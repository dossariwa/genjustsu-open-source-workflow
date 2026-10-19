"""Dreamina Canvas CLI bridge with explicit credit approval and durable recovery.

Only ``node run`` spends generation credits. Its identity and a submitting marker
are fsynced before dispatch; recovery only observes that identity, never reruns it.
The installed CLI schema and authenticated model catalog are the authority.
"""
from contextlib import contextmanager
from pathlib import Path
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import secrets
import subprocess
import tempfile
import time
import uuid

from config import setting
from audio_workflow import finish_preview

STATE_FILE = 'dreamina-state.json'
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.webm', '.mkv', '.m4v'}


class DreaminaError(RuntimeError):
    """A safe diagnostic: raw provider payloads and secrets are never persisted."""


class CreditApprovalRequired(DreaminaError):
    def __init__(self, amount, message=None):
        self.minimum_credit_ceiling = amount
        super().__init__(message or f'Dreamina quoted {amount} credits. Approve a credit ceiling to submit the saved draft.')


class RecoveryRequired(DreaminaError):
    pass


def _atomic_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _command(schema, *names):
    current = schema
    for name in names:
        current = next((item for item in current.get('subcommands', []) if item['name'] == name), None)
        if current is None:
            raise DreaminaError('Installed Dreamina CLI does not support ' + ' '.join(names))
    return current


def capabilities(schema=None):
    """Read-only capabilities; no sign-in, canvas creation or generation."""
    if schema is None:
        schema = DreaminaCanvasBridge()._call(['schema'])['data']
    create = _command(schema, 'node', 'create', 'video')
    modes = next((flag.get('constraints', '') for flag in create['flags'] if flag['name'] == 'mode'), '')
    upscale = _command(schema, 'node', 'upscale')
    download = _command(schema, 'resource', 'download')
    return {
        'provider': 'dreamina-canvas',
        'mode': 'm2v',
        'mode_label': 'Dreamina Omni (m2v)',
        'native_edit': 'edit' in modes.split('|'),
        'video_hd_supported': any(item['name'] == 'video' for item in upscale.get('subcommands', [])),
        'video_download_verified': 'video' in download.get('summary', '').lower(),
        'download_contract': download.get('summary', ''),
    }


def _safe_error(envelope):
    error = envelope.get('error')
    error = error if isinstance(error, dict) else {}
    # Codes/actions are useful without logging URLs, auth material or prompt text.
    code = error.get('code', 'cli.invalid_response')
    if not isinstance(code, str) or len(code) > 128 or not re.fullmatch(r'[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+', code):
        code = 'cli.invalid_response'
    action = error.get('requiredAction')
    if action not in ('login', 'resume', 'confirm', 'retry', 'none', 'upgrade', 'fix_input', 'contact_support'):
        action = None
    return f'Dreamina CLI: {code}' + (f' (required action: {action})' if action else '')


def _decode_cli_result(result):
    """Decode stdout success or a structured stdout/stderr failure, never raw logs."""
    def envelope(text):
        try:
            value = json.loads(text)
        except (TypeError, ValueError):
            return None
        if not isinstance(value, dict) or not isinstance(value.get('ok'), bool):
            return None
        return value

    stdout = envelope(result.stdout)
    if result.returncode:
        # Canvas 1.0.3 writes nonzero error/partial-result envelopes to stderr.
        # Junk stdout or an `ok:true` envelope cannot override the failed exit.
        for candidate in (envelope(result.stderr), stdout):
            if candidate is not None and candidate['ok'] is False and isinstance(candidate.get('error'), dict):
                return candidate
        raise DreaminaError('Dreamina CLI exited unsuccessfully without a valid failure response; raw output was not saved.')
    if stdout is None:
        raise DreaminaError('Dreamina CLI returned an invalid JSON response; raw output was not saved.')
    return stdout


def entitlement_status(mode, resolution, account):
    """Compare advertised membership constraints, without claiming admission."""
    model_requirement = mode.get('vipRequired')
    vip_resolutions = mode.get('vipResolutions')
    resolution_required = isinstance(vip_resolutions, list) and any(
        isinstance(value, str) and value.casefold() == str(resolution).casefold()
        for value in vip_resolutions
    )
    required = True if model_requirement is True or resolution_required else None
    if model_requirement is False and isinstance(vip_resolutions, list) and not resolution_required:
        required = False
    account_vip = account.get('isVip') if isinstance(account, dict) else None
    if not isinstance(account_vip, bool):
        account_vip = None
    blocked = required is True and account_vip is False
    if blocked:
        detail = (f'Advertised VIP requirement unmet for {resolution}: the authenticated account reports no VIP membership. '
                  'Server admission is untested; no purchase or generation was made.')
    elif required is True and account_vip is True:
        detail = f'Advertised VIP requirement for {resolution} matches account membership; server admission remains untested.'
    elif required is True:
        detail = f'{resolution} advertises a VIP requirement, but account membership is unavailable; server admission remains untested.'
    elif required is False:
        detail = f'No VIP requirement is advertised for {resolution}; server admission remains untested.'
    else:
        detail = f'Membership requirements for {resolution} are not fully advertised; server admission remains untested.'
    return {'required': required, 'account_is_vip': account_vip, 'blocked': blocked, 'detail': detail}


def _geometry(path):
    import av
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError('Prepared source has no video stream.')
        stream = container.streams.video[0]
        duration = float(stream.duration * stream.time_base) if stream.duration else float(container.duration / av.time_base)
        if not duration or not math.isfinite(duration):
            raise ValueError('Prepared source duration is unavailable.')
        if not container.streams.audio:
            raise ValueError('Prepared source must contain the reviewed guidance audio.')
        return {'duration': duration, 'width': stream.width, 'height': stream.height}


def _flag_map(mode):
    return {item['flag'].lstrip('-'): item for item in mode.get('flags', [])}


def draft_resolution(mode):
    """Return the canonical spelling of this workflow's 720p review resolution."""
    resolutions = _flag_map(mode).get('resolution', {}).get('values', [])
    resolution = next((value for value in resolutions if str(value).lower() == '720p'), None)
    if resolution is None:
        raise DreaminaError('The selected Dreamina model does not advertise a 720p draft resolution.')
    return resolution


def _video_parameters(mode, geometry):
    flags = _flag_map(mode)
    for name in ('resolution', 'ratio', 'duration'):
        if name not in flags:
            raise DreaminaError(f'The selected model does not advertise --{name}; cannot preserve the source framing/duration.')
    resolution = draft_resolution(mode)
    ratios = flags['ratio'].get('values', [])
    parsed = {}
    for value in ratios:
        try:
            a, b = str(value).split(':')
            parsed[value] = float(a) / float(b)
        except (ValueError, ZeroDivisionError):
            continue
    if not parsed:
        raise DreaminaError('The selected model does not advertise usable aspect ratios.')
    source_ratio = geometry['width'] / geometry['height']
    ratio = min(parsed, key=lambda value: abs(parsed[value] - source_ratio))
    duration_spec = flags['duration']
    values = duration_spec.get('values')
    if values:
        durations = [float(value) for value in values]
        duration = min(durations, key=lambda value: (abs(value - geometry['duration']), -value))
    else:
        low, high, step = duration_spec.get('min'), duration_spec.get('max'), duration_spec.get('step')
        if low is None or high is None or step is None or step <= 0:
            raise DreaminaError('The model duration range/step is not advertised; refusing to guess supported values.')
        duration = min(high, max(low, low + math.floor((geometry['duration'] - low) / step + .5) * step))
    if abs(duration - geometry['duration']) > .5:
        raise DreaminaError('The nearest supported model duration differs from the source by more than 0.5 seconds. Use a compatible source/model before spending credits.')
    return {'resolution': resolution, 'aspect_ratio': ratio, 'duration': duration,
            'source_duration': geometry['duration'],
            'last_frame_hold_seconds': max(0.0, geometry['duration'] - duration)}


def _validate_references(mode, assets):
    rules = mode.get('references')
    if not rules or not rules.get('types'):
        raise DreaminaError('The selected model does not advertise usable multimodal references.')
    if not rules.get('min', 0) <= len(assets) <= rules.get('max', 0):
        raise DreaminaError('Reference count is outside the selected model limits.')
    counts = {}
    for asset in assets:
        counts[asset['type']] = counts.get(asset['type'], 0) + 1
    types = {rule['mediaType']: rule for rule in rules['types']}
    for kind, count in counts.items():
        if kind not in types or not types[kind].get('min', 0) <= count <= types[kind].get('max', 0):
            raise DreaminaError(f'The selected model cannot accept {count} {kind} reference(s).')
    for kind, rule in types.items():
        if counts.get(kind, 0) < rule.get('min', 0):
            raise DreaminaError(f'The selected model requires a {kind} reference.')
    if rules.get('requireAnyOfTypes') and not any(counts.get(kind) for kind in rules['requireAnyOfTypes']):
        raise DreaminaError('Required reference media types are missing.')
    if sum(bool(counts.get(kind)) for kind in rules.get('mutuallyExclusiveTypes', [])) > 1:
        raise DreaminaError('The selected model forbids this combination of reference media types.')


class DreaminaCanvasBridge:
    def __init__(self, folder=None, status=print):
        self.folder = Path(folder) if folder is not None else None
        self.status = status
        self.profile = setting('DREAMINA_PROFILE', 'default')
        self.binary = setting('DREAMINA_CLI_BIN', 'dreamina-canvas')
        located = shutil.which(self.binary)
        if not located and self.binary in ('dreamina', 'dreamina-canvas'):
            candidate = Path.home() / '.local/bin/dreamina-canvas'
            if candidate.is_file():
                located = str(candidate)
        self.binary = located or self.binary
        self.state = None

    @contextmanager
    def _lock(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        with (self.folder / '.dreamina.lock').open('a') as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _call(self, args, timeout=60, allow_error=False):
        command = [self.binary, '--format', 'json', '--non-interactive', '--profile', self.profile, *map(str, args)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        except FileNotFoundError as exc:
            raise DreaminaError('Dreamina Canvas CLI is missing. Install it or set DREAMINA_CLI_BIN.') from exc
        except subprocess.TimeoutExpired as exc:
            raise RecoveryRequired('Dreamina CLI timed out. Saved operation identity must be inspected; do not start a new generation.') from exc
        envelope = _decode_cli_result(result)
        meta = envelope.get('meta')
        request_id = meta.get('requestId') if isinstance(meta, dict) else None
        if self.state is not None and isinstance(request_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', request_id):
            self.state['last_request_id'] = request_id
            self._save()
        if (result.returncode or not envelope.get('ok')) and not allow_error:
            raise DreaminaError(_safe_error(envelope))
        return envelope

    def _load(self):
        path = self.folder / STATE_FILE
        self.state = json.loads(path.read_text()) if path.exists() else None
        if self.state:
            if self.state.get('provider') != 'dreamina-canvas':
                raise DreaminaError('Saved generation belongs to a different provider.')
            self.profile = self.state['profile']
        return self.state

    def _save(self):
        self.state['state'] = {'submission_unknown': 'uncertain'}.get(self.state['status'], self.state['status'])
        _atomic_json(self.folder / STATE_FILE, self.state)
        # Preserve the app/agent CLI read contract while exposing the actual mode.
        generation = {key: self.state[key] for key in (
            'provider', 'status', 'state', 'prompt', 'project_id', 'node_id', 'submit_id', 'mode',
            'model', 'resolution', 'aspect_ratio', 'duration', 'source_duration',
            'last_frame_hold_seconds', 'minimum_credit_ceiling', 'approved_credit_ceiling',
            'web_url', 'resource_id', 'download_sha256') if key in self.state}
        generation.update(request_id=self.state['submit_id'], video='seedance-result.mp4',
                          mode_label='Dreamina Omni (m2v)', is_draft=True)
        _atomic_json(self.folder / 'generation.json', generation)

    def _persist_command(self, args):
        if '--credit-token' in args:
            raise AssertionError('Credit tokens must never be saved.')
        self.state['last_command'] = [str(value) for value in args]
        self._save()

    def _preflight(self, model_name):
        version = self._call(['--version'])['data']
        schema = self._call(['schema'])['data']
        for path in [('canvas', 'create'), ('resource', 'upload'), ('node', 'create', 'video'),
                     ('node', 'show'), ('node', 'quote'), ('node', 'confirm'), ('node', 'run'),
                     ('operation', 'wait'), ('resource', 'download')]:
            _command(schema, *path)
        auth = self._call(['auth', 'status'])['data']
        if not auth.get('loggedIn'):
            raise DreaminaError('Dreamina is not authenticated. Run dreamina-canvas auth login for the configured profile, then retry.')
        catalog = self._call(['model', 'find', model_name, '--type', 'video'])['data'].get('items', [])
        exact = [item for item in catalog if item.get('model') == model_name]
        candidates = exact or catalog
        if len(candidates) != 1:
            raise DreaminaError('DREAMINA_DRAFT_MODEL does not resolve to exactly one canonical video model; inspect dreamina-canvas model list --type video.')
        item = candidates[0]
        modes = [mode for mode in item.get('modes', []) if mode.get('name') == 'm2v']
        if len(modes) != 1:
            raise DreaminaError('The configured Dreamina model has no unambiguous m2v mode for the prepared source video.')
        entitlement = self._check_entitlement(modes[0], draft_resolution(modes[0]))
        caps = capabilities(schema)
        caps['entitlement'] = entitlement
        return version, auth, item['model'], modes[0], caps

    def _check_entitlement(self, mode, resolution):
        account = self._call(['auth', 'account'])['data']
        entitlement = entitlement_status(mode, resolution, account)
        if entitlement['blocked']:
            raise DreaminaError(entitlement['detail'])
        return entitlement

    def _check_artifacts(self):
        from mask_review import require_approved
        require_approved(self.folder)
        for asset in self.state['assets']:
            path = Path(asset['path'])
            if not path.is_file() or _digest(path) != asset['sha256']:
                raise ValueError('A prepared source or identity reference changed after the generation was saved. Prepare a new job and review it again.')

    def submit_draft(self, prompt, sirio, tein=None, credit_ceiling=None):
        from mask_review import require_approved
        with self._lock():
            require_approved(self.folder)
            self._load()
            if self.state:
                if prompt != self.state['prompt'] or [str(Path(p).resolve()) for p in [sirio] + ([tein] if tein else [])] != [a['path'] for a in self.state['assets'][1:]]:
                    raise ValueError('This job already has a saved prompt and references. Resume it unchanged or prepare a new job for a deliberate variation.')
                return self._resume_submission(credit_ceiling)
            if (self.folder / 'seedance-response.json').exists():
                raise ValueError('This job already has a provider response. Resume it using its original provider; never resubmit automatically.')
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError('Show and approve a non-empty creative prompt before submission.')
            prepared = self.folder / 'seedance-input.mp4'
            if not prepared.is_file() or not (self.folder / 'audio-manifest.json').is_file():
                raise ValueError('Prepare the composite with embedded guidance audio, then review it before submission.')
            paths = [prepared, Path(sirio)] + ([Path(tein)] if tein else [])
            assets = []
            for path in paths:
                if not path.is_file():
                    raise ValueError('A source or identity reference file is missing.')
                assets.append({'path': str(path.resolve()), 'type': 'video' if path.suffix.lower() in VIDEO_EXTENSIONS else 'image',
                               'sha256': _digest(path), 'resource_id': str(uuid.uuid4()), 'uploaded': False})
            version, auth, model, mode, caps = self._preflight(setting('DREAMINA_DRAFT_MODEL', 'seedance_2.0_mini'))
            _validate_references(mode, assets)
            parameters = _video_parameters(mode, _geometry(prepared))
            self.state = {
                'provider': 'dreamina-canvas', 'status': 'preparing', 'profile': self.profile,
                'region': auth.get('region'), 'environment': auth.get('environment'),
                'cli_version': version.get('version'), 'project_id': str(uuid.uuid4()),
                'node_id': 'node_' + ''.join(secrets.choice('0123456789abcdefghjkmnpqrstvwxyz') for _ in range(10)), 'update_id': str(uuid.uuid4()),
                'submit_id': str(uuid.uuid4()), 'prompt': prompt, 'model': model, 'mode': 'm2v',
                'assets': assets, 'model_mode': mode, 'capabilities': caps,
                'canvas_created': False, 'node_saved': False, 'submit_attempted': False, **parameters,
            }
            self._save()  # Business keys exist durably before any remote mutation.
            return self._resume_submission(credit_ceiling)

    def _resume_submission(self, credit_ceiling):
        self._check_artifacts()
        if self.state.get('submit_attempted'):
            self.status('Resuming the saved Dreamina operation; no new generation is submitted.')
            return self.state['submit_id']
        if credit_ceiling is not None:
            if isinstance(credit_ceiling, bool) or not isinstance(credit_ceiling, int) or credit_ceiling < 0:
                raise ValueError('An explicitly approved non-negative integer credit ceiling is required.')
        self._check_context()
        self._check_entitlement(self.state['model_mode'], self.state['resolution'])
        project = self.state['project_id']
        if not self.state['canvas_created']:
            args = ['canvas', 'create', 'Video workflow ' + self.folder.name, '--project-id', project]
            self._persist_command(args)
            result = self._call(args)['data']['project']
            if result['projectId'] != project:
                raise DreaminaError('Dreamina returned a different canvas identity.')
            self.state.update(canvas_created=True, web_url=result.get('webUrl'))
            self._save()
            self.status('Dreamina canvas: ' + (result.get('webUrl') or project))
        for asset in self.state['assets']:
            if asset['uploaded']:
                continue
            args = ['resource', 'upload', '--file', asset['path'], '--type', asset['type'],
                    '--project-id', project, '--resource-id', asset['resource_id'], '--import-kind', 'local_upload']
            self._persist_command(args)
            result = self._call(args, timeout=300)['data']
            if result.get('resourceId') != asset['resource_id'] or result.get('mediaType') != asset['type']:
                raise DreaminaError('Dreamina upload identity or media type did not match the saved asset.')
            asset['uploaded'] = True
            self._save()
        if not self.state['node_saved']:
            if self.state.get('node_save_attempted'):
                shown = self._show_node()
                if shown is not None:
                    self._verify_node(shown)
                    self.state['node_saved'] = True
                    self._save()
            if not self.state['node_saved']:
                args = ['node', 'create', 'video', '--project-id', project, '--node-id', self.state['node_id'],
                        '--update-id', self.state['update_id'], '--title', '720p review draft', '--mode', 'm2v',
                        '--model', self.state['model'], '--prompt', self.state['prompt'],
                        '--resolution', self.state['resolution'], '--ratio', self.state['aspect_ratio'],
                        '--duration', str(self.state['duration'])]
                if 'count' in _flag_map(self.state['model_mode']):
                    args += ['--count', '1']
                for asset in self.state['assets']:
                    args += ['--ref', 'res:' + asset['resource_id']]
                self.state['node_save_attempted'] = True
                self._persist_command(args)
                self._call(args)
                self._verify_node(self._show_node())
                self.state['node_saved'] = True
                self._save()
        else:
            self._verify_node(self._show_node())
        self._check_artifacts()
        quote = self._call(['node', 'quote', '--project-id', project, '--node-id', self.state['node_id']])['data']
        items = quote.get('items', [])
        amount = quote.get('totalMaxCredits')
        if (not quote.get('confirmable') or not isinstance(amount, int) or amount < 0 or len(items) != 1
                or items[0].get('nodeId') != self.state['node_id'] or items[0].get('error')
                or items[0].get('generationDiff')):
            raise DreaminaError('Dreamina did not return a complete, unchanged credit quote. No generation was submitted.')
        self.state.update(status='awaiting_credit_approval', minimum_credit_ceiling=amount)
        self._save()
        if credit_ceiling is None or credit_ceiling < amount:
            raise CreditApprovalRequired(amount)
        confirmed = self._call(['node', 'confirm', '--project-id', project, '--node-id', self.state['node_id'],
                                '--credit-ceiling', str(credit_ceiling)])['data']
        token = confirmed.get('creditConfirmationToken')
        if not token:
            raise DreaminaError('Dreamina did not return credit authorization. No generation was submitted.')
        self._check_artifacts()
        self._verify_node(self._show_node())
        self.status('Exact prompt submitted to Dreamina:\n' + self.state['prompt'])
        if self.state.get('last_frame_hold_seconds'):
            self.status(f"Source audio requires a final-frame hold of {self.state['last_frame_hold_seconds']:.3f}s after generation.")
        args = ['node', 'run', '--project-id', project, '--node-id', self.state['node_id'], '--submit-id', self.state['submit_id']]
        self.state.update(status='submitting', submit_attempted=True, approved_credit_ceiling=credit_ceiling)
        self._persist_command(args)
        try:
            result = self._call(args + ['--credit-token', token], allow_error=True)
        except Exception:
            self.state['status'] = 'submission_unknown'
            self._save()
            raise
        finally:
            token = None
        data = result.get('data') or result.get('partialData') or {}
        matched = [item for item in data.get('items', []) if item.get('nodeId') == self.state['node_id'] and item.get('submitId') == self.state['submit_id']]
        if not matched or str(matched[0].get('state', '')).lower() not in ('accepted', 'completed', 'in_progress'):
            self.state['status'] = 'submission_unknown'
            self._save()
            raise RecoveryRequired('Dreamina submission has no confirmed acceptance. Inspect the saved operation; automatic resubmission is disabled.')
        self.state['status'] = 'submitted'
        self._save()
        _atomic_json(self.folder / 'seedance-response.json', {'requestId': self.state['submit_id'], 'provider': 'dreamina-canvas'})
        self.status('Dreamina draft submitted: ' + self.state['submit_id'])
        return self.state['submit_id']

    def _check_context(self):
        auth = self._call(['auth', 'status'])['data']
        if not auth.get('loggedIn'):
            raise DreaminaError('Dreamina authentication expired. Sign in to the saved profile and resume the same operation.')
        if any(auth.get(key) != self.state.get(key) for key in ('region', 'environment')):
            raise RecoveryRequired('Dreamina region/environment changed since this job was saved. Restore the original context before continuing.')

    def _show_node(self):
        data = self._call(['node', 'show', '--project-id', self.state['project_id'], '--node-id', self.state['node_id']])['data']
        nodes = data.get('nodes', [])
        for item in nodes:
            if item.get('nodeId') == self.state['node_id'] and item.get('result') == 'FOUND':
                return item.get('node')
        return None

    def _verify_node(self, node):
        generation = (node or {}).get('generation', {})
        expected = [('resource', asset['resource_id']) for asset in self.state['assets']]
        references = [('resource' if item.get('kind') in ('resource', 'res') else item.get('kind'), item.get('id')) for item in generation.get('references', [])]
        # Schema uses `kind=resource` for res: references. Never infer an upstream node.
        if generation.get('prompt') != self.state['prompt'] or references != expected:
            raise DreaminaError('Saved Dreamina prompt or ordered references differ from the approved request. No generation was submitted.')
        if generation.get('outputCount') != 1:
            raise DreaminaError('Saved Dreamina output count differs from the single approved output. No generation was submitted.')
        for name, expected_value in (('mode', 'm2v'), ('model', self.state['model']), ('resolution', self.state['resolution']),
                                     ('ratio', self.state['aspect_ratio']), ('durationSeconds', self.state['duration'])):
            if generation.get(name) != expected_value:
                raise DreaminaError(f'Saved Dreamina {name} differs from the approved request. No generation was submitted.')

    def resume_preparation(self):
        """Finish an interrupted save/upload, stopping at a fresh quote without spending."""
        with self._lock():
            if not self._load():
                raise ValueError('No saved Dreamina preparation is available to resume.')
            if self.state.get('submit_attempted'):
                raise RecoveryRequired('Generation submission was already attempted. Use read-only operation recovery instead.')
            # A saved ceiling is historical information, never renewed approval.
            return self._resume_submission(None)

    def resume_approved(self, credit_ceiling):
        with self._lock():
            if not self._load():
                raise ValueError('No saved Dreamina draft is available for credit approval.')
            return self._resume_submission(credit_ceiling)

    def collect_result(self, submit_id=None):
        with self._lock():
            if not self._load():
                raise RecoveryRequired('No saved Dreamina operation exists. Legacy jobs are not automatically migrated or resubmitted.')
            if submit_id and submit_id != self.state['submit_id']:
                raise ValueError('The requested operation does not match this job.')
            if not self.state.get('submit_attempted'):
                if self.state.get('status') == 'awaiting_credit_approval':
                    raise CreditApprovalRequired(self.state.get('minimum_credit_ceiling'))
                raise RecoveryRequired('The canvas draft has not been submitted. Resume the saved preparation explicitly.')
            if self.state.get('status') == 'completed' and (self.folder / 'final-preview.mp4').is_file():
                return self.folder / 'final-preview.mp4'
            self._check_context()
            deadline = time.monotonic() + float(setting('DREAMINA_WAIT_SECONDS', '3600'))
            while True:
                result = self._call(['operation', 'wait', self.state['submit_id'], '--project-id', self.state['project_id'],
                                     '--timeout', '30s', '--interval', '5s'], timeout=45, allow_error=True)
                data = result.get('data') or result.get('partialData') or {}
                if data.get('operationRef') not in (None, self.state['submit_id']):
                    raise DreaminaError('Dreamina returned the wrong operation identity.')
                resource_states = [{'resourceId': r.get('resourceId'), 'state': r.get('state')} for r in data.get('resources', [])]
                snapshot = {'operationRef': self.state['submit_id'], 'state': data.get('state'),
                            'submission_state': data.get('submission', {}).get('state'), 'resources': resource_states}
                _atomic_json(self.folder / 'provider-status.json', snapshot)
                state = str(data.get('state', '')).lower()
                submission_state = str(data.get('submission', {}).get('state', '')).lower()
                if state in ('failed', 'canceled', 'cancelled', 'rejected') or submission_state == 'rejected':
                    self.state['status'] = 'failed'
                    self._save()
                    raise DreaminaError('Dreamina generation failed. The operation is retained; no replacement was submitted.')
                if state in ('succeeded', 'completed'):
                    if len(resource_states) != 1 or not resource_states[0]['resourceId'] or str(resource_states[0]['state']).lower() != 'succeeded':
                        raise RecoveryRequired('Dreamina reported completion without exactly one successful output. Resume inspection; do not resubmit.')
                    resource = resource_states[0]['resourceId']
                    self.state.update(status='result_available', resource_id=resource)
                    self._save()
                    break
                if submission_state in ('absent', 'unknown') or state == 'unknown':
                    self.state['status'] = 'submission_unknown'
                    self._save()
                    raise RecoveryRequired('Dreamina cannot establish the submission state. Inspect the saved canvas/operation; absent records do not authorize resubmission.')
                if not result.get('ok') and result.get('error', {}).get('requiredAction') != 'resume':
                    raise DreaminaError(_safe_error(result))
                if time.monotonic() >= deadline:
                    raise TimeoutError('Dreamina is still pending. Resume the saved operation; do not submit again.')
                self.status('Dreamina is still generating; the saved operation remains resumable.')
            media = self._call(['resource', 'get', resource, '--project-id', self.state['project_id']])['data']
            if media.get('type') != 'video' or str(media.get('status', '')).lower() not in ('success', 'succeeded'):
                raise DreaminaError('The selected output is not a successful video resource.')
            target = self.folder / 'seedance-result.mp4'
            if not target.is_file() or _digest(target) != self.state.get('download_sha256'):
                temporary = self.folder / 'dreamina-download.mp4'
                try:
                    downloaded = self._call(['resource', 'download', resource, '--project-id', self.state['project_id'],
                                             '--output', str(temporary.resolve())], timeout=300)['data']
                except DreaminaError as exc:
                    self.state['status'] = 'result_available_download_blocked'
                    self._save()
                    raise DreaminaError('The result exists, but this Dreamina CLI could not download its video. Its installed schema advertises image download only. The canvas and operation are preserved; no new generation was submitted.') from exc
                if (not temporary.is_file() or temporary.stat().st_size <= 0 or downloaded.get('size') != temporary.stat().st_size
                        or downloaded.get('sha256') != _digest(temporary)):
                    raise DreaminaError('Downloaded media size or checksum validation failed.')
                import av
                with av.open(str(temporary)) as video:
                    if not video.streams.video or next(video.decode(video=0), None) is None:
                        raise DreaminaError('Downloaded resource contains no decodable video frame.')
                os.replace(temporary, target)
                self.state['download_sha256'] = downloaded['sha256']
                self._save()
            self.status('Restoring the configured complete final audio and discarding generated audio')
            final = finish_preview(target, self.folder)
            shutil.copy2(final, self.folder / 'draft_final.mp4')
            self.state['status'] = 'completed'
            self._save()
            return final

    def submit_hd_upgrade(self, approved=False):
        if not approved:
            raise ValueError('Explicit HD approval is required. No upgrade was submitted.')
        # 1.0.3 only exposes image upscale and no video draft-completion lineage.
        # A fresh 1080p generation is not an upgrade of the accepted draft.
        raise DreaminaError('This Dreamina Canvas CLI has no verified video HD upgrade/draft-completion command. The accepted 720p draft is preserved; no new generation or charge was made.')


def submit(folder, prompt, sirio, tein=None, status=print, credit_ceiling=None):
    return DreaminaCanvasBridge(folder, status).submit_draft(prompt, sirio, tein, credit_ceiling)


def resume_preparation(folder, status=print):
    return DreaminaCanvasBridge(folder, status).resume_preparation()


def resume_approved(folder, credit_ceiling, status=print):
    return DreaminaCanvasBridge(folder, status).resume_approved(credit_ceiling)


def wait_and_finish(folder, request_id, status=print):
    return DreaminaCanvasBridge(folder, status).collect_result(request_id)


def submit_hd(folder, approved=False):
    return DreaminaCanvasBridge(folder).submit_hd_upgrade(approved=approved)

"""OpenArt Seedance draft adapter with explicit credit gates and durable recovery.

Discovery and quotes are read-only. Only the final generate tool spends credits;
an attempt marker is synced before that call and an uncertain call is never
repeated. Provider URLs live only in memory, never in persisted job metadata.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import uuid

from audio_workflow import finish_preview
from config import setting

STATE_FILE = 'openart-state.json'
MODEL = 'byte-plus-seedance-2-5-draft'
MODE = 'element2video'
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.webm', '.mkv', '.m4v'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.heic', '.heif'}


class OpenArtError(RuntimeError):
    """Safe diagnostics that exclude raw provider errors and private URLs."""


class CreditApprovalRequired(OpenArtError):
    def __init__(self, amount, message=None):
        self.minimum_credit_ceiling = amount
        super().__init__(message or f'OpenArt quoted {amount} credits. Approve a credit ceiling for this saved request.')


class RecoveryRequired(OpenArtError):
    pass


def _atomic_json(path, value):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}', value) is not None


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _account_context(account):
    uid = account.get('user', {}).get('uid')
    workspace = account.get('workspace') or {}
    if not _identifier(uid) or (workspace and not _identifier(workspace.get('id'))):
        raise OpenArtError('OpenArt did not return a verifiable account/workspace identity.')
    return {'account_fingerprint': hashlib.sha256(uid.encode()).hexdigest(),
            'workspace_id': workspace.get('id')}


def _geometry(path):
    import av
    with av.open(str(path)) as container:
        if not container.streams.video or not container.streams.audio:
            raise ValueError('Prepared source must contain video and the reviewed embedded guidance audio.')
        stream = container.streams.video[0]
        duration = float(stream.duration * stream.time_base) if stream.duration else float(container.duration / av.time_base)
        if not duration or not math.isfinite(duration):
            raise ValueError('Prepared source duration is unavailable.')
        return {'duration': duration, 'width': stream.width, 'height': stream.height}


def _validate_schema(schema):
    properties = schema.get('properties', {})
    expected = {'prompt': 'string', 'videoCount': 'integer', 'duration': 'integer',
                'aspectRatio': 'string', 'resolution': 'string', 'generateAudio': 'boolean',
                'autoEnhancePrompt': 'boolean', 'visualReferences': 'array'}
    if schema.get('type') != 'object' or any(properties.get(key, {}).get('type') != kind for key, kind in expected.items()):
        raise OpenArtError('The live OpenArt input schema does not support this prepared-video workflow.')
    if not set(schema.get('required', [])).issubset(expected):
        raise OpenArtError('The live OpenArt model requires additional inputs; inspect its current schema before submitting.')
    resolution = properties['resolution']
    if resolution.get('const') != '480p' and '480p' not in resolution.get('enum', []):
        raise OpenArtError('The selected OpenArt model does not advertise the required 480p draft resolution.')
    for key, value in (('videoCount', 1), ('generateAudio', True), ('autoEnhancePrompt', False)):
        rule = properties[key]
        if (('const' in rule and rule['const'] != value)
                or ('enum' in rule and value not in rule['enum'])
                or (key == 'videoCount' and not rule.get('minimum', 1) <= value <= rule.get('maximum', 1))):
            raise OpenArtError('The live OpenArt schema no longer accepts one output with exact prompt and audio guidance settings.')
    reference = properties['visualReferences'].get('items', {})
    if not all(reference.get('properties', {}).get(key, {}).get('type') == 'string' for key in ('type', 'id', 'url', 'label')):
        raise OpenArtError('The live OpenArt reference contract is incompatible with the saved workflow.')
    return properties


def _video_parameters(schema, geometry):
    properties = _validate_schema(schema)
    ratios = {}
    for value in properties['aspectRatio'].get('enum', []):
        try:
            left, right = value.split(':')
            ratios[value] = float(left) / float(right)
        except (ValueError, ZeroDivisionError, AttributeError):
            continue
    if not ratios:
        raise OpenArtError('OpenArt does not advertise a usable aspect ratio.')
    ratio = min(ratios, key=lambda value: abs(ratios[value] - geometry['width'] / geometry['height']))
    spec = properties['duration']
    low, high = spec.get('minimum'), spec.get('maximum')
    step = spec.get('multipleOf', 1)
    if not all(_number(value) for value in (low, high, step)) or step <= 0 or int(step) != step:
        raise OpenArtError('OpenArt does not advertise a usable integer duration range.')
    first, last = math.ceil(low / step) * step, math.floor(high / step) * step
    if first > last:
        raise OpenArtError('OpenArt advertises no usable duration.')
    duration = int(min(last, max(first, math.floor(geometry['duration'] / step + .5) * step)))
    if abs(duration - geometry['duration']) > .5:
        raise OpenArtError('The nearest supported OpenArt duration differs from the source by more than 0.5 seconds. Use a compatible source before spending credits.')
    return {'resolution': '480p', 'aspect_ratio': ratio, 'duration': duration,
            'source_duration': geometry['duration'],
            'last_frame_hold_seconds': max(0.0, geometry['duration'] - duration)}


def capabilities():
    """Static verified contract; an actual HD action is checked on the draft."""
    return {'provider': 'openart', 'mode': MODE, 'mode_label': 'OpenArt reference video (element2video)',
            'native_edit': False, 'video_hd_supported': False, 'provider_draft_upgrade_offered': True,
            'hd_requires_saved_action': True,
            'video_download_verified': False,
            'download_contract': 'Download a completed provider video and restore the complete configured source audio.'}


class OpenArtBridge:
    def __init__(self, folder=None, status=print, transport=None):
        self.folder = Path(folder) if folder is not None else None
        self.status = status or (lambda message: None)
        if transport is None:
            from openart_transport import OpenArtTransport
            transport = OpenArtTransport()
        self.transport = transport
        self.state = None

    def _call(self, tool, arguments):
        try:
            result = self.transport.call(tool, arguments)
        except Exception:
            # Raw HTTP/CLI messages may contain signed URLs or credentials.
            raise OpenArtError('OpenArt request failed; account connectivity or provider availability needs checking. Raw provider output was not saved.') from None
        if not isinstance(result, dict):
            raise OpenArtError('OpenArt returned an invalid response; raw provider output was not saved.')
        return result

    def _preflight(self):
        model = setting('OPENART_DRAFT_MODEL', MODEL)
        if model != MODEL or setting('OPENART_DRAFT_RESOLUTION', '480p') != '480p':
            raise OpenArtError('This workflow is configured for OpenArt Seedance 2.5 Draft at 480p. Restore OPENART_DRAFT_MODEL and OPENART_DRAFT_RESOLUTION before continuing.')
        account = self._call('openart_account_get', {})
        context = _account_context(account)
        models = self._call('openart_model_list', {}).get('models', [])
        exact = [item for item in models if item.get('id') == model]
        if len(exact) != 1:
            raise OpenArtError('The configured OpenArt draft model is absent from the authenticated model catalog.')
        modes = [item for item in exact[0].get('modes', {}).get('video', []) if item.get('mode') == MODE]
        if len(modes) != 1 or not {'image', 'video'}.issubset(modes[0].get('elementTypes', [])):
            raise OpenArtError('The OpenArt model does not advertise both video and image references in element2video mode.')
        form = self._call('openart_model_form_get', {'model': model, 'mode': MODE})
        if form.get('model') != model or form.get('mode') != MODE or form.get('media') != 'video':
            raise OpenArtError('OpenArt returned a model schema for a different model or mode.')
        _validate_schema(form.get('jsonSchema', {}))
        return account, context, model, form['jsonSchema']

    def readiness(self):
        account, _, model, _ = self._preflight()
        credits = account.get('credits')
        return {'provider': 'openart', 'authenticated': True, 'plan': account.get('plan'),
                'cli_version': getattr(self.transport, 'cli_version', None),
                'credits': credits if _number(credits) else None, 'model': model,
                'model_verified': True, 'schema_verified': True, 'mode': MODE, 'resolution': '480p',
                'capabilities': capabilities(),
                'generation_blockers': [] if _number(credits) else ['OpenArt account credit balance is unavailable.'],
                'live_generation_verified': False}

    @contextmanager
    def _lock(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        with (self.folder / '.openart.lock').open('a') as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _load(self):
        path = self.folder / STATE_FILE
        self.state = json.loads(path.read_text()) if path.exists() else None
        if self.state and self.state.get('provider') != 'openart':
            raise OpenArtError('This saved job belongs to a different generation provider.')
        return self.state

    def _save(self):
        self.state['state'] = 'uncertain' if self.state['status'] == 'submission_unknown' else self.state['status']
        _atomic_json(self.folder / STATE_FILE, self.state)
        public = {key: self.state[key] for key in (
            'provider', 'status', 'state', 'prompt', 'project_id', 'submit_id', 'history_id', 'mode',
            'model', 'resolution', 'aspect_ratio', 'duration', 'source_duration', 'last_frame_hold_seconds',
            'minimum_credit_ceiling', 'approved_credit_ceiling', 'resource_id', 'download_sha256',
            'reference_labels', 'parent_history_id', 'is_draft') if key in self.state}
        public.update(request_id=self.state['submit_id'], video='seedance-result.mp4',
                      mode_label='OpenArt draft upgrade' if not self.state.get('is_draft', True) else capabilities()['mode_label'])
        _atomic_json(self.folder / 'generation.json', public)

    def _check_artifacts(self):
        from mask_review import require_approved
        review_folder = Path(self.state.get('review_folder') or self.folder)
        require_approved(review_folder)
        for asset in self.state['assets']:
            path = Path(asset['path'])
            if not path.is_file() or _digest(path) != asset['sha256']:
                raise ValueError('A reviewed source or identity reference changed. Prepare and review a new job before spending credits.')

    def _project(self):
        cursor = None
        while True:
            page = self._call('openart_project_list', {'cursor': cursor} if cursor else {})
            projects = page.get('items', [])
            wanted = self.state.get('project_id') if self.state else setting('OPENART_PROJECT_ID')
            matches = [item for item in projects if item.get('id') == wanted] if wanted else [item for item in projects if item.get('isDefault')]
            if matches:
                if len(matches) != 1 or matches[0].get('canGenerate') is not True or not _identifier(matches[0].get('id')):
                    raise OpenArtError('The selected OpenArt project does not permit generation.')
                return matches[0]['id']
            next_cursor = page.get('nextCursor')
            if not page.get('hasMore') or not next_cursor or next_cursor == cursor:
                raise OpenArtError('No writable OpenArt project was found in the current workspace.')
            cursor = next_cursor

    def _check_context(self):
        context = _account_context(self._call('openart_account_get', {}))
        if any(context[key] != self.state[key] for key in context):
            raise RecoveryRequired('The OpenArt account or workspace changed. Restore the saved account and workspace before resuming.')
        self._project()

    def submit_draft(self, prompt, sirio, tein=None, credit_ceiling=None):
        from mask_review import require_approved
        with self._lock():
            require_approved(self.folder)
            self._load()
            references = [str(Path(path).resolve()) for path in [sirio] + ([tein] if tein else [])]
            if self.state:
                if prompt != self.state['prompt'] or references != [asset['path'] for asset in self.state['assets'][1:]]:
                    raise ValueError('This job already has a saved prompt and references. Resume it unchanged or prepare a new job.')
                return self._resume_submission(credit_ceiling)
            if any((self.folder / name).exists() for name in ('dreamina-state.json', 'seedance-response.json', 'generation.json')):
                raise RecoveryRequired('This job has existing generation metadata. Collect its original provider operation; automatic resubmission is disabled.')
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError('Show and approve a non-empty creative prompt before submission.')
            prepared = self.folder / 'seedance-input.mp4'
            if not prepared.is_file() or not (self.folder / 'audio-manifest.json').is_file():
                raise ValueError('Prepare a source video with embedded guidance audio and review it first.')
            assets = []
            for index, path in enumerate([prepared, *map(Path, references)]):
                kind = 'video' if path.suffix.lower() in VIDEO_EXTENSIONS else 'image'
                if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS | IMAGE_EXTENSIONS:
                    raise ValueError('A supported source or identity reference file is missing.')
                label = 'Prepared source' if index == 0 else f'Character {index} · {path.name}'
                assets.append({'path': str(path.resolve()), 'type': kind, 'sha256': _digest(path), 'label': label})
            account, context, model, schema = self._preflight()
            properties = _validate_schema(schema)
            if len(prompt) > properties['prompt'].get('maxLength', 30000):
                raise ValueError('The exact creative prompt exceeds the OpenArt model limit.')
            rules = properties['visualReferences']
            if len(assets) < rules.get('minItems', 0) or len(assets) > rules.get('maxItems', math.inf):
                raise ValueError('The reference count is outside the OpenArt model limits.')
            parameters = _video_parameters(schema, _geometry(prepared))
            project = self._project()
            self.state = {'provider': 'openart', 'status': 'preparing', 'submit_id': str(uuid.uuid4()),
                          'submit_attempted': False, 'prompt': prompt, 'model': model, 'mode': MODE,
                          'project_id': project, 'assets': assets, 'reference_labels': [asset['label'] for asset in assets],
                          'is_draft': True, **context, **parameters}
            self._save()
            return self._resume_submission(credit_ceiling)

    def _references(self):
        references = []
        for asset in self.state['assets']:
            try:
                if asset.get('upload_id'):
                    reference = self.transport.resolve_reference(asset['upload_id'], self.state['project_id'])
                else:
                    reference = self.transport.upload(Path(asset['path']), asset['type'], asset['label'], project_id=self.state['project_id'])
            except Exception:
                raise OpenArtError('OpenArt reference upload or lookup failed. Saved generation identity is retained; no generation was submitted.') from None
            if (not isinstance(reference, dict) or not _identifier(reference.get('id'))
                    or reference.get('type') != asset['type'] or not isinstance(reference.get('url'), str)
                    or not reference['url'].startswith('https://')):
                raise OpenArtError('OpenArt did not return a verified reference of the expected media type.')
            if asset.get('upload_id') and reference['id'] != asset['upload_id']:
                raise OpenArtError('OpenArt returned a different uploaded reference identity.')
            asset['upload_id'] = reference['id']
            self._save()
            # Use explicit labels to retain the reviewed ordering and mapping.
            references.append({key: value for key, value in dict(reference, label=asset['label']).items()
                               if key in ('id', 'type', 'url', 'label', 'metadata')})
        return references

    def _quote(self, model, mode, params, credit_ceiling):
        quote = self._call('openart_model_cost', {'model': model, 'mode': mode, 'params': params})
        items = quote.get('items', [])
        if quote.get('currency') != 'credits' or len(items) != 1:
            raise OpenArtError('OpenArt did not return one exact credit quote. No generation was submitted.')
        if not _number(quote.get('balance')):
            raise OpenArtError('OpenArt did not return the current credit balance. No generation was submitted.')
        row = items[0]
        amount = row.get('totalCredits')
        if row.get('model') != model or row.get('mode') != mode or row.get('quantity') != 1 or not _number(amount):
            raise OpenArtError('OpenArt returned an incompatible credit quote. No generation was submitted.')
        # The provider quote must describe the selected output settings exactly.
        config = row.get('config', {})
        for key in ('duration', 'resolution', 'aspectRatio', 'videoCount', 'generateAudio'):
            if key in params and config.get(key) != params[key]:
                raise OpenArtError('OpenArt quoted different output settings. No generation was submitted.')
        self.state.update(status='awaiting_credit_approval', minimum_credit_ceiling=amount)
        self._save()
        if row.get('affordable') is False or (_number(quote.get('balance')) and quote['balance'] < amount):
            raise CreditApprovalRequired(amount, f'OpenArt quoted {amount} credits, but the current workspace balance is insufficient. No generation was submitted.')
        if credit_ceiling is None or credit_ceiling < amount:
            raise CreditApprovalRequired(amount)
        return amount

    def _resume_submission(self, credit_ceiling):
        self._check_artifacts()
        if self.state.get('submit_attempted'):
            self.status('Collecting the saved OpenArt operation; no replacement generation is submitted.')
            return self.state['submit_id']
        if credit_ceiling is not None and (not _number(credit_ceiling) or int(credit_ceiling) != credit_ceiling):
            raise ValueError('An explicitly approved non-negative integer credit ceiling is required.')
        self._check_context()
        # Discovery is refreshed before uploads or a spend; saved settings must
        # remain accepted, rather than silently migrating a pending request.
        _, _, model, schema = self._preflight()
        if model != self.state['model']:
            raise OpenArtError('The selected model changed after this draft was saved.')
        properties = _validate_schema(schema)
        references_rule = properties['visualReferences']
        if (len(self.state['prompt']) > properties['prompt'].get('maxLength', 30000)
                or not references_rule.get('minItems', 0) <= len(self.state['assets']) <= references_rule.get('maxItems', math.inf)):
            raise OpenArtError('The saved prompt or references no longer fit the live OpenArt schema.')
        chosen = _video_parameters(schema, {'duration': self.state['source_duration'],
                                           'width': int(self.state['aspect_ratio'].split(':')[0]),
                                           'height': int(self.state['aspect_ratio'].split(':')[1])})
        if any(chosen[key] != self.state[key] for key in ('resolution', 'aspect_ratio', 'duration')):
            raise OpenArtError('The saved draft settings no longer match the live model schema.')
        params = {'prompt': self.state['prompt'], 'videoCount': 1, 'duration': self.state['duration'],
                  'aspectRatio': self.state['aspect_ratio'], 'resolution': '480p', 'generateAudio': True,
                  'autoEnhancePrompt': False, 'visualReferences': self._references()}
        self._quote(model, MODE, params, credit_ceiling)
        self._check_artifacts()
        self._check_context()
        self.status('Exact prompt submitted to OpenArt:\n' + self.state['prompt'])
        if self.state.get('last_frame_hold_seconds'):
            self.status(f"Restoring complete source audio will require a final-frame hold of {self.state['last_frame_hold_seconds']:.3f}s.")
        return self._generate(model, MODE, params, credit_ceiling)

    def _generate(self, model, mode, params, credit_ceiling):
        self.state.update(status='submitting', submit_attempted=True, approved_credit_ceiling=credit_ceiling)
        self._save()  # Never retry this call after any response uncertainty.
        try:
            result = self._call('openart_generate_video', {'model': model, 'mode': mode, 'params': params,
                                                          'projectId': self.state['project_id']})
            history = result.get('historyId')
            if not _identifier(history):
                raise RecoveryRequired('OpenArt submission has no confirmed history ID. Inspect the account history; automatic resubmission is disabled.')
            self.state.update(history_id=history, status='submitted')
            self._save()
        except Exception:
            self.state['status'] = 'submission_unknown'
            self._save()
            raise RecoveryRequired('OpenArt submission outcome is uncertain. Inspect the saved job and account history; automatic resubmission is disabled.') from None
        _atomic_json(self.folder / 'seedance-response.json', {'requestId': self.state['submit_id'], 'historyId': history, 'provider': 'openart'})
        self.status('OpenArt draft submitted: ' + history)
        return self.state['submit_id']

    def resume_preparation(self):
        with self._lock():
            if not self._load():
                raise ValueError('No saved OpenArt preparation is available.')
            if self.state.get('submit_attempted'):
                raise RecoveryRequired('OpenArt submission was already attempted. Use read-only result collection.')
            return self._resume_submission(None)

    def resume_approved(self, credit_ceiling):
        with self._lock():
            if not self._load():
                raise ValueError('No saved OpenArt draft is available for approval.')
            return self._resume_submission(credit_ceiling)

    def collect_result(self, submit_id=None):
        with self._lock():
            if not self._load():
                raise RecoveryRequired('No saved OpenArt operation is available.')
            if submit_id and submit_id not in (self.state['submit_id'], self.state.get('history_id')):
                raise ValueError('The requested operation does not match this job.')
            if not self.state.get('submit_attempted'):
                raise CreditApprovalRequired(self.state.get('minimum_credit_ceiling'))
            history = self.state.get('history_id')
            if not _identifier(history):
                raise RecoveryRequired('The attempted OpenArt submission has no confirmed history ID. Inspect account history or import the downloaded result; do not resubmit.')
            if self.state.get('status') == 'completed' and (self.folder / 'final-preview.mp4').is_file():
                return self.folder / 'final-preview.mp4'
            self._check_context()
            deadline = time.monotonic() + float(setting('OPENART_WAIT_SECONDS', '3600'))
            while True:
                result = self._call('openart_creation_get', {'historyId': history})
                if result.get('historyId') != history:
                    raise OpenArtError('OpenArt returned a different generation history identity.')
                state = result.get('status')
                _atomic_json(self.folder / 'provider-status.json', {'historyId': history, 'status': state})
                if state in ('FAILED', 'CANCELLED'):
                    self.state['status'] = 'failed'
                    self._save()
                    raise OpenArtError('OpenArt generation failed or was cancelled. The saved operation is retained; no replacement was submitted.')
                if state == 'COMPLETED':
                    resources = result.get('resources', [])
                    if result.get('warning') or len(resources) != 1 or resources[0].get('mediaType') != 'video' or not resources[0].get('url') or not _identifier(resources[0].get('id')):
                        raise RecoveryRequired('OpenArt completion has no single complete video result. Inspect the saved generation; do not resubmit.')
                    resource = resources[0]
                    self.state.update(status='result_available', resource_id=resource['id'])
                    self._save()
                    break
                if state not in ('PENDING', 'RUNNING'):
                    raise RecoveryRequired('OpenArt returned an unknown generation state. Inspect the saved operation; do not resubmit.')
                delay = result.get('pollAfterSeconds')
                if not _number(delay) or delay <= 0:
                    raise RecoveryRequired('OpenArt did not return a safe polling interval. Resume this saved operation later.')
                if time.monotonic() + delay > deadline:
                    raise TimeoutError('OpenArt is still generating. Resume the same saved operation later.')
                self.status('OpenArt is still generating; the saved operation remains resumable.')
                time.sleep(delay)
            target = self.folder / 'seedance-result.mp4'
            if not target.is_file() or _digest(target) != self.state.get('download_sha256'):
                temporary = self.folder / 'openart-download.mp4'
                try:
                    self.transport.download(resource['url'], temporary)
                except Exception:
                    self.state['status'] = 'result_available_download_blocked'
                    self._save()
                    raise OpenArtError('The OpenArt result exists, but its download failed. Resume collection or import the provider video; no replacement was submitted.') from None
                if not temporary.is_file() or temporary.stat().st_size <= 0:
                    raise OpenArtError('OpenArt did not download a non-empty video.')
                import av
                with av.open(str(temporary)) as video:
                    if not video.streams.video or next(video.decode(video=0), None) is None:
                        raise OpenArtError('The downloaded OpenArt resource has no decodable video frame.')
                os.replace(temporary, target)
                self.state['download_sha256'] = _digest(target)
                self._save()
            self.status('Restoring the complete configured source audio and discarding generated audio.')
            audio_folder = Path(self.state.get('review_folder') or self.folder)
            final = finish_preview(target, audio_folder)
            if audio_folder != self.folder:
                final_copy = self.folder / 'final-preview.mp4'
                shutil.copy2(final, final_copy)
                final = final_copy
            if self.state.get('is_draft', True):
                shutil.copy2(final, self.folder / 'draft_final.mp4')
            self.state['status'] = 'completed'
            self._save()
            return final

    def submit_hd_upgrade(self, approved=False, credit_ceiling=None):
        if not approved:
            raise ValueError('Explicit HD upgrade approval is required.')
        # A valid provider-returned sourceResourceId action is required. Until
        # this app exposes its quote and artifact-bound approval, fail closed.
        raise OpenArtError('OpenArt offers HD only through a completed draft’s returned upgrade action. This adapter has not enabled that credit-approved lineage action; the draft is preserved and no replacement generation was submitted.')


def readiness():
    return OpenArtBridge().readiness()


def submit(folder, prompt, sirio, tein=None, status=print, credit_ceiling=None):
    return OpenArtBridge(folder, status).submit_draft(prompt, sirio, tein, credit_ceiling)


def resume_preparation(folder, status=print):
    return OpenArtBridge(folder, status).resume_preparation()


def resume_approved(folder, credit_ceiling, status=print):
    return OpenArtBridge(folder, status).resume_approved(credit_ceiling)


def wait_and_finish(folder, request_id, status=print):
    return OpenArtBridge(folder, status).collect_result(request_id)


def submit_hd(folder, approved=False, credit_ceiling=None):
    return OpenArtBridge(folder).submit_hd_upgrade(approved, credit_ceiling)

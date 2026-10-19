"""Local workflow UI; remote calls occur only in explicitly requested jobs."""
from pathlib import Path
from datetime import datetime, timezone
import json
import math
import re
import shutil
import threading
import uuid
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from config import ROOT, setting, DEPTH_MAX_SECONDS, DEPTH_MAX_FRAMES, DEPTH_FPS

RUNS = ROOT / 'runs'
RUNS.mkdir(exist_ok=True)
app = FastAPI(title='GENJUSTSU // 幻術 · 変わり身の術', description='Kawarimi Substitution Studio')
jobs, hd_jobs = {}, {}
mutation_lock = threading.Lock()
collecting = set()


def save_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2))
    temporary.replace(path)


def job_folder(ident):
    if len(ident) != 32 or any(c not in '0123456789abcdef' for c in ident):
        raise HTTPException(404, 'Unknown job')
    folder = RUNS / ident
    if not folder.is_dir():
        raise HTTPException(404, 'Unknown job')
    return folder


def update(folder, **values):
    registry = hd_jobs if folder.name == 'hd' else jobs
    ident = folder.parent.name if folder.name == 'hd' else folder.name
    data = registry.setdefault(ident, {'id': ident})
    data.update(values)
    save_json(folder / 'status.json', data)
    return dict(data)


def failure(exc):
    # Do not echo remote payloads or credential-bearing URLs into the UI.
    if isinstance(exc, (ValueError, RuntimeError)):
        return str(exc)[:600]
    return f'{type(exc).__name__}: operation failed; inspect configuration and resume saved work.'


@app.get('/')
def index():
    return FileResponse(ROOT / 'static/index.html')


@app.get('/capabilities')
def capabilities():
    from seedance_bridge import capabilities as bridge_capabilities, ProviderError
    from raw_masks import configuration_status
    try:
        generation = bridge_capabilities()
    except ProviderError:
        generation = {'provider': 'openart', 'mode': 'element2video', 'video_hd_supported': False,
                      'available': False, 'detail': 'OpenArt connection unavailable; run doctor.py.'}
    generation = {**generation,
                  'model': setting('OPENART_DRAFT_MODEL', 'byte-plus-seedance-2-5-draft'),
                  'resolution': setting('OPENART_DRAFT_RESOLUTION', '480p')}
    depth_limit = {'max_seconds': DEPTH_MAX_SECONDS, 'max_frames': DEPTH_MAX_FRAMES, 'fps': DEPTH_FPS}
    return {'generation': generation, 'segmentation': configuration_status(),
            'audio': {'provider': 'elevenlabs',
                      'configured': bool(setting('ELEVENLABS_API_KEY')),
                      'voice_id': setting('ELEVENLABS_VOICE_ID'),
                      'guidance_mode': setting('AUDIO_DISGUISE_MODE', 'pitch_shift')},
            'final_audio_source': setting('FINAL_AUDIO_SOURCE', 'original'),
            'clip_limits': {
                'depth': depth_limit,
                'depth_mesh': depth_limit,
                'face_mesh': {'max_seconds': 30},
            }}


@app.get('/telemetry')
def telemetry():
    """Read-only account summary; never expose identity or raw provider data."""
    from openart_transport import OpenArtTransport
    summary = {'authenticated': False, 'plan': None, 'credits': None, 'checked_at': None,
               'detail': 'OpenArt account could not be checked. Run the read-only doctor or sign in with the official CLI.'}
    try:
        account = OpenArtTransport().call('openart_account_get', {})
        user = account.get('user') if isinstance(account, dict) else None
        if not isinstance(user, dict) or not isinstance(user.get('uid'), str) or not user['uid']:
            raise ValueError('Account identity unavailable')
        plan = account.get('plan')
        credits = account.get('credits')
        summary.update(
            authenticated=True,
            plan=plan if isinstance(plan, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9 +._-]{0,63}', plan) else None,
            credits=credits if isinstance(credits, (int, float)) and not isinstance(credits, bool)
            and math.isfinite(credits) and credits >= 0 else None,
            checked_at=datetime.now(timezone.utc).isoformat(),
            detail='Account checked through OpenArt MCP. Model readiness and live generation remain unverified.',
        )
    except Exception:
        # Provider errors can contain credentials or signed URLs. Keep only the
        # fixed summary and leave all request/submission paths untouched.
        pass
    return {'openart': summary}


@app.post('/jobs')
def create(video: UploadFile = File(...), prompt: str = Form('person'),
           provider: str = Form('huggingface'), mode: str = Form('depth')):
    if mode not in ('depth', 'face_mesh', 'depth_mesh'):
        raise HTTPException(400, 'Unknown preparation mode')
    if provider != 'huggingface':
        raise HTTPException(400, 'Only Hugging Face cloud preparation is supported.')
    if mode != 'face_mesh':
        from raw_masks import configuration_status
        readiness = configuration_status()
        if not readiness['ready']:
            raise HTTPException(409, readiness['detail'])
    ident = uuid.uuid4().hex
    folder = RUNS / ident
    folder.mkdir()
    src = folder / 'upload.mp4'
    with src.open('wb') as out:
        shutil.copyfileobj(video.file, out)
    if mode in ('depth', 'depth_mesh'):
        from pipeline import probe_source_duration, normalized_frame_count
        try:
            duration = probe_source_duration(src)
            frames = normalized_frame_count(duration)
        except ValueError as exc:
            shutil.rmtree(folder, ignore_errors=True)
            raise HTTPException(400, str(exc)) from None
        if duration > DEPTH_MAX_SECONDS or frames > DEPTH_MAX_FRAMES:
            shutil.rmtree(folder, ignore_errors=True)
            raise HTTPException(
                400,
                f'Depth modes accept at most {DEPTH_MAX_SECONDS:.1f} seconds '
                f'({DEPTH_MAX_FRAMES} frames at {DEPTH_FPS}fps). '
                'Choose a shorter clip or Fast · Face Mesh.',
            )
    update(folder, state='running', status='Starting preparation')

    def work():
        try:
            progress = lambda message: update(folder, status=message)
            if mode == 'face_mesh':
                from face_mesh import run
                run(src, folder, progress)
            elif mode == 'depth_mesh':
                from face_mesh import run_depth
                run_depth(src, folder, prompt, provider, progress)
            else:
                from pipeline import run
                run(src, folder, prompt, provider, progress)
            update(folder, state='done', status='Preparation complete · full-clip review required')
        except Exception as exc:
            update(folder, state='error', status=failure(exc))
    threading.Thread(target=work, daemon=True).start()
    return jobs[ident]


@app.get('/jobs/{ident}')
def get(ident: str):
    folder = job_folder(ident)
    if ident in jobs:
        return jobs[ident]
    saved = folder / 'status.json'
    if saved.exists():
        return json.loads(saved.read_text())
    return {'id': ident, 'state': 'idle', 'status': 'No saved operation'}


def start_collection(folder, submit_id):
    key = str(folder)
    if key in collecting:
        return
    collecting.add(key)
    update(folder, state='running', status='Collecting saved generation ' + submit_id)
    def collect():
        from seedance_bridge import wait_and_finish
        try:
            wait_and_finish(folder, submit_id, lambda message: update(folder, status=message))
            update(folder, state='done', status='Final preview ready · configured source audio restored',
                   final_url='/runs/' + folder.relative_to(RUNS).as_posix() + '/final-preview.mp4')
        except Exception as exc:
            update(folder, state='error', status=failure(exc))
        finally:
            collecting.discard(key)
    threading.Thread(target=collect, daemon=True).start()


def store_references(folder, primary, secondary=None):
    paths = []
    for name, upload in [('sirio', primary), ('tein', secondary)]:
        if upload is None:
            for previous in folder.glob(name + '-reference.*'):
                previous.unlink()
            paths.append(None)
            continue
        suffix = Path(upload.filename or '').suffix.lower()
        allowed = {'.png', '.jpg', '.jpeg', '.webp'} | ({'.mp4', '.mov', '.webm'} if name == 'sirio' else set())
        if suffix not in allowed:
            raise HTTPException(400, 'Use a supported image, or a video for Character 1.')
        path = folder / (name + '-reference' + suffix)
        with path.open('wb') as output:
            shutil.copyfileobj(upload.file, output)
        for previous in folder.glob(name + '-reference.*'):
            if previous != path:
                previous.unlink()
        paths.append(path)
    return paths


@app.post('/jobs/{ident}/prompt')
def suggest_prompt(ident: str, sirio: UploadFile = File(...), tein: UploadFile | None = File(None)):
    with mutation_lock:
        return _suggest_prompt(ident, sirio, tein)


def _suggest_prompt(ident, sirio, tein):
    from openai_helper import generate_seedance_prompt, sample_video_frames
    from mask_review import fingerprint
    from seedance_bridge import state_filename
    folder = job_folder(ident)
    if (folder / state_filename(folder)).exists():
        raise HTTPException(409, 'A generation is already saved; its prompt is frozen.')
    # Video identity is never silently converted to stills.
    if Path(sirio.filename or '').suffix.lower() in {'.mp4', '.mov', '.webm'}:
        raise HTTPException(400, 'Video identity stays a video. Write its appearance-only prompt manually.')
    if not (folder / 'original.mp4').exists():
        raise HTTPException(409, 'Prepare the source first.')
    try:
        current = fingerprint(folder)
    except ValueError:
        raise HTTPException(409, 'Complete preparation, including guidance audio and transcription, before suggesting a prompt.') from None
    references = [path for path in store_references(folder, sirio, tein) if path]
    try:
        frames = sample_video_frames(folder / 'original.mp4', folder / 'scene-samples', count=1)
        transcript = folder / 'dialogue.txt'
        mode_file = folder / 'workflow-mode.json'
        mode = json.loads(mode_file.read_text()).get('mode', 'depth') if mode_file.exists() else 'depth'
        prompt = generate_seedance_prompt(frames[0], references, transcript.read_text() if transcript.exists() else '', mode)
        if fingerprint(folder) != current:
            raise ValueError('Artifacts changed during prompt generation. Request a fresh suggestion.')
        save_json(folder / 'prompt-suggestion.json', {'prompt': prompt, 'mode': mode, 'fingerprint': current})
        return {'prompt': prompt}
    except Exception as exc:
        raise HTTPException(502, failure(exc)) from None


@app.post('/jobs/{ident}/audit')
def audit(ident: str):
    from openai_helper import auto_audit_mask_quality, sample_video_frames
    from mask_review import fingerprint
    folder = job_folder(ident)
    try:
        current = fingerprint(folder)
        frames = sample_video_frames(folder / 'composite-silent.mp4', folder / 'audit-samples')
        result = auto_audit_mask_quality(frames)
        if fingerprint(folder) != current:
            raise ValueError('Artifacts changed during the audit. Run a fresh audit.')
        result['fingerprint'] = current
        save_json(folder / 'mask-audit.json', result)
        return result
    except Exception as exc:
        raise HTTPException(502, failure(exc)) from None


@app.post('/jobs/{ident}/seedance')
def seedance(ident: str, prompt: str = Form(...), sirio: UploadFile = File(...), tein: UploadFile | None = File(None)):
    folder = job_folder(ident)
    from seedance_bridge import submit, CreditApprovalRequired, state_filename
    from mask_review import require_approved
    with mutation_lock:
        try:
            require_approved(folder)
            if (folder / state_filename(folder)).exists():
                raise ValueError('This job has saved provider work. Resume it instead of submitting again.')
            paths = store_references(folder, sirio, tein)
            submit_id = submit(folder, prompt, *paths)
        except CreditApprovalRequired as exc:
            return update(folder, state='awaiting_credit_approval', status=str(exc),
                          minimum_credit_ceiling=exc.minimum_credit_ceiling)
        except Exception as exc:
            update(folder, state='error', status=failure(exc))
            raise HTTPException(409, failure(exc)) from None
        start_collection(folder, submit_id)
    return jobs[ident]


@app.post('/jobs/{ident}/credit-approval')
def approve_credit(ident: str, credit_ceiling: int = Form(...)):
    from seedance_bridge import resume_approved, CreditApprovalRequired
    folder = job_folder(ident)
    with mutation_lock:
        try:
            submit_id = resume_approved(folder, credit_ceiling)
        except CreditApprovalRequired as exc:
            return update(folder, state='awaiting_credit_approval', status=str(exc), minimum_credit_ceiling=exc.minimum_credit_ceiling)
        except Exception as exc:
            raise HTTPException(409, failure(exc)) from None
        start_collection(folder, submit_id)
    return jobs[ident]


@app.post('/jobs/{ident}/resume')
def resume(ident: str):
    from seedance_bridge import state_filename
    folder = job_folder(ident)
    saved = folder / state_filename(folder)
    if not saved.exists():
        raise HTTPException(409, 'No saved generation to collect.')
    data = json.loads(saved.read_text())
    submit_id = data.get('history_id') or data.get('submit_id') or data.get('submitId')
    if not submit_id:
        raise HTTPException(409, 'Saved operation has no generation ID; inspect its provider history before retrying.')
    start_collection(folder, submit_id)
    return jobs[ident]


@app.post('/jobs/{ident}/resume-preparation')
def resume_preparation(ident: str):
    """Explicitly finish saved preparation and quote; never authorize a run."""
    from seedance_bridge import resume_preparation as prepare_saved, CreditApprovalRequired
    folder = job_folder(ident)
    with mutation_lock:
        try:
            prepare_saved(folder)
        except CreditApprovalRequired as exc:
            return update(folder, state='awaiting_credit_approval', status=str(exc), minimum_credit_ceiling=exc.minimum_credit_ceiling)
        except Exception as exc:
            raise HTTPException(409, failure(exc)) from None
    raise HTTPException(409, 'Preparation did not produce a credit quote. Inspect the saved operation.')


@app.post('/jobs/{ident}/finish')
def finish(ident: str, video: UploadFile = File(...)):
    folder = job_folder(ident)
    target = folder / 'seedance-result.mp4'
    with target.open('wb') as output:
        shutil.copyfileobj(video.file, output)
    from audio_workflow import finish_preview
    try:
        finish_preview(target, folder)
        update(folder, state='done', status='Imported result ready · configured source audio restored')
    except Exception as exc:
        raise HTTPException(400, failure(exc)) from None
    return {'url': '/runs/' + ident + '/final-preview.mp4'}


@app.get('/jobs/{ident}/hd')
def get_hd(ident: str):
    folder = job_folder(ident)
    if ident in hd_jobs:
        return hd_jobs[ident]
    saved = folder / 'hd/status.json'
    return json.loads(saved.read_text()) if saved.exists() else {'state': 'idle', 'status': 'HD completion requires a verified provider upgrade contract and explicit approval.'}


@app.post('/jobs/{ident}/hd')
def create_hd(ident: str):
    from seedance_bridge import submit_hd
    folder = job_folder(ident)
    with mutation_lock:
        try:
            submit_id = submit_hd(folder, approved=True)
        except Exception as exc:
            raise HTTPException(409, failure(exc)) from None
        start_collection(folder / 'hd', submit_id)
    return hd_jobs[ident]


@app.get('/jobs/{ident}/mask-review')
def get_mask_review(ident: str):
    from mask_review import state
    folder = job_folder(ident)
    result = state(folder)
    audit_file = folder / 'mask-audit.json'
    if audit_file.exists():
        try:
            audit = json.loads(audit_file.read_text())
        except (ValueError, OSError):
            audit = {}
        if audit.get('fingerprint') == result.get('fingerprint'):
            result = {**result, 'audit': audit}
    return result


@app.post('/jobs/{ident}/mask-review')
def save_mask_review(ident: str, approved: bool = Form(...), fingerprint: str = Form(...), note: str = Form('')):
    from mask_review import review
    try:
        return review(job_folder(ident), approved, note, fingerprint)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@app.on_event('startup')
def resume_saved_generations():
    """Observe saved identities only. Startup can never launch or approve a run."""
    from seedance_bridge import state_filename
    for folder in RUNS.iterdir():
        if not folder.is_dir() or len(folder.name) != 32:
            continue
        saved = folder / state_filename(folder)
        if saved.exists() and not (folder / 'final-preview.mp4').exists():
            try:
                data = json.loads(saved.read_text())
                submit_id = data.get('history_id') or data.get('submit_id') or data.get('submitId')
                stage = data.get('state') or data.get('status')
                if stage == 'awaiting_credit_approval':
                    provider = 'Dreamina' if saved.name == 'dreamina-state.json' else 'OpenArt'
                    update(folder, state=stage, status=provider + ' requires credit approval.', minimum_credit_ceiling=data.get('minimum_credit_ceiling'))
                elif submit_id and stage in {'submitted', 'accepted', 'running', 'pending', 'uncertain', 'submitting', 'result_available'}:
                    start_collection(folder, submit_id)
            except (ValueError, OSError):
                continue
        elif (folder / 'status.json').exists():
            try:
                data = json.loads((folder / 'status.json').read_text())
            except (ValueError, OSError):
                continue
            if data.get('state') == 'running':
                update(folder, state='error', status='Preparation was interrupted. Inspect existing artifacts before explicitly preparing again.')


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'Genjustsu Cloud Workflow', 'generation_readiness': 'Use doctor.py; UI health does not establish provider readiness.'}

app.mount('/runs', StaticFiles(directory=RUNS), name='runs')
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

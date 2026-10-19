"""Mandatory human/agent visual review, bound to the exact prepared assets."""
import hashlib,json,os,tempfile
from pathlib import Path
from datetime import datetime,timezone

FILES=('upload.mp4','original.mp4','depth.mp4','mask.mp4','composite-silent.mp4',
       'seedance-input.mp4','audio-manifest.json','guidance-audio.wav')
def is_mesh(folder):
    p=Path(folder)/'workflow-mode.json'
    return p.exists() and json.loads(p.read_text()).get('mode') in ['face_mesh','depth_mesh']

def fingerprint(folder):
    digest=hashlib.sha256()
    names=list(('upload.mp4','workflow-mode.json','original.mp4','face-landmarks.json','composite-silent.mp4','seedance-input.mp4','audio-manifest.json','guidance-audio.wav') if is_mesh(folder) else FILES)
    if is_mesh(folder) and json.loads((Path(folder)/'workflow-mode.json').read_text()).get('mode')=='depth_mesh':names+=['depth.mp4','mask.mp4','depth-composite-silent.mp4']
    for name in ('original-audio.wav','isolated_vocals.wav','dialogue_transcript.json','dialogue.txt','elevenlabs-sts.wav','music.wav'):
        if (Path(folder)/name).exists():names.append(name)
    for name in names:
        path=Path(folder)/name
        if not path.exists():raise ValueError('Prepare the video and mask before review.')
        digest.update(name.encode())
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()

def state(folder):
    path=Path(folder)/'mask-review.json'
    try:saved=json.loads(path.read_text()) if path.exists() else {}
    except (ValueError,OSError):saved={}
    if not isinstance(saved,dict):saved={}
    try:current=fingerprint(folder)
    except ValueError:return {'approved':False,'status':'unavailable','note':'Prepare the video first.'}
    if saved.get('fingerprint')!=current:return {'approved':False,'status':'pending','note':'Review the entire prepared input: mask coverage for depth mode; facial tracking and overlay alignment for fast mode.','fingerprint':current}
    return saved

def review(folder,approved,note,expected):
    current=fingerprint(folder)
    if current!=expected:raise ValueError('The mask changed. Reload and review the latest preview.')
    if approved and not note.strip():raise ValueError('Record who reviewed the entire clip and their findings.')
    data={'approved':approved,'status':'approved' if approved else 'rejected','note':note,'fingerprint':current,'reviewed_at':datetime.now(timezone.utc).isoformat()}
    fd,temporary=tempfile.mkstemp(prefix='.mask-review-',dir=folder)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump(data,stream,indent=2)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,Path(folder)/'mask-review.json')
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    return data

def require_approved(folder):
    if not state(folder).get('approved'):raise ValueError('Input review required: inspect the whole prepared video and approve its current artifacts before submitting.')

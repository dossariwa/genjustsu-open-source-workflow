"""Dependency/configuration checks and read-only OpenArt discovery; no inference."""
import argparse
import importlib
import shutil
import subprocess
import sys
from pathlib import Path
from config import setting


def configured(name):
    value = setting(name).strip()
    return bool(value) and not any(part in value.lower() for part in ('your_key', 'your_api', 'replace_me', 'placeholder', 'xxxxxxxx'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-keys', action='store_true', help='Exit 2 when generation configuration is blocked.')
    parser.add_argument('--mesh', action='store_true', help='Also verify the isolated face-mesh worker.')
    parser.add_argument('--mode', choices=['depth', 'face_mesh', 'depth_mesh'], default='depth')
    args = parser.parse_args(argv)
    failed = sys.version_info < (3, 12)
    print('Python:', sys.version.split()[0], '(3.12+ required)')
    for name in ['av', 'numpy', 'PIL', 'requests', 'fastapi', 'uvicorn', 'multipart', 'gradio_client', 'scipy', 'cv2', 'openai']:
        try:
            if name == 'cv2':
                # macOS PyAV/OpenCV bundle distinct FFmpeg Objective-C classes.
                # Probe OpenCV in a fresh process rather than loading both here.
                checked = subprocess.run([sys.executable, '-c', 'import cv2'], capture_output=True, timeout=30)
                if checked.returncode:
                    raise ImportError('OpenCV import failed')
            else:
                importlib.import_module(name)
            print(name + ': OK')
        except Exception as exc:
            print(name + ': FAILED (' + type(exc).__name__ + ')')
            failed = True
    rubberband = shutil.which('rubberband')
    print('rubberband:', 'OK' if rubberband else 'MISSING — see docs/SETUP-AGENT.md')
    failed = failed or not rubberband
    if args.mesh or args.mode in ('face_mesh', 'depth_mesh'):
        worker = Path(__file__).resolve().parent / '.venv-face/bin/python'
        try:
            ready = worker.exists() and subprocess.run([str(worker), '-c', 'import mediapipe,av,PIL,numpy'], capture_output=True, timeout=30).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ready = False
        print('Face mesh worker: ' + ('OK' if ready else 'MISSING — run bash setup-face-mesh.sh'))
        failed = failed or not ready
    blocked = []
    for key in ['HF_ACCESS_TOKEN', 'OPENAI_API_KEY', 'ELEVENLABS_API_KEY']:
        valid = configured(key)
        print(key + ': ' + ('configured (access/balance not verified)' if valid else 'MISSING'))
        if not valid:
            blocked.append(key)
    disguise = setting('AUDIO_DISGUISE_MODE', 'pitch_shift')
    final_audio = setting('FINAL_AUDIO_SOURCE', 'original')
    if disguise not in ('pitch_shift', 'elevenlabs_sts'):
        blocked.append('AUDIO_DISGUISE_MODE')
        print('AUDIO_DISGUISE_MODE: invalid; use pitch_shift or elevenlabs_sts')
    if final_audio not in ('original', 'elevenlabs_sts'):
        blocked.append('FINAL_AUDIO_SOURCE')
        print('FINAL_AUDIO_SOURCE: invalid; use original or elevenlabs_sts')
    if 'elevenlabs_sts' in (disguise, final_audio) and not configured('ELEVENLABS_VOICE_ID'):
        blocked.append('ELEVENLABS_VOICE_ID')
        print('ELEVENLABS_VOICE_ID: required for the selected speech-to-speech mode')
    if args.mode != 'face_mesh':
        try:
            from raw_masks import configuration_status
            masks = configuration_status()
            print('Raw SAM masks: ' + masks['detail'])
            if not masks['ready']:
                blocked.append('raw SAM endpoint')
        except Exception as exc:
            print('Raw SAM masks: unavailable (' + type(exc).__name__ + ')')
            blocked.append('raw SAM endpoint')
    try:
        from openart_bridge import readiness
        status = readiness()
        print('OpenArt CLI: ' + str(status.get('cli_version', 'unknown')))
        authenticated = status.get('authenticated') is True
        print('OpenArt CLI authentication: ' + ('signed in (read-only check)' if authenticated else 'NOT SIGNED IN — complete the official OpenArt CLI OAuth login'))
        print('OpenArt connector authentication is separate from this local CLI session.')
        if not authenticated:
            blocked.append('OpenArt CLI authentication')
        else:
            plan = status.get('plan')
            credits = status.get('credits')
            print('OpenArt account: plan ' + str(plan if plan is not None else 'unavailable') + '; credits ' + str(credits if credits is not None else 'unavailable') + ' (read-only)')
            model_verified = status.get('model_verified') is True
            schema_verified = status.get('schema_verified') is True
            print('OpenArt draft model: ' + str(status.get('model', setting('OPENART_DRAFT_MODEL'))) + (' (catalog verified)' if model_verified else ' (UNVERIFIED)'))
            print('OpenArt reference-video contract: ' + ('verified; ' if schema_verified else 'UNVERIFIED; ') + str(status.get('mode', 'unknown')) + '; ' + str(status.get('resolution', setting('OPENART_DRAFT_RESOLUTION', '480p'))))
            if not model_verified:
                blocked.append('OpenArt draft model')
            if not schema_verified:
                blocked.append('OpenArt reference-video schema')
            if isinstance(credits, (int, float)) and not isinstance(credits, bool) and credits <= 0:
                blocked.append('OpenArt credits')
            for reason in status.get('generation_blockers', []):
                if reason not in blocked:
                    blocked.append(reason)
            caps = status.get('capabilities') or {}
            if caps.get('video_hd_supported'):
                print('OpenArt HD: supported contract; separate explicit approval and draft lineage required')
            else:
                print('OpenArt HD: unavailable in the verified local contract; no replacement generation is substituted')
            print('OpenArt video delivery: live generation and download remain untested')
    except Exception as exc:
        # Exception type avoids printing uncontrolled provider output or secrets.
        print('OpenArt CLI discovery: FAILED (' + type(exc).__name__ + '); check installation, OAuth login and network')
        blocked.append('OpenArt CLI discovery')
    print('Dreamina: retained only for collecting existing Dreamina jobs; not required for new jobs')
    print('Legacy Replicate, Enhancor and cloudflared: not required by the default stack')
    if failed:
        print('DEPENDENCIES NOT READY; no inference was run.')
        return 1
    if blocked:
        print('LOCAL UI DEPENDENCIES READY; GENERATION BLOCKED: ' + ', '.join(blocked) + '.')
        print('No paid inference was run. Configured credentials do not prove provider access or balance.')
        return 2 if args.require_keys else 0
    print('CONFIGURATION CHECKS PASSED; live inference and video delivery remain unverified. No credits were spent.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

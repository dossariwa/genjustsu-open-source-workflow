"""Project-local configuration; environment values take precedence."""
import os
from pathlib import Path
ROOT = Path(__file__).resolve().parent
DEFAULTS = {
    'OPENAI_VISION_MODEL': 'gpt-4o',
    'AUDIO_DISGUISE_MODE': 'pitch_shift',
    'FINAL_AUDIO_SOURCE': 'original',
    'OPENART_CLI_BIN': 'openart',
    'OPENART_DRAFT_MODEL': 'byte-plus-seedance-2-5-draft',
    'OPENART_DRAFT_RESOLUTION': '480p',
    # Retained only to collect jobs created before the OpenArt migration.
    'DREAMINA_CLI_BIN': 'dreamina-canvas',
    'DREAMINA_DRAFT_MODEL': 'seedance_2.0_mini',
    'DREAMINA_HD_MODEL': 'seedance_2.5',
    'DREAMINA_DRAFT_RESOLUTION': '720p',
    'DREAMINA_HD_RESOLUTION': '1080p',
    'HF_DEPTH_SPACE': 'depth-anything/Video-Depth-Anything',
    'HF_DEPTH_API_NAME': '/infer_video_depth',
    'HF_SAM_SPACE': 'merve/SAM3-video-segmentation',
}

def load_env():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            key, sep, value = line.partition('=')
            if sep:
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    token = os.getenv('HF_ACCESS_TOKEN') or os.getenv('HF_TOKEN')
    if token:
        os.environ['HF_ACCESS_TOKEN'] = token
        os.environ['HF_TOKEN'] = token

def setting(name, default=''):
    load_env()
    return os.getenv(name, default or DEFAULTS.get(name, ''))

def credential(name):
    value = setting(name).strip()
    if not value:
        raise ValueError(f'Set {name} in this project’s .env file.')
    return value

# Depth / SAM raw-mask clip limit (matches spaces/sam3-raw/raw_endpoint.py and the UI).
DEPTH_MAX_SECONDS = 8
DEPTH_FPS = 24
DEPTH_MAX_FRAMES = DEPTH_MAX_SECONDS * DEPTH_FPS

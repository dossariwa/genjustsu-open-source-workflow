"""Cloud SAM 3 raw masks, with strict frame and archive validation.

The public merve demo returns overlays, not raw masks (source/API checked
2026-10-18). Configure a Space returning a ZIP of mask_000000.png files,
one binary PNG at input dimensions for every input frame. See docs/HF-RAW-MASKS.md.
"""
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
import av
import numpy as np
from gradio_client import handle_file
from PIL import Image
from config import setting
from hf_client import client, endpoint_schema, local_file

DEFAULT_SAM_SPACE = 'merve/SAM3-video-segmentation'
OVERLAY_ONLY_SPACES = {DEFAULT_SAM_SPACE, 'linoyts/SAM3-Video'}


def configuration_status():
    """Local configuration check; does not claim live service readiness."""
    space = setting('HF_SAM_SPACE', DEFAULT_SAM_SPACE)
    api_name = setting('HF_SAM_API_NAME')
    fallback_space = setting('HF_SAM_FALLBACK_SPACE')
    fallback_api_name = setting('HF_SAM_FALLBACK_API_NAME')
    primary_ready = bool(space and api_name and space not in OVERLAY_ONLY_SPACES)
    fallback_ready = bool(fallback_space and fallback_api_name and fallback_space not in OVERLAY_ONLY_SPACES)
    ready = primary_ready or fallback_ready
    if not primary_ready and fallback_ready:
        space, api_name = fallback_space, fallback_api_name
    detail = ('Raw-mask endpoint configured; its live schema and output still require validation.' if ready else
              'The public SAM 3 demos expose overlay playback, not raw masks. Configure HF_SAM_SPACE and '
              'HF_SAM_API_NAME for a raw-mask ZIP endpoint. Depth modes are unavailable until then; face_mesh is independent.')
    return {'ready': ready, 'detail': detail, 'space': space, 'api_name': api_name}


def inspect_endpoint(space=None, api_name=None):
    """Read-only schema validation; no upload or inference."""
    status = configuration_status()
    space = space or status['space']
    api_name = api_name or status['api_name']
    if not space or not api_name or space in OVERLAY_ONLY_SPACES:
        raise ValueError(status['detail'])
    connection = client(space)
    endpoint = endpoint_schema(connection, api_name)
    parameters = endpoint.get('parameters', [])
    videos = [p for p in parameters if p.get('component') in {'Video', 'File'} and
              'video' in p.get('parameter_name', '').lower()]
    prompts = [p for p in parameters if p.get('component') == 'Textbox' and
               any(word in p.get('parameter_name', '').lower() for word in ('prompt', 'query', 'text'))]
    outputs = [(i, p) for i, p in enumerate(endpoint.get('returns', [])) if
               p.get('component') == 'File' and 'mask' in p.get('label', '').lower()]
    if len(videos) != 1 or len(prompts) != 1 or len(outputs) != 1:
        raise ValueError('Unsupported SAM Space API: require one video input, one text prompt, and one File output labelled raw masks (ZIP). Overlay outputs are not raw masks.')
    required = {videos[0]['parameter_name'], prompts[0]['parameter_name']}
    if any(not p.get('parameter_has_default', False) and p.get('parameter_name') not in required for p in parameters):
        raise ValueError('Unsupported SAM Space API: extra required inputs must have server-side defaults.')
    return connection, videos[0], prompts[0], outputs[0][0]


def _video_shape(video):
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        dimensions = (stream.width, stream.height)
        count = sum(1 for _ in container.decode(video=0))
    if not count:
        raise ValueError('Cannot segment an empty video.')
    return count, dimensions


def validate_masks(folder, video):
    """Check every PNG; measurements are diagnostics, not visual approval."""
    count, dimensions = _video_shape(video)
    try:
        files = sorted(Path(folder).glob('mask_*.png'), key=lambda p: int(p.stem.split('_')[-1]))
    except ValueError:
        raise ValueError('Frame alignment failed: raw mask filenames must use numeric frame indices.') from None
    if len(files) != count or [int(p.stem.split('_')[-1]) for p in files] != list(range(count)):
        raise ValueError(f'Frame alignment failed: expected {count} zero-based raw masks, received {len(files)}. No shortened or shifted output is accepted.')
    reports = []
    for i, path in enumerate(files):
        with Image.open(path) as image:
            if image.size != dimensions:
                raise ValueError(f'Frame alignment failed: raw mask {i} dimensions {image.size} differ from video {dimensions}.')
            array = np.asarray(image)
        if array.ndim == 3:
            if array.shape[2] != 3 or not np.all(array == array[:, :, :1]):
                raise ValueError(f'Raw mask {i} is colored or has alpha; overlays are not binary masks.')
            array = array[:, :, 0]
        if array.ndim != 2 or not np.isin(array, [0, 255]).all():
            raise ValueError(f'Raw mask {i} must contain only binary 0/255 pixels.')
        selected = array > 0
        border = np.concatenate((selected[0], selected[-1], selected[:, 0], selected[:, -1]))
        reports.append({'frame': i, 'coverage': float(selected.mean()), 'border_coverage': float(border.mean())})
    failures = [r['frame'] for r in reports if r['coverage'] == 0 or r['coverage'] >= .98]
    return {'frames': count, 'width': dimensions[0], 'height': dimensions[1],
            'suspicious_frames': failures, 'measurements': reports, 'visual_approval': False,
            'note': 'Empty/nearly full masks trigger RGB retry. Measurements do not establish subject coverage, background spill, or full visual approval.'}


def _extract_archive(archive, output, count, dimensions):
    """Never extract archive paths; bound decompression and reject duplicate indices."""
    max_size = max(count * dimensions[0] * dimensions[1] * 4, 1024 * 1024)
    with zipfile.ZipFile(archive) as zipped:
        members = [m for m in zipped.infolist() if not m.is_dir()]
        if sum(m.file_size for m in members) > max_size:
            raise ValueError('Raw mask archive exceeds the expected frame dimensions.')
        masks = []
        for member in members:
            match = re.fullmatch(r'mask_(\d+)\.png', Path(member.filename).name)
            if match:
                masks.append((int(match.group(1)), member))
        if len(masks) != count or sorted(index for index, _ in masks) != list(range(count)):
            raise ValueError('Frame alignment failed: raw-mask ZIP must have exactly one zero-based mask PNG per input frame.')
        output.mkdir(parents=True, exist_ok=True)
        for index, member in masks:
            (output / f'mask_{index:06d}.png').write_bytes(zipped.read(member))


def segment_raw(video, folder, prompt='person'):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    primary = configuration_status()
    if not primary['ready']:
        raise ValueError(primary['detail'])
    candidates = [(primary['space'], primary['api_name'])]
    fallback = (setting('HF_SAM_FALLBACK_SPACE'), setting('HF_SAM_FALLBACK_API_NAME'))
    if all(fallback) and fallback not in candidates:
        candidates.append(fallback)
    count, dimensions = _video_shape(video)
    failures = []
    for space, api_name in candidates:
        try:
            connection, video_parameter, text_parameter, output_index = inspect_endpoint(space, api_name)
            video_value = handle_file(str(video))
            if video_parameter['component'] == 'Video':
                video_value = {'video': video_value}
            try:
                result = connection.predict(**{video_parameter['parameter_name']: video_value,
                                              text_parameter['parameter_name']: prompt}, api_name=api_name)
            except Exception:
                raise RuntimeError('Hugging Face SAM inference failed; no valid raw-mask result was returned.') from None
            if isinstance(result, (tuple, list)):
                result = result[output_index]
            elif output_index != 0:
                raise ValueError('SAM output does not match its advertised schema.')
            archive = local_file(result)
            if not zipfile.is_zipfile(archive):
                raise ValueError('SAM must return a ZIP of raw binary PNG masks; overlay videos are unsupported.')
            with tempfile.TemporaryDirectory(dir=folder, prefix='sam-download-') as temporary:
                masks = Path(temporary) / 'masks'
                _extract_archive(archive, masks, count, dimensions)
                report = validate_masks(masks, video)
                out = folder / 'raw-masks'
                if out.exists():
                    shutil.rmtree(out)
                shutil.move(str(masks), out)
            shutil.copyfile(archive, folder / 'sam-masks.zip')
            (folder / 'mask-validation.json').write_text(json.dumps(report, indent=2))
            (folder / 'sam-raw-request.json').write_text(json.dumps({
                'provider': 'huggingface', 'space': space, 'api_name': api_name,
                'prompt': prompt, 'source': Path(video).name, 'format': 'raw_binary_png_zip',
                'fallback_used': bool(failures), 'failed_attempts': failures}, indent=2))
            return out
        except Exception as exc:
            # Provider exceptions can contain credential-bearing request URLs.
            failures.append({'space': space, 'api_name': api_name, 'error_type': type(exc).__name__})
            if len(candidates) == 1:
                if isinstance(exc, ValueError):
                    raise
                raise RuntimeError('Hugging Face raw-mask request failed; check the Space availability and endpoint contract.') from None
    raise RuntimeError('Hugging Face primary and fallback raw-mask endpoints failed. No valid aligned masks were produced.')


def clean_border_fragments(folder):
    """Remove tiny narrow edge fragments; retain raw masks for mandatory review."""
    from scipy.ndimage import label
    folder = Path(folder)
    output = folder.parent / 'clean-masks'
    output.mkdir(exist_ok=True)
    for stale in output.glob('mask_*.png'):
        stale.unlink()
    report = []
    for path in sorted(folder.glob('mask_*.png')):
        with Image.open(path) as image:
            array = np.asarray(image.convert('L')) > 127
        labels, _ = label(array)
        height, width = array.shape
        removed = 0
        for ident in (set(labels[:, 0]) | set(labels[:, -1])) - {0}:
            _, x = np.where(labels == ident)
            if len(x) < height * width * .03 and x.max() - x.min() + 1 <= max(6, int(width * .05)):
                array[labels == ident] = False
                removed += len(x)
        Image.fromarray(array.astype(np.uint8) * 255).save(output / path.name)
        report.append({'frame': path.stem, 'removed_border_pixels': removed,
                       'mask_pixels': int(array.sum()),
                       'left_right_edge_pixels': int(array[:, 0].sum() + array[:, -1].sum())})
    (folder.parent / 'mask-cleanup-report.json').write_text(json.dumps(report, indent=2))
    return output

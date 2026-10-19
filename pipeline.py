"""Cloud depth/SAM preparation with local, lossless mask compositing."""
from fractions import Fraction
from pathlib import Path
import json
import math
import shutil
import av
import numpy as np
from PIL import Image
from gradio_client import handle_file
from config import setting
from hf_client import client, endpoint_schema, local_file

DEPTH = 'depth-anything/Video-Depth-Anything'
SAM = 'merve/SAM3-video-segmentation'


def frames(path):
    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            yield frame.to_ndarray(format='rgb24')


def writer(path, w, h, lossless=False):
    container = av.open(str(path), 'w')
    stream = container.add_stream('libx264rgb' if lossless else 'libx264', rate=24)
    stream.width, stream.height = w, h
    stream.pix_fmt = 'rgb24' if lossless else 'yuv420p'
    stream.options = {'crf': '0' if lossless else '18', 'preset': 'fast'}
    return container, stream


def put(container, stream, array, index):
    frame = av.VideoFrame.from_ndarray(array, format='rgb24')
    frame.pts, frame.time_base = index, Fraction(1, 24)
    for packet in stream.encode(frame):
        container.mux(packet)


def finish(container, stream):
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def normalize(src, dst):
    """Create a separate 24 fps, <=960px video without changing the source."""
    with av.open(str(src)) as inp:
        if not inp.streams.video:
            raise ValueError('The source has no video stream.')
        video = inp.streams.video[0]
        rate = float(video.average_rate or 24)
        if video.duration is not None:
            duration = float(video.duration * video.time_base)
        elif inp.duration is not None:
            duration = float(inp.duration / av.time_base)
        else:
            raise ValueError('Video duration is unavailable; remux the source before preparation.')
        if not math.isfinite(duration) or duration <= 0 or duration > 30:
            raise ValueError('Use a nonempty clip of 30 seconds or less for this hosted workflow.')
        iterator = iter(inp.decode(video=0))
        current = next(iterator, None)
        if current is None:
            raise ValueError('The source contains no decodable video frames.')
        start = float(current.time or 0)
        following = next(iterator, None)
        next_index = 1
        scale = min(1, 960 / max(current.width, current.height))
        width = max(2, int(current.width * scale) // 2 * 2)
        height = max(2, int(current.height * scale) // 2 * 2)
        output, stream = writer(dst, width, height)
        count = max(1, math.ceil(duration * 24 - 1e-6))
        try:
            for index in range(count):
                time = index / 24 + start
                while following is not None and float(following.time if following.time is not None else start + next_index / rate) <= time:
                    current = following
                    following = next(iterator, None)
                    next_index += 1
                array = np.asarray(current.to_image().resize((width, height), Image.Resampling.LANCZOS))
                put(output, stream, array, index)
            finish(output, stream)
        except Exception:
            output.close()
            raise
    return {'frames': count, 'fps': 24, 'width': width, 'height': height,
            'duration': count / 24, 'source_video_duration': duration,
            'normalization_last_frame_hold_seconds': max(0, count / 24 - duration)}


def video_layout(path):
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError('Frame alignment failed: no video stream.')
        stream = container.streams.video[0]
        stamps = [float(frame.time) if frame.time is not None else None for frame in container.decode(video=0)]
        if not stamps or any(t is None for t in stamps):
            raise ValueError('Frame alignment failed: missing frames or timestamps.')
        times = [time - stamps[0] for time in stamps]
        return {'width': stream.width, 'height': stream.height, 'frames': len(times), 'times': times}


def validate_depth_alignment(original, depth):
    source, result = video_layout(original), video_layout(depth)
    if any(abs(time - index / 24) > 1 / 240 for index, time in enumerate(source['times'])):
        raise ValueError('Frame alignment failed: source must be normalized to constant 24 fps before depth generation.')
    for key in ('width', 'height', 'frames'):
        if source[key] != result[key]:
            raise ValueError(f'Frame alignment failed: original/depth {key} differ ({source[key]}/{result[key]}).')
    if any(abs(a - b) > 1 / 240 for a, b in zip(source['times'], result['times'])):
        raise ValueError('Frame alignment failed: depth timestamps differ from the normalized source.')
    return source


def file_path(value):
    """Compatibility helper for downloaded Gradio output files."""
    return str(local_file(value))


def depth_hf(src, dst):
    space = setting('HF_DEPTH_SPACE', DEPTH)
    api_name = setting('HF_DEPTH_API_NAME', '/infer_video_depth')
    connection = client(space)
    schema = endpoint_schema(connection, api_name)
    parameters = {p['parameter_name'] for p in schema.get('parameters', [])}
    if not {'input_video', 'max_len', 'target_fps', 'max_res', 'grayscale'} <= parameters:
        raise ValueError('Unsupported depth Space API; expected Video Depth Anything infer_video_depth contract.')
    outputs = schema.get('returns', [])
    if len(outputs) != 2 or outputs[1].get('component') != 'Video' or 'depth' not in outputs[1].get('label', '').lower():
        raise ValueError('Unsupported depth Space output; expected processed video and colored depth video.')
    try:
        result = connection.predict(input_video={'video': handle_file(str(src))}, max_len=-1,
                                    target_fps=24, max_res=960, grayscale=False, api_name=api_name)
    except Exception:
        raise RuntimeError('Hugging Face colored-depth inference failed; check Space availability and account access.') from None
    if not isinstance(result, (tuple, list)) or len(result) != 2:
        raise ValueError('Depth Space returned an unexpected result.')
    downloaded = local_file(result[1])
    validate_depth_alignment(src, downloaded)
    # Preserve the provider's colored depth bit-for-bit; never grayscale/recolor.
    shutil.copyfile(downloaded, dst)


def composite(original, depth, seg, directory, audio_source=None):
    """Copy decoded colored depth pixels through raw masks, without rescaling."""
    from raw_masks import validate_masks
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if not Path(seg).is_dir():
        raise ValueError('Raw PNG masks are required; a colored SAM overlay video is not a raw mask.')
    layout = validate_depth_alignment(original, depth)
    report = validate_masks(seg, original)
    if not any(frame['coverage'] > 0 for frame in report['measurements']):
        raise ValueError('SAM 3 found no subject. Retry segmentation on original RGB detail and review the masks.')
    mask_files = sorted(Path(seg).glob('mask_*.png'), key=lambda p: int(p.stem.split('_')[-1]))
    outputs = {}
    try:
        for index, (rgb, colored_depth, path) in enumerate(zip(frames(original), frames(depth), mask_files)):
            with Image.open(path) as image:
                mask = np.asarray(image.convert('L'))
            result = np.where((mask > 127)[:, :, None], colored_depth, rgb).astype(np.uint8)
            for name, array in [('mask', np.repeat(mask[:, :, None], 3, axis=2)), ('composite-silent', result)]:
                if name not in outputs:
                    outputs[name] = writer(directory / (name + '.mp4'), layout['width'], layout['height'], lossless=True)
                put(*outputs[name], array, index)
        for container, stream in outputs.values():
            finish(container, stream)
    except Exception:
        for container, _ in outputs.values():
            container.close()
        raise
    final = directory / 'composite.mp4'
    with av.open(str(directory / 'composite-silent.mp4')) as video, av.open(str(audio_source or original)) as audio, av.open(str(final), 'w') as output:
        vs = output.add_stream_from_template(video.streams.video[0])
        audio_stream = output.add_stream_from_template(audio.streams.audio[0]) if audio.streams.audio else None
        for packet in video.demux(video=0):
            if packet.dts is not None:
                packet.stream = vs
                output.mux(packet)
        if audio_stream:
            for packet in audio.demux(audio=0):
                if packet.dts is not None:
                    packet.stream = audio_stream
                    output.mux(packet)
    return layout['frames']


def segment_with_rgb_fallback(directory, prompt, status=print):
    from raw_masks import segment_raw, clean_border_fragments, validate_masks
    directory = Path(directory)
    source = directory / 'original.mp4'
    depth = directory / 'depth.mp4'
    status('SAM 3 · segmenting colored depth')
    raw = segment_raw(depth, directory, prompt)
    masks = clean_border_fragments(raw)
    report = validate_masks(masks, source)
    fallback = False
    if report['suspicious_frames']:
        fallback = True
        (directory / 'depth-mask-validation.json').write_text(json.dumps(report, indent=2))
        status('SAM 3 · depth coverage needs repair; retrying original RGB detail')
        repair = directory / 'rgb-mask-fallback'
        raw = segment_raw(source, repair, prompt)
        masks = clean_border_fragments(raw)
        report = validate_masks(masks, source)
    (directory / 'mask-validation.json').write_text(json.dumps(report, indent=2))
    (directory / 'mask-source.json').write_text(json.dumps({
        'segmentation_input': 'original_rgb' if fallback else 'colored_depth',
        'rgb_fallback_used': fallback, 'reason': 'empty_or_nearly_full_depth_masks' if fallback else None,
        'raw_masks': str(raw.relative_to(directory)), 'composite_masks': str(masks.relative_to(directory)),
        'depth_colors_preserved': True, 'visual_approval': False}, indent=2))
    if report['suspicious_frames']:
        raise ValueError('SAM masks remain empty or nearly full after RGB retry. Inspect and repair them before generation; no visual approval has been recorded.')
    return masks, fallback


def run(src, directory, prompt='person', provider='huggingface', status=print):
    if provider != 'huggingface':
        raise ValueError('Only the huggingface cloud depth provider is supported. Legacy providers have been removed.')
    from raw_masks import configuration_status, inspect_endpoint
    configuration = configuration_status()
    if not configuration['ready']:
        raise ValueError(configuration['detail'])
    # Fail unsupported contracts before any paid audio/depth inference.
    inspect_endpoint()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    from audio_workflow import separate, prepare_seedance_video
    status('Preparing video · 24 fps, maximum 960 px')
    meta = normalize(src, directory / 'original.mp4')
    status('Video Depth Anything · generating colored depth in Hugging Face')
    depth_hf(directory / 'original.mp4', directory / 'depth-raw.mp4')
    shutil.copyfile(directory / 'depth-raw.mp4', directory / 'depth.mp4')
    masks, fallback = segment_with_rgb_fallback(directory, prompt, status)
    status('Compositing · colored depth subject over original background')
    composite(directory / 'original.mp4', directory / 'depth.mp4', masks, directory, src)
    separate(src, directory, status)
    status('Embedding isolated guidance vocals')
    prepare_seedance_video(directory)
    meta.update(prompt=prompt, depth_provider=provider, depth_space=setting('HF_DEPTH_SPACE', DEPTH),
                sam_space=configuration['space'], sam_api_name=configuration['api_name'],
                mask_method='SAM 3 raw PNG masks', rgb_mask_fallback=fallback,
                depth_colors_preserved=True, visual_review_required=True)
    (directory / 'manifest.json').write_text(json.dumps(meta, indent=2))
    status('Prepared · complete visual mask review is required before generation')

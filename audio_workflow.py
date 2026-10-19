"""Cloud speech preparation and explicit final-audio restoration.

Guidance is a stereo working copy. The default final export never uses that
copy: it remuxes every compressed audio stream from the preserved upload.
"""
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote
import hashlib
import heapq
import json
import math
import shutil
import subprocess

import av
import numpy as np
import requests

from config import credential, setting

RATE = 44100
ELEVENLABS_URL = 'https://api.elevenlabs.io/v1'
RESIDUAL_NOTICE = ('Estimated residual (original minus isolated speech), not an '
                   'independent instrumental stem; speech bleed and artifacts are possible.')


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {} if default is None else default


def _save_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    temporary.replace(path)


def _manifest(folder, **updates):
    path = Path(folder) / 'audio-manifest.json'
    data = _json(path)
    data.update(updates)
    _save_json(path, data)
    return data


def _fit(samples, count):
    if samples.ndim != 2 or not samples.shape[1] or not np.isfinite(samples).all():
        raise ValueError('Audio is empty or contains invalid samples.')
    return np.pad(samples, ((0, 0), (0, max(0, count - samples.shape[1]))))[:, :count]


def read_audio(path):
    """Decode the first track into a 44.1 kHz stereo processing copy."""
    parts = []
    resampler = av.AudioResampler(format='fltp', layout='stereo', rate=RATE)
    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise ValueError('Source has no audio track.')
        audio = container.streams.audio[0]
        expected = round(float(audio.duration * audio.time_base) * RATE) if audio.duration else None
        for frame in container.decode(audio=0):
            parts.extend(item.to_ndarray() for item in resampler.resample(frame))
        parts.extend(item.to_ndarray() for item in resampler.resample(None))
    if not parts:
        raise ValueError('Audio contains no decodable samples.')
    samples = np.concatenate(parts, axis=1)
    # Container duration excludes codec padding (e.g. the last AAC frame).
    return samples[:, :expected] if expected else samples


def write_audio(path, samples):
    samples = np.asarray(samples, dtype=np.float32)
    with av.open(str(path), 'w', format='wav') as output:
        stream = output.add_stream('pcm_s16le', rate=RATE)
        stream.layout = 'stereo'
        for i in range(0, samples.shape[1], 4096):
            frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(samples[:, i:i+4096]),
                                               format='fltp', layout='stereo')
            frame.sample_rate = RATE
            frame.pts = i
            frame.time_base = Fraction(1, RATE)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)


def _post_audio(endpoint, path, *, data=None, field='audio', binary=True):
    """Use direct multipart uploads; never persist authorization headers."""
    with Path(path).open('rb') as handle:
        response = requests.post(
            ELEVENLABS_URL + endpoint,
            headers={'xi-api-key': credential('ELEVENLABS_API_KEY')},
            files={field: (Path(path).name, handle, 'audio/wav')},
            data=data or {}, timeout=(30, 600),
        )
    response.raise_for_status()
    if binary:
        if not response.content:
            raise ValueError('ElevenLabs returned empty audio.')
        return response.content
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError('ElevenLabs returned an invalid transcript.')
    return result


def isolate_vocals(folder, status=print):
    """Isolate the prepared original-audio.wav with ElevenLabs once per input."""
    folder = Path(folder)
    original_path = folder / 'original-audio.wav'
    fingerprint = _sha256(original_path)
    isolated = folder / 'isolated_vocals.wav'
    previous = _json(folder / 'audio-manifest.json').get('isolation', {})
    if (previous.get('input_sha256') == fingerprint and isolated.is_file()
            and previous.get('output_sha256') == _sha256(isolated)
            and (folder / 'music.wav').is_file()):
        return isolated
    status('Audio · isolating speech with ElevenLabs')
    raw = folder / 'elevenlabs-isolation.audio'
    raw_state = folder / 'elevenlabs-isolation.json'
    # Retain a successful paid response if a later local operation is interrupted.
    if not (raw.is_file() and _json(raw_state).get('input_sha256') == fingerprint):
        raw.write_bytes(_post_audio('/audio-isolation', original_path))
        _save_json(raw_state, {'input_sha256': fingerprint, 'provider': 'elevenlabs'})
    original = read_audio(original_path)
    vocals = read_audio(raw)
    drift = (vocals.shape[1] - original.shape[1]) / RATE
    if abs(drift) > .25:
        raise ValueError('Isolated speech duration differs by more than 250ms; review the provider result before proceeding.')
    vocals = _fit(vocals, original.shape[1])
    write_audio(isolated, vocals)
    # Keep the old working filename for existing jobs and integrations.
    shutil.copyfile(isolated, folder / 'vocals.wav')
    write_audio(folder / 'music.wav', np.clip(original - vocals, -1, 1))
    _manifest(folder, isolation={'provider': 'elevenlabs', 'endpoint': '/v1/audio-isolation',
                                'input_sha256': fingerprint, 'output_sha256': _sha256(isolated),
                                'duration_drift_seconds': drift},
              separation='ElevenLabs Voice Isolator', residual_notice=RESIDUAL_NOTICE,
              original_audio_processing_copy='original-audio.wav',
              discard_seedance_audio=True)
    return isolated


def transcribe_dialogue_scribe(isolated_vocals_path, folder=None, status=print):
    """Persist Scribe's full response and plain dialogue, with an input-bound cache."""
    path = Path(isolated_vocals_path)
    if path.is_dir():
        folder, path = path, path / 'isolated_vocals.wav'
    folder = Path(folder) if folder is not None else path.parent
    model = setting('ELEVENLABS_SCRIBE_MODEL', 'scribe_v1')
    signature = {'input_sha256': _sha256(path), 'model_id': model}
    previous = _json(folder / 'audio-manifest.json').get('transcription', {})
    output = folder / 'dialogue_transcript.json'
    text_path = folder / 'dialogue.txt'
    if (all(previous.get(k) == v for k, v in signature.items()) and output.is_file()
            and text_path.is_file() and previous.get('output_sha256') == _sha256(output)
            and previous.get('text_sha256') == _sha256(text_path)):
        return text_path.read_text()
    status('Audio · transcribing dialogue with ElevenLabs Scribe')
    result = _post_audio('/speech-to-text', path, field='file',
                         data={'model_id': model}, binary=False)
    if not isinstance(result.get('text'), str):
        raise ValueError('Scribe did not return a synchronous text transcript.')
    _save_json(output, result)
    text_path.write_text(result['text'])
    _manifest(folder, transcription={**signature, 'output_sha256': _sha256(output),
                                     'text_sha256': _sha256(text_path)})
    return result['text']


def _duration(container):
    endpoints = [float(container.duration / av.time_base)] if container.duration else []
    for stream in container.streams:
        if stream.duration is not None:
            endpoints.append(float(((stream.start_time or 0) + stream.duration) * stream.time_base))
    if not endpoints:
        raise ValueError('Media duration is unavailable; cannot preserve complete audio.')
    return max(endpoints)


def separate(src, folder, status=print):
    """Preserve existing preparation API while using cloud isolation and Scribe."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fingerprint = _sha256(src)
    previous = _json(folder / 'audio-manifest.json')
    original = folder / 'original-audio.wav'
    if not (original.is_file() and previous.get('original_source_sha256') == fingerprint
            and previous.get('processing_audio_sha256') == _sha256(original)):
        status('Audio · extracting a processing copy; source audio remains untouched')
        samples = read_audio(src)
        with av.open(str(src)) as source:
            stream = source.streams.audio[0]
            offset = max(0, round(float((stream.start_time or 0) * stream.time_base) * RATE))
            count = round(_duration(source) * RATE)
        samples = np.pad(samples, ((0, 0), (offset, 0)))
        write_audio(original, _fit(samples, count))
        _manifest(folder, original_source_sha256=fingerprint,
                  processing_audio_sha256=_sha256(original),
                  processing_track='first audio stream, downmixed to stereo; final original export copies all streams')
    isolated = isolate_vocals(folder, status)
    transcribe_dialogue_scribe(isolated, folder, status)
    return isolated


def _rubberband(source, target, *, pitch=0, ratio=1):
    binary = shutil.which('rubberband')
    if not binary:
        raise RuntimeError('Rubber Band is required for pitch shifting and speech timing correction.')
    subprocess.run([binary, '--fine', '--pitch', str(pitch), '--time', str(ratio),
                    str(source), str(target)], check=True, capture_output=True, timeout=600)


def _prepare_sts(folder, isolated):
    voice = setting('ELEVENLABS_VOICE_ID')
    if not voice:
        raise ValueError('ELEVENLABS_VOICE_ID is required for elevenlabs_sts audio.')
    signature = {'input_sha256': _sha256(isolated), 'voice_id': voice,
                 'model_id': 'eleven_multilingual_sts_v2'}
    target = folder / 'elevenlabs-sts.wav'
    previous = _json(folder / 'audio-manifest.json').get('speech_to_speech', {})
    if (all(previous.get(k) == v for k, v in signature.items()) and target.is_file()
            and previous.get('output_sha256') == _sha256(target)):
        return target
    raw = folder / 'elevenlabs-sts.audio'
    raw_state = folder / 'elevenlabs-sts-response.json'
    if not (raw.is_file() and _json(raw_state) == signature):
        raw.write_bytes(_post_audio('/speech-to-speech/' + quote(voice, safe=''), isolated,
                                   data={'model_id': signature['model_id']}))
        _save_json(raw_state, signature)
    samples = read_audio(raw)
    count = read_audio(isolated).shape[1]
    returned_count = samples.shape[1]
    drift = (returned_count - count) / RATE
    corrected = abs(drift) > .040
    ratio = count / returned_count
    if corrected:
        unaligned = folder / 'elevenlabs-sts-unaligned.wav'
        aligned = folder / 'elevenlabs-sts-aligned.wav'
        write_audio(unaligned, samples)
        _rubberband(unaligned, aligned, ratio=ratio)
        samples = read_audio(aligned)
        if abs(samples.shape[1] - count) / RATE > .040:
            raise ValueError('Speech timing correction still differs by more than 40ms; refusing to trim dialogue.')
    write_audio(target, _fit(samples, count))
    _manifest(folder, speech_to_speech={**signature, 'output_sha256': _sha256(target),
              'returned_samples': returned_count, 'target_samples': count,
              'duration_drift_seconds': drift, 'rubberband_time_corrected': corrected,
              'time_ratio': ratio if corrected else 1,
              'notice': 'Converted speech is not original audio; duration matching does not prove phoneme alignment.'})
    return target


def prepare_guidance_audio(folder, semitones=3):
    """Produce timing-fitted guidance; any final STS conversion is prepared now."""
    folder = Path(folder)
    mode = setting('AUDIO_DISGUISE_MODE', 'pitch_shift')
    final_mode = setting('FINAL_AUDIO_SOURCE', 'original')
    if mode not in {'pitch_shift', 'elevenlabs_sts'}:
        raise ValueError('AUDIO_DISGUISE_MODE must be pitch_shift or elevenlabs_sts.')
    if final_mode not in {'original', 'elevenlabs_sts'}:
        raise ValueError('FINAL_AUDIO_SOURCE must be original or elevenlabs_sts.')
    isolated = folder / 'isolated_vocals.wav'
    if not isolated.is_file():
        isolated = folder / 'vocals.wav'  # Existing prepared jobs remain usable.
    converted = _prepare_sts(folder, isolated) if 'elevenlabs_sts' in {mode, final_mode} else None
    signature = {'input_sha256': _sha256(isolated), 'mode': mode,
                 'pitch_semitones': semitones if mode == 'pitch_shift' else None,
                 'converted_sha256': _sha256(converted) if mode == 'elevenlabs_sts' else None}
    target = folder / 'guidance-audio.wav'
    previous = _json(folder / 'audio-manifest.json').get('guidance', {})
    if not (all(previous.get(k) == v for k, v in signature.items()) and target.is_file()
            and previous.get('output_sha256') == _sha256(target)):
        if mode == 'pitch_shift':
            pitched = folder / f'vocals-plus{semitones}.wav'
            _rubberband(isolated, pitched, pitch=semitones)
            count = read_audio(isolated).shape[1]
            samples = read_audio(pitched)
            if abs(samples.shape[1] - count) / RATE > .040:
                raise ValueError('Pitch shifting changed speech duration by more than 40ms.')
            write_audio(target, _fit(samples, count))
        else:
            shutil.copyfile(converted, target)
        _manifest(folder, guidance={**signature, 'output_sha256': _sha256(target)})
    if final_mode == 'elevenlabs_sts':
        if not (folder / 'music.wav').is_file():
            raise ValueError('The estimated residual music.wav is required for the requested final STS mix.')
        final_description = 'ElevenLabs converted speech plus estimated residual background; re-encoded, not original audio'
        final_artifacts = {name: _sha256(folder / name) for name in ('elevenlabs-sts.wav', 'music.wav')}
    else:
        final_description = 'all original compressed audio streams from upload.mp4, packet copied without re-encoding'
        final_artifacts = {}
    _manifest(folder, final_audio_source=final_mode, final_audio=final_description,
              final_audio_artifacts=final_artifacts,
              embedded_vocals=target.name, seedance_audio=None)
    return target


def _encode_audio(output, stream, samples):
    for i in range(0, samples.shape[1], 4096):
        frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(samples[:, i:i+4096].astype(np.float32)),
                                           format='fltp', layout='stereo')
        frame.sample_rate = RATE
        frame.pts = i
        frame.time_base = Fraction(1, RATE)
        yield from stream.encode(frame)
    yield from stream.encode()


def _remapped_packets(container, mapping, streams):
    for packet in container.demux(*streams):
        if packet.dts is not None:
            packet.stream = mapping[packet.stream.index]
            yield packet


def _mux_interleaved(output, *iterators):
    for packet in heapq.merge(*iterators, key=lambda p: p.dts * p.time_base):
        output.mux(packet)


def prepare_seedance_video(folder, semitones=3):
    """Embed speech guidance into the current composite; attach no separate audio."""
    folder = Path(folder)
    guidance = prepare_guidance_audio(folder, semitones)
    composite = folder / 'composite-silent.mp4'
    target = folder / 'seedance-input.mp4'
    signature = {'video_sha256': _sha256(composite), 'audio_sha256': _sha256(guidance)}
    previous = _json(folder / 'audio-manifest.json').get('embedded_input', {})
    if (all(previous.get(k) == v for k, v in signature.items()) and target.is_file()
            and previous.get('output_sha256') == _sha256(target)):
        return target
    temporary = folder / 'seedance-input.tmp.mp4'
    samples = read_audio(guidance)
    with av.open(str(composite)) as video, av.open(str(temporary), 'w') as output:
        original = video.streams.video[0]
        stream = output.add_stream_from_template(original)
        audio = output.add_stream('aac', rate=RATE)
        audio.layout = 'stereo'
        audio.bit_rate = 192000
        _mux_interleaved(output, _remapped_packets(video, {original.index: stream}, [original]),
                         _encode_audio(output, audio, samples))
    temporary.replace(target)
    _manifest(folder, seedance_video=target.name, seedance_audio=None,
              embedded_input={**signature, 'output_sha256': _sha256(target)})
    return target


def _align_generated_video(generated, folder, duration):
    with av.open(str(generated)) as probe:
        video = probe.streams.video[0]
        vd = float(video.duration * video.time_base) if video.duration else _duration(probe)
        rate = video.average_rate or Fraction(24, 1)
    gap = duration - vd
    if abs(gap) > .5 + 1e-6:
        raise ValueError('Generated duration differs from original audio; refusing to trim, loop or stretch it.')
    if abs(gap) < .5 / float(rate):
        return Path(generated)
    padded = folder / 'seedance-duration-aligned.mp4'
    # A rolling last frame avoids loading a whole video into memory.
    with av.open(str(generated)) as source, av.open(str(padded), 'w') as output:
        video = source.streams.video[0]
        stream = output.add_stream('libx264', rate=rate)
        stream.width, stream.height = video.width, video.height
        stream.pix_fmt = 'yuv420p'
        stream.options = {'crf': '18'}
        index = 0
        last = None
        target_count = math.ceil(duration * float(rate))
        for frame in source.decode(video=0):
            if index >= target_count:
                break
            last = frame.to_ndarray(format='rgb24')
            frame = av.VideoFrame.from_ndarray(last, format='rgb24')
            frame.pts, frame.time_base = index, 1 / rate
            for packet in stream.encode(frame):
                output.mux(packet)
            index += 1
        if last is None:
            raise ValueError('Generated video has no decodable frames.')
        while index < target_count:
            frame = av.VideoFrame.from_ndarray(last, format='rgb24')
            frame.pts, frame.time_base = index, 1 / rate
            for packet in stream.encode(frame):
                output.mux(packet)
            index += 1
        for packet in stream.encode():
            output.mux(packet)
    _save_json(folder / 'duration-adjustment.json',
               {'method': 'hold final frame' if gap > 0 else 'trim extra generated video frames',
                'seconds': abs(gap), 'original_audio': 'unchanged'})
    return padded


def finish_preview(generated, folder):
    """Discard generated sound and restore the prepared final-audio choice.

    Default: packet-copy all original audio tracks, including their channels.
    Explicit STS: encode a stereo converted-voice/residual mix, never described
    as byte-for-byte restoration. No network inference occurs during collection.
    """
    folder = Path(folder)
    target = folder / 'final-preview.mp4'
    source_path = folder / 'upload.mp4'
    manifest = _json(folder / 'audio-manifest.json')
    expected_source = manifest.get('original_source_sha256')
    if expected_source and expected_source != _sha256(source_path):
        raise ValueError('Original source changed after audio preparation; refusing to restore a different source.')
    with av.open(str(source_path)) as source:
        if not source.streams.audio:
            raise ValueError('Original source has no audio track.')
        duration = _duration(source)
    generated = _align_generated_video(generated, folder, duration)
    final_mode = manifest.get('final_audio_source', setting('FINAL_AUDIO_SOURCE', 'original'))
    if final_mode not in {'original', 'elevenlabs_sts'}:
        raise ValueError('Unknown final audio mode; refusing to substitute audio.')
    temporary = folder / 'final-preview.tmp.mp4'
    with av.open(str(generated)) as video, av.open(str(source_path)) as source, av.open(str(temporary), 'w') as output:
        original_video = video.streams.video[0]
        video_stream = output.add_stream_from_template(original_video)
        video_packets = _remapped_packets(video, {original_video.index: video_stream}, [original_video])
        if final_mode == 'original':
            mapping = {}
            for audio in source.streams.audio:
                stream = output.add_stream_from_template(audio)
                stream.metadata.update(audio.metadata)
                mapping[audio.index] = stream
            _mux_interleaved(output, video_packets,
                             _remapped_packets(source, mapping, list(source.streams.audio)))
            restoration = {'mode': 'original', 'audio_tracks': len(mapping),
                           'method': 'original compressed packets copied without re-encoding'}
        else:
            for name in ('elevenlabs-sts.wav', 'music.wav'):
                expected_artifact = manifest.get('final_audio_artifacts', {}).get(name)
                if expected_artifact and (not (folder / name).is_file() or expected_artifact != _sha256(folder / name)):
                    raise ValueError('Prepared final audio changed; prepare and review audio again.')
            converted = folder / 'elevenlabs-sts.wav'
            expected = manifest.get('speech_to_speech', {}).get('output_sha256')
            if not converted.is_file() or not expected or expected != _sha256(converted):
                raise ValueError('Approved ElevenLabs speech is unavailable or changed; prepare and review audio again.')
            count = round(duration * RATE)
            samples = _fit(read_audio(converted), count) + _fit(read_audio(folder / 'music.wav'), count)
            peak = float(np.max(np.abs(samples)))
            gain = min(1.0, .99 / peak) if peak else 1.0
            samples *= gain
            audio = output.add_stream('aac', rate=RATE)
            audio.layout, audio.bit_rate = 'stereo', 192000
            _mux_interleaved(output, video_packets, _encode_audio(output, audio, samples))
            restoration = {'mode': final_mode, 'method': 're-encoded stereo converted speech and estimated residual',
                           'gain': gain, 'residual_notice': RESIDUAL_NOTICE,
                           'original_audio_preserved': False}
    temporary.replace(target)
    _save_json(folder / 'audio-restoration.json', restoration)
    return target

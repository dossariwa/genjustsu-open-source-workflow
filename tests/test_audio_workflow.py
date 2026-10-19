"""No paid calls: synthetic media and mocked ElevenLabs responses."""
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
import json
import shutil
import tempfile
import unittest

import av
import numpy as np

import audio_workflow as audio


def sine(seconds=1, frequency=440, channels=2):
    wave = (np.sin(np.arange(round(seconds * audio.RATE)) * 2 * np.pi * frequency / audio.RATE) * .1).astype(np.float32)
    return np.tile(wave, (channels, 1))


def video_file(path, frames=24, tracks=()):
    with av.open(str(path), 'w') as output:
        video = output.add_stream('libx264', rate=24)
        video.width, video.height, video.pix_fmt = 64, 64, 'yuv420p'
        streams = []
        for channels, seconds, frequency in tracks:
            stream = output.add_stream('aac', rate=audio.RATE)
            stream.layout = 'mono' if channels == 1 else 'stereo'
            stream.metadata['language'] = 'eng'
            streams.append((stream, sine(seconds, frequency, channels)))
        for i in range(frames):
            frame = av.VideoFrame.from_ndarray(np.full((64, 64, 3), i % 255, dtype=np.uint8), format='rgb24')
            frame.pts, frame.time_base = i, Fraction(1, 24)
            for packet in video.encode(frame):
                output.mux(packet)
        for packet in video.encode():
            output.mux(packet)
        for stream, samples in streams:
            for i in range(0, samples.shape[1], 4096):
                frame = av.AudioFrame.from_ndarray(np.ascontiguousarray(samples[:, i:i+4096]), format='fltp', layout=stream.layout)
                frame.sample_rate, frame.pts, frame.time_base = audio.RATE, i, Fraction(1, audio.RATE)
                for packet in stream.encode(frame):
                    output.mux(packet)
            for packet in stream.encode():
                output.mux(packet)


def response(*, content=b'', payload=None):
    return SimpleNamespace(content=content, json=lambda: payload, raise_for_status=lambda: None)


def audio_packets(path):
    with av.open(str(path)) as source:
        streams = list(source.streams.audio)
        packets = {stream.index: [] for stream in streams}
        layouts = [stream.layout.name for stream in streams]
        for packet in source.demux(*streams):
            if packet.dts is not None:
                packets[packet.stream.index].append(bytes(packet))
        return list(packets.values()), layouts


class AudioWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.settings = {}
        self.patcher = patch.object(audio, 'setting', side_effect=lambda name, default='': self.settings.get(name, default))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        key = patch.object(audio, 'credential', return_value='test-key')
        key.start()
        self.addCleanup(key.stop)

    def wav(self, name, seconds=1, frequency=440):
        path = self.folder / name
        audio.write_audio(path, sine(seconds, frequency))
        return path

    def test_isolation_scribe_contract_and_cache_preserve_source(self):
        source = self.folder / 'upload.mp4'
        video_file(source, tracks=((2, 1, 440),))
        before = source.read_bytes()
        isolated = self.wav('response.wav')
        transcript = {'text': 'Hello there.', 'words': [{'text': 'Hello', 'start': 0.1, 'end': 0.4}]}
        with patch.object(audio.requests, 'post', side_effect=[response(content=isolated.read_bytes()), response(payload=transcript)]) as post:
            audio.separate(source, self.folder, lambda _: None)
            audio.separate(source, self.folder, lambda _: None)
        self.assertEqual(post.call_count, 2)
        isolation, transcription = post.call_args_list
        self.assertEqual(isolation.args[0], 'https://api.elevenlabs.io/v1/audio-isolation')
        self.assertIn('audio', isolation.kwargs['files'])
        self.assertEqual(isolation.kwargs['headers'], {'xi-api-key': 'test-key'})
        self.assertEqual(transcription.args[0], 'https://api.elevenlabs.io/v1/speech-to-text')
        self.assertEqual(transcription.kwargs['data'], {'model_id': 'scribe_v1'})
        self.assertIn('file', transcription.kwargs['files'])
        self.assertEqual((self.folder / 'dialogue.txt').read_text(), transcript['text'])
        self.assertEqual(json.loads((self.folder / 'dialogue_transcript.json').read_text()), transcript)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(audio.read_audio(self.folder / 'isolated_vocals.wav').shape[1], audio.RATE)
        manifest = (self.folder / 'audio-manifest.json').read_text()
        self.assertIn('Estimated residual', manifest)
        self.assertNotIn('test-key', manifest)

    def test_retry_transcription_does_not_repeat_successful_isolation(self):
        source = self.folder / 'upload.mp4'
        video_file(source, tracks=((2, 1, 440),))
        isolated = self.wav('response.wav')
        with patch.object(audio.requests, 'post', side_effect=[response(content=isolated.read_bytes()), RuntimeError('temporary failure'), response(payload={'text': 'Recovered'})]) as post:
            with self.assertRaisesRegex(RuntimeError, 'temporary failure'):
                audio.separate(source, self.folder, lambda _: None)
            audio.separate(source, self.folder, lambda _: None)
        self.assertEqual(post.call_count, 3)
        self.assertEqual(sum(call.args[0].endswith('/audio-isolation') for call in post.call_args_list), 1)

    def test_mp3_isolation_response_decodes_to_actual_wav(self):
        self.wav('original-audio.wav')
        mp3 = self.folder / 'response.mp3'
        with av.open(str(mp3), 'w', format='mp3') as output:
            stream = output.add_stream('libmp3lame', rate=audio.RATE)
            stream.layout = 'stereo'
            for packet in audio._encode_audio(output, stream, sine()):
                output.mux(packet)
        with patch.object(audio.requests, 'post', return_value=response(content=mp3.read_bytes())):
            isolated = audio.isolate_vocals(self.folder, lambda _: None)
        self.assertEqual(isolated.read_bytes()[:4], b'RIFF')
        self.assertEqual(audio.read_audio(isolated).shape, (2, audio.RATE))

    @unittest.skipUnless(shutil.which('rubberband'), 'Rubber Band is not installed')
    def test_pitch_shift_changes_pitch_preserving_exact_sample_duration(self):
        self.wav('isolated_vocals.wav')
        guidance = audio.prepare_guidance_audio(self.folder)
        samples = audio.read_audio(guidance)
        self.assertEqual(samples.shape[1], audio.RATE)
        middle = samples[0, 8000:36000]
        frequency = np.fft.rfftfreq(len(middle), 1 / audio.RATE)[np.argmax(np.abs(np.fft.rfft(middle)))]
        self.assertAlmostEqual(frequency, 440 * 2 ** (3 / 12), delta=4)
        with patch.object(audio, '_rubberband') as process:
            self.assertEqual(audio.prepare_guidance_audio(self.folder), guidance)
        process.assert_not_called()

    @unittest.skipUnless(shutil.which('rubberband'), 'Rubber Band is not installed')
    def test_sts_corrects_drift_over_40ms_and_caches_conversion(self):
        self.settings.update(AUDIO_DISGUISE_MODE='elevenlabs_sts', ELEVENLABS_VOICE_ID='voice/test')
        self.wav('isolated_vocals.wav')
        returned = self.wav('response.wav', 1.10)
        with patch.object(audio.requests, 'post', return_value=response(content=returned.read_bytes())) as post:
            first = audio.prepare_guidance_audio(self.folder)
            second = audio.prepare_guidance_audio(self.folder)
        self.assertEqual(first, second)
        self.assertEqual(post.call_count, 1)
        self.assertTrue(post.call_args.args[0].endswith('/speech-to-speech/voice%2Ftest'))
        self.assertEqual(post.call_args.kwargs['data'], {'model_id': 'eleven_multilingual_sts_v2'})
        self.assertEqual(audio.read_audio(first).shape[1], audio.RATE)
        data = json.loads((self.folder / 'audio-manifest.json').read_text())['speech_to_speech']
        self.assertTrue(data['rubberband_time_corrected'])
        self.assertAlmostEqual(data['time_ratio'], 1 / 1.1, places=5)
        self.assertIn('does not prove phoneme alignment', data['notice'])

    def test_sts_small_drift_only_fits_samples_and_requires_voice_id(self):
        self.settings['AUDIO_DISGUISE_MODE'] = 'elevenlabs_sts'
        self.wav('isolated_vocals.wav')
        with self.assertRaisesRegex(ValueError, 'ELEVENLABS_VOICE_ID'):
            audio.prepare_guidance_audio(self.folder)
        self.settings['ELEVENLABS_VOICE_ID'] = 'voice-id'
        returned = self.wav('response.wav', .98)
        with patch.object(audio.requests, 'post', return_value=response(content=returned.read_bytes())), patch.object(audio, '_rubberband') as process:
            guidance = audio.prepare_guidance_audio(self.folder)
        process.assert_not_called()
        self.assertEqual(audio.read_audio(guidance).shape[1], audio.RATE)

    @unittest.skipUnless(shutil.which('rubberband'), 'Rubber Band is not installed')
    def test_embedded_guidance_cache_changes_with_composite(self):
        self.wav('isolated_vocals.wav')
        composite = self.folder / 'composite-silent.mp4'
        video_file(composite)
        first = audio.prepare_seedance_video(self.folder)
        fingerprint = hashlib.sha256(first.read_bytes()).hexdigest()
        with patch.object(audio, '_rubberband') as process:
            audio.prepare_seedance_video(self.folder)
        process.assert_not_called()
        self.assertEqual(hashlib.sha256(first.read_bytes()).hexdigest(), fingerprint)
        video_file(composite, frames=23)
        audio.prepare_seedance_video(self.folder)
        self.assertNotEqual(hashlib.sha256(first.read_bytes()).hexdigest(), fingerprint)
        with av.open(str(first)) as source:
            self.assertEqual(len(source.streams.audio), 1)

    def test_original_final_copies_all_tracks_channels_and_longest_tail(self):
        source = self.folder / 'upload.mp4'
        generated = self.folder / 'generated.mp4'
        video_file(source, tracks=((1, 1, 440), (2, 1.2, 660)))
        video_file(generated, tracks=((2, 1, 880),))
        result = audio.finish_preview(generated, self.folder)
        self.assertEqual(audio_packets(source), audio_packets(result))
        with av.open(str(result)) as output:
            self.assertGreaterEqual(output.duration / av.time_base, 1.2)
            self.assertGreater(sum(1 for _ in output.decode(video=0)), 24)
        adjustment = json.loads((self.folder / 'duration-adjustment.json').read_text())
        self.assertEqual(adjustment['method'], 'hold final frame')
        self.assertAlmostEqual(adjustment['seconds'], .2, places=2)

    def test_final_sts_mix_is_explicit_reencoded_and_never_calls_api(self):
        source = self.folder / 'upload.mp4'
        generated = self.folder / 'generated.mp4'
        video_file(source, tracks=((2, 1, 440),))
        video_file(generated, tracks=((2, 1, 880),))
        converted = self.wav('elevenlabs-sts.wav', frequency=660)
        self.wav('music.wav', frequency=220)
        audio._manifest(self.folder, final_audio_source='elevenlabs_sts',
                        speech_to_speech={'output_sha256': audio._sha256(converted)})
        with patch.object(audio.requests, 'post') as post:
            result = audio.finish_preview(generated, self.folder)
        post.assert_not_called()
        self.assertNotEqual(audio_packets(source)[0], audio_packets(result)[0])
        self.assertEqual(audio.read_audio(result).shape[1], audio.RATE)
        restoration = json.loads((self.folder / 'audio-restoration.json').read_text())
        self.assertFalse(restoration['original_audio_preserved'])
        self.assertIn('Estimated residual', restoration['residual_notice'])

    def test_duration_gap_over_half_second_is_rejected(self):
        video_file(self.folder / 'upload.mp4', tracks=((2, 1, 440),))
        video_file(self.folder / 'generated.mp4', frames=10)
        with self.assertRaisesRegex(ValueError, 'refusing to trim'):
            audio.finish_preview(self.folder / 'generated.mp4', self.folder)
        self.assertFalse((self.folder / 'final-preview.mp4').exists())

    def test_short_generated_tail_is_trimmed_without_touching_original_audio(self):
        source = self.folder / 'upload.mp4'
        video_file(source, tracks=((2, 1, 440),))
        video_file(self.folder / 'generated.mp4', frames=36)
        result = audio.finish_preview(self.folder / 'generated.mp4', self.folder)
        self.assertEqual(audio_packets(source), audio_packets(result))
        with av.open(str(result)) as output:
            self.assertEqual(sum(1 for _ in output.decode(video=0)), 24)
        adjustment = json.loads((self.folder / 'duration-adjustment.json').read_text())
        self.assertEqual(adjustment['method'], 'trim extra generated video frames')

    def test_changed_sts_artifact_cannot_be_exported(self):
        video_file(self.folder / 'upload.mp4', tracks=((2, 1, 440),))
        video_file(self.folder / 'generated.mp4')
        self.wav('elevenlabs-sts.wav')
        audio._manifest(self.folder, final_audio_source='elevenlabs_sts', speech_to_speech={'output_sha256': 'wrong'})
        with self.assertRaisesRegex(ValueError, 'unavailable or changed'):
            audio.finish_preview(self.folder / 'generated.mp4', self.folder)


if __name__ == '__main__':
    unittest.main()

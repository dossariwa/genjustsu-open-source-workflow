import json
import tempfile
import unittest
import zipfile
from fractions import Fraction
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import av
from PIL import Image
import hf_client
import pipeline
import raw_masks

RAW_SCHEMA = {'named_endpoints': {'/segment_raw': {
    'parameters': [
        {'parameter_name': 'video', 'component': 'Video', 'parameter_has_default': False},
        {'parameter_name': 'text_prompt', 'component': 'Textbox', 'parameter_has_default': False}],
    'returns': [{'component': 'File', 'label': 'Raw masks ZIP'}]}}}
DEPTH_SCHEMA = {'named_endpoints': {'/infer_video_depth': {
    'parameters': [{'parameter_name': name} for name in ['input_video', 'max_len', 'target_fps', 'max_res', 'grayscale']],
    'returns': [{'component': 'Video', 'label': 'Preprocessed video'}, {'component': 'Video', 'label': 'Generated Depth Video'}]}}}


def video(path, count=3, width=64, height=64, color=(180, 40, 40)):
    c, s = pipeline.writer(path, width, height, lossless=True)
    for i in range(count):
        pipeline.put(c, s, np.full((height, width, 3), color, dtype=np.uint8), i)
    pipeline.finish(c, s)
    return path


def masks(folder, count=3, size=(64, 64), indices=None, value=None):
    folder.mkdir(parents=True, exist_ok=True)
    for index in indices if indices is not None else range(count):
        array = np.zeros(size[::-1], dtype=np.uint8)
        array[16:48, 16:48] = 255
        if value is not None:
            array[:] = value
        Image.fromarray(array).save(folder / f'mask_{index:06d}.png')
    return folder


def archive(path, folder):
    with zipfile.ZipFile(path, 'w') as zipped:
        for item in folder.iterdir():
            zipped.write(item, item.name)
    return path


def configured_settings(overrides=None):
    values = {'HF_SAM_SPACE': 'owner/raw-sam3', 'HF_SAM_API_NAME': '/segment_raw'}
    values.update(overrides or {})
    return lambda name, default='': values.get(name, default)


class HuggingFaceTests(unittest.TestCase):
    def test_token_constructor_versions(self):
        for keyword in ['token', 'hf_token']:
            calls = []
            if keyword == 'token':
                def fake(space, token=None, verbose=True):
                    calls.append((space, token, verbose))
            else:
                def fake(space, hf_token=None, verbose=True):
                    calls.append((space, hf_token, verbose))
            with patch.object(hf_client, 'Client', fake), patch.object(hf_client, 'credential', return_value='secret'):
                hf_client.client('owner/space')
            self.assertEqual(calls, [('owner/space', 'secret', False)])

    def test_overlay_only_default_blocks_before_remote_calls(self):
        with patch.object(raw_masks, 'setting', side_effect=lambda name, default='': default), patch.object(raw_masks, 'client') as client:
            self.assertFalse(raw_masks.configuration_status()['ready'])
            with self.assertRaisesRegex(ValueError, 'overlay playback'):
                raw_masks.inspect_endpoint()
            client.assert_not_called()
        with patch.object(raw_masks, 'configuration_status', return_value={'ready': False, 'detail': 'unsupported raw masks'}), patch('audio_workflow.separate') as audio:
            with self.assertRaisesRegex(ValueError, 'unsupported raw masks'):
                pipeline.run('unused.mp4', 'unused-folder')
            audio.assert_not_called()

    def test_legacy_provider_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Legacy providers'):
            pipeline.run('unused.mp4', 'unused-folder', provider='replicate')

    def test_overlay_schema_is_not_submitted(self):
        connection = MagicMock()
        connection.view_api.return_value = {'named_endpoints': {'/segment_raw': {
            'parameters': RAW_SCHEMA['named_endpoints']['/segment_raw']['parameters'],
            'returns': [{'component': 'Video', 'label': 'Rendered Playback'}]}}}
        with patch.object(raw_masks, 'setting', side_effect=configured_settings()), patch.object(raw_masks, 'client', return_value=connection):
            with self.assertRaisesRegex(ValueError, 'Overlay outputs'):
                raw_masks.inspect_endpoint()
        connection.predict.assert_not_called()

    def test_depth_cloud_contract_and_unchanged_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            src, remote, dst = video(p / 'original.mp4'), video(p / 'returned.mp4', color=(40, 150, 220)), p / 'depth.mp4'
            connection = MagicMock()
            connection.view_api.return_value = DEPTH_SCHEMA
            connection.predict.return_value = ({'video': str(src)}, {'video': str(remote)})
            with patch.object(pipeline, 'client', return_value=connection):
                pipeline.depth_hf(src, dst)
            self.assertEqual(dst.read_bytes(), remote.read_bytes())
            kwargs = connection.predict.call_args.kwargs
            self.assertFalse(kwargs['grayscale'])
            self.assertEqual((kwargs['target_fps'], kwargs['max_res'], kwargs['max_len']), (24, 960, -1))

    def test_depth_alignment_rejects_shortened_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'Frame alignment'):
                pipeline.validate_depth_alignment(video(p / 'source.mp4'), video(p / 'depth.mp4', count=2))

    def test_depth_alignment_rejects_same_count_with_wrong_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            src = video(p / 'source.mp4')
            with av.open(str(p / 'slow.mp4'), 'w') as output:
                stream = output.add_stream('libx264', rate=12)
                stream.width = stream.height = 64
                stream.pix_fmt = 'yuv420p'
                for index in range(3):
                    frame = av.VideoFrame.from_ndarray(np.zeros((64, 64, 3), np.uint8), format='rgb24')
                    frame.pts, frame.time_base = index, Fraction(1, 12)
                    for packet in stream.encode(frame):
                        output.mux(packet)
                for packet in stream.encode():
                    output.mux(packet)
            with self.assertRaisesRegex(ValueError, 'timestamps'):
                pipeline.validate_depth_alignment(src, p / 'slow.mp4')

    def test_configured_secondary_can_replace_unsupported_public_primary(self):
        settings = configured_settings({'HF_SAM_SPACE': raw_masks.DEFAULT_SAM_SPACE, 'HF_SAM_API_NAME': '',
                                        'HF_SAM_FALLBACK_SPACE': 'owner/raw', 'HF_SAM_FALLBACK_API_NAME': '/segment_raw'})
        with patch.object(raw_masks, 'setting', side_effect=settings):
            status = raw_masks.configuration_status()
        self.assertTrue(status['ready'])
        self.assertEqual(status['space'], 'owner/raw')

    def test_normalize_resizes_without_mutating_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            src = video(p / 'large.mp4', count=2, width=1024, height=512)
            original_bytes = src.read_bytes()
            meta = pipeline.normalize(src, p / 'normalized.mp4')
            self.assertEqual(meta['fps'], 24)
            self.assertEqual((meta['width'], meta['height']), (960, 480))
            self.assertEqual(meta['frames'], 2)
            self.assertEqual(src.read_bytes(), original_bytes)

    def test_raw_zip_is_validated_and_request_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            src = video(p / 'source.mp4')
            remote = archive(p / 'remote.zip', masks(p / 'remote-masks'))
            connection = MagicMock()
            connection.view_api.return_value = RAW_SCHEMA
            connection.predict.return_value = str(remote)
            with patch.object(raw_masks, 'setting', side_effect=configured_settings()), patch.object(raw_masks, 'client', return_value=connection):
                result = raw_masks.segment_raw(src, p / 'job', 'person')
            self.assertEqual(len(list(result.glob('mask_*.png'))), 3)
            metadata = json.loads((p / 'job' / 'sam-raw-request.json').read_text())
            self.assertEqual(metadata['space'], 'owner/raw-sam3')
            self.assertNotIn('token', json.dumps(metadata).lower())
            self.assertFalse(json.loads((p / 'job' / 'mask-validation.json').read_text())['visual_approval'])

    def test_raw_zip_rejects_missing_shifted_duplicate_and_wrong_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            src = video(p / 'source.mp4')
            for label, indices, size in [('missing', [0, 1], (64, 64)), ('shifted', [1, 2, 3], (64, 64)), ('dimension', [0, 1, 2], (32, 32))]:
                with self.subTest(label=label), self.assertRaisesRegex(ValueError, 'Frame alignment'):
                    raw_masks.validate_masks(masks(p / label, indices=indices, size=size), src)
            zipped = p / 'duplicates.zip'
            with zipfile.ZipFile(zipped, 'w') as z:
                z.write(p / 'missing' / 'mask_000000.png', 'a/mask_000000.png')
                z.write(p / 'missing' / 'mask_000000.png', 'b/mask_000000.png')
                z.write(p / 'missing' / 'mask_000001.png', 'mask_000001.png')
            with self.assertRaisesRegex(ValueError, 'Frame alignment'):
                raw_masks._extract_archive(zipped, p / 'unpacked', 3, (64, 64))

    def test_overlay_artifact_never_recovered_as_raw_mask(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            source = video(p / 'source.mp4')
            with self.assertRaisesRegex(ValueError, 'overlay video'):
                pipeline.composite(source, source, source, p)
            folder = masks(p / 'masks')
            Image.fromarray(np.full((64, 64, 3), (0, 255, 0), np.uint8)).save(folder / 'mask_000000.png')
            with self.assertRaisesRegex(ValueError, 'colored'):
                raw_masks.validate_masks(folder, source)

    def test_configured_secondary_endpoint_records_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            src = video(p / 'source.mp4')
            remote = archive(p / 'remote.zip', masks(p / 'remote-masks'))
            failed, success = MagicMock(), MagicMock()
            failed.view_api.return_value = success.view_api.return_value = RAW_SCHEMA
            failed.predict.side_effect = RuntimeError('provider unavailable')
            success.predict.return_value = str(remote)
            settings = configured_settings({'HF_SAM_FALLBACK_SPACE': 'owner/fallback', 'HF_SAM_FALLBACK_API_NAME': '/segment_raw'})
            with patch.object(raw_masks, 'setting', side_effect=settings), patch.object(raw_masks, 'client', side_effect=[failed, success]):
                raw_masks.segment_raw(src, p / 'job')
            metadata = json.loads((p / 'job' / 'sam-raw-request.json').read_text())
            self.assertTrue(metadata['fallback_used'])
            self.assertEqual(metadata['space'], 'owner/fallback')

    def test_rgb_retry_keeps_colored_depth_unchanged_and_records_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            video(p / 'original.mp4')
            video(p / 'depth.mp4', color=(25, 99, 224))
            depth_bytes = (p / 'depth.mp4').read_bytes()
            def segment(source, folder, prompt):
                return masks(Path(folder) / 'raw-masks', value=0 if Path(source).name == 'depth.mp4' else None)
            with patch.object(raw_masks, 'segment_raw', side_effect=segment) as call:
                selected, fallback = pipeline.segment_with_rgb_fallback(p, 'person', status=lambda _: None)
            self.assertTrue(fallback)
            self.assertEqual([x.args[0].name for x in call.call_args_list], ['depth.mp4', 'original.mp4'])
            self.assertEqual((p / 'depth.mp4').read_bytes(), depth_bytes)
            self.assertEqual(selected.parent.name, 'rgb-mask-fallback')
            self.assertTrue(json.loads((p / 'mask-source.json').read_text())['rgb_fallback_used'])

    def test_invalid_rgb_retry_still_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            video(p / 'original.mp4')
            video(p / 'depth.mp4')
            with patch.object(raw_masks, 'segment_raw', side_effect=lambda source, folder, prompt: masks(Path(folder) / 'raw-masks', value=255)):
                with self.assertRaisesRegex(ValueError, 'remain empty or nearly full'):
                    pipeline.segment_with_rgb_fallback(p, 'person', status=lambda _: None)
            self.assertFalse(json.loads((p / 'mask-source.json').read_text())['visual_approval'])


if __name__ == '__main__':
    unittest.main()

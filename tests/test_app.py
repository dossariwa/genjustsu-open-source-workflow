"""HTTP and recovery integration tests. Provider calls are always mocked."""
from fractions import Fraction
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
import json
import tempfile
import unittest

import av
import numpy as np
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

import app as ui
import config
import mask_review
import seedance_bridge
import workflow


class InlineThread:
    """Execute short mocked jobs deterministically; never contact a provider."""
    def __init__(self, target, daemon=True):
        self.target = target

    def start(self):
        self.target()


class AppIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runs = Path(self.temp.name)
        for name, value in [('RUNS', self.runs), ('jobs', {}), ('hd_jobs', {}), ('collecting', set())]:
            mocked = patch.object(ui, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.client = TestClient(ui.app)
        self.addCleanup(self.client.close)
        self.ident = 'a' * 32
        self.folder = self.runs / self.ident
        self.folder.mkdir()

    def prepared(self):
        for name in mask_review.FILES:
            (self.folder / name).write_bytes(b'prepared test artifact')
        return mask_review.fingerprint(self.folder)

    def approved(self):
        current = self.prepared()
        mask_review.review(self.folder, True, 'User reviewed the entire clip and audio.', current)
        return current

    def test_health_reports_ui_only_without_provider_calls(self):
        with patch('requests.post') as network, patch('seedance_bridge.submit') as submit:
            result = self.client.get('/health')
        self.assertEqual(result.status_code, 200)
        self.assertIn('does not establish provider readiness', result.json()['generation_readiness'])
        network.assert_not_called()
        submit.assert_not_called()

    def test_telemetry_reads_only_account_and_omits_private_fields(self):
        account = {'user': {'uid': 'private-id', 'email': 'private@example.test'},
                   'plan': 'Starter', 'credits': 4000, 'accessToken': 'private-token',
                   'download_url': 'https://example.test/private?signature=secret'}
        with patch('openart_transport.OpenArtTransport') as transport:
            transport.return_value.call.return_value = account
            result = self.client.get('/telemetry')
        self.assertEqual(result.status_code, 200)
        transport.return_value.call.assert_called_once_with('openart_account_get', {})
        summary = result.json()['openart']
        self.assertTrue(summary['authenticated'])
        self.assertEqual(summary['plan'], 'Starter')
        self.assertEqual(summary['credits'], 4000)
        self.assertTrue(summary['checked_at'])
        self.assertIn('remain unverified', summary['detail'])
        self.assertNotIn('private', result.text)
        self.assertNotIn('secret', result.text)

    def test_telemetry_failure_never_returns_provider_error(self):
        with patch('openart_transport.OpenArtTransport') as transport:
            transport.return_value.call.side_effect = RuntimeError('token=secret https://example.test/private')
            result = self.client.get('/telemetry')
        self.assertEqual(result.status_code, 200)
        summary = result.json()['openart']
        self.assertFalse(summary['authenticated'])
        self.assertIsNone(summary['plan'])
        self.assertIsNone(summary['credits'])
        self.assertIsNone(summary['checked_at'])
        self.assertNotIn('secret', result.text)
        self.assertNotIn('https://', result.text)

    def test_telemetry_requires_account_identity_and_finite_credit_balance(self):
        with patch('openart_transport.OpenArtTransport') as transport:
            for account in [None, {}, {'user': 'invalid'}, {'user': {'uid': ''}}]:
                with self.subTest(account=account):
                    transport.return_value.call.return_value = account
                    self.assertFalse(self.client.get('/telemetry').json()['openart']['authenticated'])
            for credits in [True, -1, float('nan'), float('inf'), '4000']:
                with self.subTest(credits=credits):
                    transport.return_value.call.return_value = {'user': {'uid': 'valid'}, 'credits': credits}
                    summary = self.client.get('/telemetry').json()['openart']
                    self.assertTrue(summary['authenticated'])
                    self.assertIsNone(summary['credits'])

    def test_invalid_job_and_modes_are_rejected_before_work(self):
        self.assertEqual(self.client.get('/jobs/not-a-job').status_code, 404)
        self.assertEqual(self.client.get('/jobs/' + 'f' * 32).status_code, 404)
        with patch.object(ui.threading, 'Thread') as worker:
            for data in [{'mode': 'unknown'}, {'provider': 'replicate'}]:
                result = self.client.post('/jobs', data=data, files={'video': ('source.mp4', b'video', 'video/mp4')})
                self.assertEqual(result.status_code, 400)
        worker.assert_not_called()

    def test_fast_preparation_skips_huggingface_and_persists_state(self):
        with patch('raw_masks.configuration_status') as readiness, patch('face_mesh.run') as prepare, patch.object(ui.threading, 'Thread', InlineThread):
            result = self.client.post('/jobs', data={'mode': 'face_mesh'}, files={'video': ('source.mp4', b'original video', 'video/mp4')})
        self.assertEqual(result.status_code, 200)
        readiness.assert_not_called()
        prepare.assert_called_once()
        job = result.json()
        folder = self.runs / job['id']
        self.assertEqual((folder / 'upload.mp4').read_bytes(), b'original video')
        self.assertEqual(json.loads((folder / 'status.json').read_text())['state'], 'done')
        ui.jobs.clear()
        self.assertEqual(self.client.get('/jobs/' + job['id']).json()['state'], 'done')

    def test_unconfigured_raw_masks_block_depth_before_audio_spend(self):
        with patch('raw_masks.configuration_status', return_value={'ready': False, 'detail': 'Raw masks unavailable'}), patch.object(ui.threading, 'Thread') as worker, patch('audio_workflow.separate') as audio:
            result = self.client.post('/jobs', data={'mode': 'depth'}, files={'video': ('source.mp4', b'video', 'video/mp4')})
        self.assertEqual(result.status_code, 409)
        worker.assert_not_called()
        audio.assert_not_called()

    def test_stale_review_blocks_submission_before_bridge(self):
        self.approved()
        (self.folder / 'guidance-audio.wav').write_bytes(b'changed speech')
        with patch('seedance_bridge.submit') as submit:
            result = self.client.post('/jobs/' + self.ident + '/seedance', data={'prompt': 'Replace the subject'}, files={'sirio': ('character.png', b'character', 'image/png')})
        self.assertEqual(result.status_code, 409)
        submit.assert_not_called()

    def test_credit_quote_waits_for_explicit_approval_without_collection(self):
        self.approved()
        with patch('seedance_bridge.submit', side_effect=seedance_bridge.CreditApprovalRequired(25)), patch.object(ui, 'start_collection') as collect:
            result = self.client.post('/jobs/' + self.ident + '/seedance', data={'prompt': 'Replace the subject'}, files={'sirio': ('character.png', b'character', 'image/png')})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['state'], 'awaiting_credit_approval')
        self.assertEqual(result.json()['minimum_credit_ceiling'], 25)
        collect.assert_not_called()

    def test_noninteger_credit_ceiling_is_rejected_before_bridge(self):
        with patch('seedance_bridge.resume_approved') as approve, patch.object(ui, 'start_collection') as collect:
            for value in ['25.5', 'nan', 'Infinity', 'not-a-number']:
                with self.subTest(value=value):
                    result = self.client.post('/jobs/' + self.ident + '/credit-approval', data={'credit_ceiling': value})
                    self.assertEqual(result.status_code, 422)
        approve.assert_not_called()
        collect.assert_not_called()

    def test_generation_freezes_prompt_before_any_vision_call(self):
        for filename in ['openart-state.json', 'dreamina-state.json']:
            with self.subTest(filename=filename):
                saved = self.folder / filename
                saved.write_text('{"submit_id":"saved"}')
                with patch('openai_helper.generate_seedance_prompt') as vision:
                    result = self.client.post('/jobs/' + self.ident + '/prompt', files={'sirio': ('character.png', b'character', 'image/png')})
                self.assertEqual(result.status_code, 409)
                vision.assert_not_called()
                self.assertFalse((self.folder / 'sirio-reference.png').exists())
                saved.unlink()

    def test_saved_provider_job_blocks_new_submission_and_reference_replacement(self):
        self.approved()
        reference = self.folder / 'sirio-reference.png'
        reference.write_bytes(b'approved reference')
        for filename in ['openart-state.json', 'dreamina-state.json']:
            with self.subTest(filename=filename):
                saved = self.folder / filename
                saved.write_text('{"submit_id":"saved"}')
                with patch('seedance_bridge.submit') as submit:
                    result = self.client.post('/jobs/' + self.ident + '/seedance', data={'prompt': 'Changed prompt'}, files={'sirio': ('character.png', b'changed reference', 'image/png')})
                self.assertEqual(result.status_code, 409)
                self.assertEqual(reference.read_bytes(), b'approved reference')
                submit.assert_not_called()
                saved.unlink()

    def test_video_identity_never_calls_image_prompt_helper(self):
        with patch('openai_helper.generate_seedance_prompt') as vision:
            result = self.client.post('/jobs/' + self.ident + '/prompt', files={'sirio': ('character.mp4', b'video', 'video/mp4')})
        self.assertEqual(result.status_code, 400)
        vision.assert_not_called()

    def test_audit_has_no_approval_and_invalidates_if_artifacts_change(self):
        self.prepared()
        def inspect(_):
            (self.folder / 'mask.mp4').write_bytes(b'new mask')
            return {'advisory_only': True, 'full_clip_review': False, 'findings': 'Old mask observations'}
        with patch('openai_helper.sample_video_frames', return_value=[]), patch('openai_helper.auto_audit_mask_quality', side_effect=inspect):
            result = self.client.post('/jobs/' + self.ident + '/audit')
        self.assertEqual(result.status_code, 502)
        self.assertIn('Artifacts changed', result.json()['detail'])
        self.assertFalse((self.folder / 'mask-audit.json').exists())
        self.assertFalse(mask_review.state(self.folder)['approved'])

    def test_manual_review_requires_current_fingerprint_and_findings(self):
        current = self.prepared()
        endpoint = '/jobs/' + self.ident + '/mask-review'
        empty = self.client.post(endpoint, data={'approved': 'true', 'fingerprint': current, 'note': ''})
        self.assertEqual(empty.status_code, 409)
        accepted = self.client.post(endpoint, data={'approved': 'true', 'fingerprint': current, 'note': 'User reviewed the full clip.'})
        self.assertEqual(accepted.status_code, 200)
        (self.folder / 'composite-silent.mp4').write_bytes(b'changed composite')
        self.assertFalse(self.client.get(endpoint).json()['approved'])

    def test_startup_recovers_observation_but_never_approves_or_submits(self):
        states = [
            ('a' * 32, {'status': 'awaiting_credit_approval', 'submit_id': 'quote', 'minimum_credit_ceiling': 10}),
            ('b' * 32, {'status': 'submitted', 'submit_id': 'accepted'}),
            ('c' * 32, {'status': 'draft_created', 'submit_id': 'unsubmitted'}),
        ]
        for ident, state in states:
            folder = self.runs / ident
            folder.mkdir(exist_ok=True)
            (folder / 'dreamina-state.json').write_text(json.dumps(state))
        with patch.object(ui, 'start_collection') as collect, patch('seedance_bridge.submit') as submit, patch('seedance_bridge.resume_approved') as approve, patch('audio_workflow.separate') as audio:
            ui.resume_saved_generations()
        collect.assert_called_once_with(self.runs / ('b' * 32), 'accepted')
        submit.assert_not_called()
        approve.assert_not_called()
        audio.assert_not_called()
        self.assertEqual(ui.jobs[self.ident]['state'], 'awaiting_credit_approval')

    def test_startup_collects_openart_history_without_spending(self):
        states = [
            ('a' * 32, {'status': 'awaiting_credit_approval', 'minimum_credit_ceiling': 240}),
            ('b' * 32, {'status': 'submitted', 'history_id': 'openart-history'}),
            ('c' * 32, {'status': 'preparing'}),
            ('d' * 32, {'status': 'uncertain'}),
        ]
        for ident, state in states:
            folder = self.runs / ident
            folder.mkdir(exist_ok=True)
            (folder / 'openart-state.json').write_text(json.dumps(state))
        with patch.object(ui, 'start_collection') as collect, patch('seedance_bridge.submit') as submit, patch('seedance_bridge.resume_approved') as approve, patch('seedance_bridge.resume_preparation') as prepare:
            ui.resume_saved_generations()
        collect.assert_called_once_with(self.runs / ('b' * 32), 'openart-history')
        submit.assert_not_called()
        approve.assert_not_called()
        prepare.assert_not_called()
        self.assertEqual(ui.jobs[self.ident]['minimum_credit_ceiling'], 240)

    def test_resume_uses_saved_openart_history_and_never_submits(self):
        (self.folder / 'openart-state.json').write_text('{"history_id":"accepted-history","status":"submitted"}')
        ui.jobs[self.ident] = {'id': self.ident, 'state': 'running'}
        with patch.object(ui, 'start_collection') as collect, patch('seedance_bridge.submit') as submit, patch('seedance_bridge.resume_approved') as approve:
            result = self.client.post('/jobs/' + self.ident + '/resume')
        self.assertEqual(result.status_code, 200)
        collect.assert_called_once_with(self.folder, 'accepted-history')
        submit.assert_not_called()
        approve.assert_not_called()

    def test_uncertain_openart_submission_without_history_is_not_retried(self):
        (self.folder / 'openart-state.json').write_text('{"status":"uncertain"}')
        with patch.object(ui, 'start_collection') as collect, patch('seedance_bridge.submit') as submit:
            result = self.client.post('/jobs/' + self.ident + '/resume')
        self.assertEqual(result.status_code, 409)
        self.assertIn('no generation ID', result.json()['detail'])
        collect.assert_not_called()
        submit.assert_not_called()

    def test_omitting_second_reference_removes_previous_mapping(self):
        (self.folder / 'tein-reference.jpg').write_bytes(b'old secondary')
        primary = UploadFile(filename='primary.png', file=BytesIO(b'new primary'))
        self.addCleanup(primary.file.close)
        references = ui.store_references(self.folder, primary, None)
        self.assertIsNone(references[1])
        self.assertEqual(list(self.folder.glob('tein-reference.*')), [])

    def test_corrupt_status_does_not_prevent_recovering_other_jobs(self):
        (self.folder / 'status.json').write_text('{interrupted')
        second = self.runs / ('b' * 32)
        second.mkdir()
        (second / 'status.json').write_text('{"state":"running"}')
        with patch.object(ui, 'start_collection') as collect:
            ui.resume_saved_generations()
        collect.assert_not_called()
        self.assertEqual(ui.jobs[second.name]['state'], 'error')

    def test_cli_audit_cannot_bind_old_samples_to_changed_artifacts(self):
        self.prepared()
        # CLI ROOT/runs must resolve to our temporary job tree.
        root = self.runs / 'cli-root'
        root.mkdir()
        (root / 'runs').symlink_to(self.runs, target_is_directory=True)
        def inspect(_):
            (self.folder / 'mask.mp4').write_bytes(b'new mask')
            return {'advisory_only': True, 'full_clip_review': False, 'findings': 'Old observations'}
        with patch.object(workflow, 'ROOT', root), patch.object(workflow, 'load_env'), patch('openai_helper.sample_video_frames', return_value=[]), patch('openai_helper.auto_audit_mask_quality', side_effect=inspect):
            with self.assertRaisesRegex(ValueError, 'changed'):
                workflow.main(['audit', self.ident])
        self.assertFalse((self.folder / 'mask-audit.json').exists())

    def test_incomplete_preparation_cannot_generate_prompt(self):
        (self.folder / 'original.mp4').write_bytes(b'video')
        with patch('openai_helper.generate_seedance_prompt') as vision:
            result = self.client.post('/jobs/' + self.ident + '/prompt', files={'sirio': ('character.png', b'character', 'image/png')})
        self.assertEqual(result.status_code, 409)
        vision.assert_not_called()

    def test_prompt_cannot_bind_to_changed_artifacts(self):
        self.prepared()
        def suggest(*args):
            (self.folder / 'guidance-audio.wav').write_bytes(b'new speech')
            return 'Stale suggestion'
        with patch('openai_helper.sample_video_frames', return_value=['fixture.png']), patch('openai_helper.generate_seedance_prompt', side_effect=suggest):
            result = self.client.post('/jobs/' + self.ident + '/prompt', files={'sirio': ('character.png', b'character', 'image/png')})
        self.assertEqual(result.status_code, 502)
        self.assertFalse((self.folder / 'prompt-suggestion.json').exists())

    def test_corrupt_review_requires_fresh_approval(self):
        self.prepared()
        (self.folder / 'mask-review.json').write_text('{incomplete')
        (self.folder / 'mask-audit.json').write_text('{incomplete')
        result = self.client.get('/jobs/' + self.ident + '/mask-review')
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json()['approved'])
        self.assertNotIn('audit', result.json())

    def test_explicit_preparation_resume_returns_quote_without_collection(self):
        with patch('seedance_bridge.resume_preparation', side_effect=seedance_bridge.CreditApprovalRequired(30)) as prepare, patch.object(ui, 'start_collection') as collect:
            result = self.client.post('/jobs/' + self.ident + '/resume-preparation')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['minimum_credit_ceiling'], 30)
        prepare.assert_called_once_with(self.folder)
        collect.assert_not_called()



def synthetic_clip(path, fps, seconds, size=64):
    """Write a tiny H.264 clip with an exact stream duration for limit tests."""
    frames = int(round(seconds * fps))
    with av.open(str(path), 'w') as out:
        stream = out.add_stream('libx264', rate=fps)
        stream.width = stream.height = size
        stream.pix_fmt = 'yuv420p'
        for index in range(frames):
            frame = av.VideoFrame.from_ndarray(
                np.full((size, size, 3), 40, dtype=np.uint8), format='rgb24')
            frame.pts = index
            frame.time_base = Fraction(1, fps)
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)


class DepthDurationLimitTests(unittest.TestCase):
    """Server-side depth clip limit; pipelines stay mocked (no network/paid calls)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runs = Path(self.temp.name)
        for name, value in [('RUNS', self.runs), ('jobs', {}), ('hd_jobs', {}), ('collecting', set())]:
            mocked = patch.object(ui, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.client = TestClient(ui.app)
        self.addCleanup(self.client.close)
        self.clip_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.clip_dir.cleanup)
        self.clips = Path(self.clip_dir.name)

    def clip_bytes(self, fps, seconds):
        path = self.clips / f'{fps}fps-{seconds}s.mp4'
        if not path.exists():
            synthetic_clip(path, fps, seconds)
        return path.read_bytes()

    def post_job(self, mode, fps, seconds, pipeline_target):
        readiness = {'ready': True, 'detail': 'configured', 'space': 'test', 'api_name': '/segment_raw'}
        with patch('raw_masks.configuration_status', return_value=readiness), \
                patch(pipeline_target) as prepare, \
                patch.object(ui.threading, 'Thread', InlineThread):
            result = self.client.post(
                '/jobs', data={'mode': mode},
                files={'video': ('source.mp4', self.clip_bytes(fps, seconds), 'video/mp4')})
        return result, prepare

    def test_depth_clip_at_most_eight_seconds_is_accepted(self):
        result, prepare = self.post_job('depth', 24, 7.5, 'pipeline.run')
        self.assertEqual(result.status_code, 200)
        prepare.assert_called_once()
        self.assertEqual(result.json()['state'], 'done')

    def test_depth_clip_over_eight_seconds_is_rejected_with_400(self):
        result, prepare = self.post_job('depth', 24, 9.0, 'pipeline.run')
        self.assertEqual(result.status_code, 400)
        self.assertIn('8.0 seconds', result.json()['detail'])
        self.assertIn('192 frames', result.json()['detail'])
        prepare.assert_not_called()
        self.assertEqual(list(self.runs.iterdir()), [])

    def test_depth_mesh_over_eight_seconds_is_rejected(self):
        result, prepare = self.post_job('depth_mesh', 24, 9.0, 'face_mesh.run_depth')
        self.assertEqual(result.status_code, 400)
        self.assertIn('8.0 seconds', result.json()['detail'])
        prepare.assert_not_called()
        self.assertEqual(list(self.runs.iterdir()), [])

    def test_face_mesh_over_eight_seconds_remains_accepted(self):
        with patch('face_mesh.run') as prepare, patch.object(ui.threading, 'Thread', InlineThread):
            result = self.client.post(
                '/jobs', data={'mode': 'face_mesh'},
                files={'video': ('source.mp4', self.clip_bytes(24, 9.0), 'video/mp4')})
        self.assertEqual(result.status_code, 200)
        prepare.assert_called_once()

    def test_exactly_eight_seconds_at_24fps_is_accepted(self):
        result, prepare = self.post_job('depth', 24, 8.0, 'pipeline.run')
        self.assertEqual(result.status_code, 200)
        prepare.assert_called_once()

    def test_eight_second_clip_at_30fps_is_accepted(self):
        # Source duration is 8s; after 24fps resample normalize yields 192 frames.
        result, prepare = self.post_job('depth', 30, 8.0, 'pipeline.run')
        self.assertEqual(result.status_code, 200)
        prepare.assert_called_once()
        from pipeline import probe_source_duration, normalized_frame_count
        path = self.clips / '30fps-8.0s.mp4'
        duration = probe_source_duration(path)
        self.assertEqual(duration, 8.0)
        self.assertEqual(normalized_frame_count(duration), config.DEPTH_MAX_FRAMES)

    def test_capabilities_exposes_depth_clip_limits(self):
        generation = {'provider': 'openart', 'mode': 'element2video', 'video_hd_supported': False,
                      'available': False, 'detail': 'mocked'}
        segmentation = {'ready': False, 'detail': 'mocked', 'space': None, 'api_name': None}
        with patch('seedance_bridge.capabilities', return_value=generation), \
                patch('raw_masks.configuration_status', return_value=segmentation):
            result = self.client.get('/capabilities')
        self.assertEqual(result.status_code, 200)
        body = result.json()
        self.assertEqual(body['generation']['provider'], 'openart')
        limits = body['clip_limits']
        self.assertEqual(limits['depth'], {
            'max_seconds': config.DEPTH_MAX_SECONDS,
            'max_frames': config.DEPTH_MAX_FRAMES,
            'fps': config.DEPTH_FPS,
        })
        self.assertEqual(limits['depth_mesh'], limits['depth'])
        self.assertEqual(limits['face_mesh']['max_seconds'], 30)
        self.assertEqual(config.DEPTH_MAX_FRAMES, config.DEPTH_MAX_SECONDS * config.DEPTH_FPS)
        self.assertEqual(config.DEPTH_MAX_FRAMES, 192)


class UiVariantTests(unittest.TestCase):
    """FastAPI serves the Next.js export when built, else the legacy UI."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name) / 'out'
        mocked = patch.object(ui, 'WEB_OUT', self.out)
        mocked.start()
        self.addCleanup(mocked.stop)
        self.client = TestClient(ui.app)
        self.addCleanup(self.client.close)
        self.legacy = (config.ROOT / 'static/index.html').read_text()

    def build(self):
        self.out.mkdir()
        (self.out / 'index.html').write_text('<!doctype html><title>next studio export</title>')

    def ui_setting(self, value):
        original = ui.setting
        return patch.object(ui, 'setting', lambda name, default='': value if name == 'UI' else original(name, default))

    def test_serves_web_export_when_present(self):
        self.build()
        with self.ui_setting(''):
            result = self.client.get('/')
        self.assertEqual(result.status_code, 200)
        self.assertIn('next studio export', result.text)
        self.assertEqual(result.headers['cache-control'], 'no-cache')

    def test_job_query_still_served_by_web_export(self):
        self.build()
        with self.ui_setting(''):
            result = self.client.get('/', params={'job': 'a' * 32})
        self.assertIn('next studio export', result.text)

    def test_legacy_override_wins_even_when_export_present(self):
        self.build()
        for value in ('legacy', 'LEGACY', ' legacy '):
            with self.subTest(value=value), self.ui_setting(value):
                result = self.client.get('/')
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.text, self.legacy)

    def test_falls_back_to_legacy_without_a_build(self):
        with self.ui_setting(''):
            result = self.client.get('/')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.text, self.legacy)

    def test_legacy_assets_and_api_routes_unchanged(self):
        self.build()
        with self.ui_setting(''):
            self.assertEqual(self.client.get('/static/app.js').status_code, 200)
            self.assertEqual(self.client.get('/health').json()['status'], 'ok')
            self.assertEqual(self.client.get('/jobs/' + 'f' * 32).status_code, 404)
            self.assertEqual(self.client.get('/_next/static/missing.js').status_code, 404)

    def test_export_mounts_point_at_web_out(self):
        mounts = {route.path: route for route in ui.app.routes if hasattr(route, 'app') and hasattr(route.app, 'directory')}
        for path in ('/runs', '/static', '/_next', '/ui'):
            self.assertIn(path, mounts)
        self.assertEqual(Path(mounts['/_next'].app.directory), config.ROOT / 'web' / 'out' / '_next')
        self.assertEqual(Path(mounts['/ui'].app.directory), config.ROOT / 'web' / 'out' / 'ui')


if __name__ == '__main__':
    unittest.main()

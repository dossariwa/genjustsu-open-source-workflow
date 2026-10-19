"""No network or generation: exercise credit gates and interruption recovery."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import dreamina_bridge as bridge


MODE = {
    'name': 'm2v',
    'vipRequired': False,
    'vipResolutions': [],
    'flags': [{'flag': '--resolution', 'values': ['720P', '1080P']},
              {'flag': '--ratio', 'values': ['16:9', '9:16', '1:1']},
              {'flag': '--duration', 'values': ['4', '5', '6']},
              {'flag': '--count', 'min': 1, 'max': 1}],
    'references': {'min': 1, 'max': 4, 'types': [
        {'mediaType': 'video', 'min': 0, 'max': 2},
        {'mediaType': 'image', 'min': 0, 'max': 2}]},
}
GEOMETRY = {'duration': 5, 'width': 960, 'height': 540}


class FakeBridge(bridge.DreaminaCanvasBridge):
    def __init__(self, folder):
        super().__init__(folder, status=lambda message: None)
        self.calls = []
        self.fail_run = False
        self.quote_diff = False
        self.operation = {'state': 'running', 'submission': {'state': 'in_progress'}, 'resources': []}

    def _preflight(self, model):
        return {'version': '1.0.3'}, {'region': 'sg', 'environment': 'prod'}, 'canonical-video', copy.deepcopy(MODE), {}

    def _call(self, args, **kwargs):
        self.calls.append(list(args))
        command = args[:2]
        if command == ['auth', 'status']:
            data = {'loggedIn': True, 'region': 'sg', 'environment': 'prod'}
        elif command == ['auth', 'account']:
            data = {'isVip': False}
        elif command == ['canvas', 'create']:
            data = {'project': {'projectId': self.state['project_id'], 'webUrl': 'https://example.org/canvas'}}
        elif command == ['resource', 'upload']:
            data = {'resourceId': args[args.index('--resource-id') + 1], 'mediaType': args[args.index('--type') + 1]}
        elif command == ['node', 'create']:
            data = {}
        elif command == ['node', 'show']:
            data = {'nodes': [{'nodeId': self.state['node_id'], 'result': 'FOUND', 'node': {'generation': {
                'prompt': self.state['prompt'], 'mode': 'm2v', 'model': self.state['model'],
                'resolution': self.state['resolution'], 'ratio': self.state['aspect_ratio'],
                'durationSeconds': self.state['duration'], 'outputCount': 1,
                'references': [{'kind': 'resource', 'id': a['resource_id']} for a in self.state['assets']],
            }}}]}
        elif command == ['node', 'quote']:
            data = {'items': [{'nodeId': self.state['node_id'], 'maxCredits': 12,
                               'generationDiff': [{'fieldPath': 'prompt'}] if self.quote_diff else []}],
                    'totalMaxCredits': 12, 'confirmable': True}
        elif command == ['node', 'confirm']:
            data = {'creditConfirmationToken': 'SECRET-TOKEN-DO-NOT-PERSIST'}
        elif command == ['node', 'run']:
            saved = json.loads((self.folder / bridge.STATE_FILE).read_text())
            if not saved['submit_attempted'] or saved['status'] != 'submitting' or saved['submit_id'] != args[args.index('--submit-id') + 1]:
                raise AssertionError('Submission identity was not durably saved before spending.')
            if self.fail_run:
                raise bridge.RecoveryRequired('simulated lost response')
            data = {'items': [{'nodeId': self.state['node_id'], 'submitId': self.state['submit_id'], 'state': 'ACCEPTED'}]}
        elif command == ['operation', 'wait']:
            data = dict(self.operation, operationRef=self.state['submit_id'])
        elif command == ['resource', 'get']:
            data = {'type': 'video', 'status': 'success'}
        elif command == ['resource', 'download']:
            output = Path(args[args.index('--output') + 1])
            output.write_bytes(self.download_bytes)
            data = {'path': str(output), 'size': output.stat().st_size, 'sha256': bridge._digest(output)}
        else:
            raise AssertionError('Unexpected command: ' + repr(args))
        return {'ok': True, 'data': data}


class DreaminaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        (self.folder / 'audio-manifest.json').write_text('{}')
        (self.folder / 'seedance-input.mp4').write_bytes(b'reviewed video with embedded audio')
        self.reference = self.folder / 'reference.png'
        self.reference.write_bytes(b'identity')
        self.gate = patch('mask_review.require_approved').start()
        self.addCleanup(patch.stopall)
        patch('dreamina_bridge._geometry', return_value=GEOMETRY).start()
        self.bridge = FakeBridge(self.folder)

    def submit(self, ceiling=None):
        return self.bridge.submit_draft('The exact approved prompt. @Video1', self.reference, credit_ceiling=ceiling)

    def test_quote_cannot_spend_and_keeps_recovery_identity(self):
        with self.assertRaises(bridge.CreditApprovalRequired) as caught:
            self.submit()
        self.assertEqual(caught.exception.minimum_credit_ceiling, 12)
        self.assertFalse(any(args[:2] == ['node', 'run'] for args in self.bridge.calls))
        state = json.loads((self.folder / bridge.STATE_FILE).read_text())
        self.assertEqual(state['state'], 'awaiting_credit_approval')
        self.assertFalse(state['submit_attempted'])
        self.assertRegex(state['node_id'], r'^node_[0-9abcdefghjkmnpqrstvwxyz]{10}$')
        self.assertEqual((self.folder / bridge.STATE_FILE).stat().st_mode & 0o777, 0o600)

    def test_approved_run_preserves_exact_prompt_and_never_saves_token(self):
        with self.assertRaises(bridge.CreditApprovalRequired):
            self.submit()
        original = json.loads((self.folder / bridge.STATE_FILE).read_text())
        ident = self.bridge.resume_approved(12)
        self.assertEqual(ident, original['submit_id'])
        create = next(args for args in self.bridge.calls if args[:3] == ['node', 'create', 'video'])
        self.assertEqual(create[create.index('--prompt') + 1], 'The exact approved prompt. @Video1')
        self.assertEqual(create[create.index('--mode') + 1], 'm2v')
        self.assertNotIn('--run', create)
        self.assertEqual(sum(args[:2] == ['node', 'run'] for args in self.bridge.calls), 1)
        self.assertGreaterEqual(self.gate.call_count, 3)
        for path in self.folder.glob('*.json'):
            self.assertNotIn('SECRET-TOKEN', path.read_text())

    def test_insufficient_ceiling_never_runs(self):
        with self.assertRaises(bridge.CreditApprovalRequired):
            self.submit(11)
        self.assertFalse(any(args[:2] in (['node', 'confirm'], ['node', 'run']) for args in self.bridge.calls))

    def test_lost_submit_response_never_replays_paid_command(self):
        self.bridge.fail_run = True
        with self.assertRaises(bridge.RecoveryRequired):
            self.submit(12)
        saved = json.loads((self.folder / bridge.STATE_FILE).read_text())
        self.assertEqual(saved['state'], 'uncertain')
        resumed = FakeBridge(self.folder)
        self.assertEqual(resumed.submit_draft(saved['prompt'], self.reference, credit_ceiling=12), saved['submit_id'])
        self.assertEqual(resumed.calls, [])
        resumed.operation = {'state': 'unknown', 'submission': {'state': 'absent'}, 'resources': []}
        with self.assertRaises(bridge.RecoveryRequired):
            resumed.collect_result(saved['submit_id'])
        self.assertTrue(all(args[:2] in (['auth', 'status'], ['operation', 'wait']) for args in resumed.calls))

    def test_changed_identity_cannot_use_previously_approved_credit(self):
        with self.assertRaises(bridge.CreditApprovalRequired):
            self.submit()
        self.reference.write_bytes(b'changed identity')
        with self.assertRaises(ValueError):
            self.bridge.resume_approved(12)
        self.assertFalse(any(args[:2] == ['node', 'run'] for args in self.bridge.calls))

    def test_quote_generation_mutation_blocks_submit(self):
        self.bridge.quote_diff = True
        with self.assertRaises(bridge.DreaminaError):
            self.submit(12)
        self.assertFalse(any(args[:2] == ['node', 'run'] for args in self.bridge.calls))

    def test_video_identity_is_an_ordered_video_reference_without_conversion(self):
        video = self.folder / 'identity.mov'
        video.write_bytes(b'identity video')
        self.bridge.submit_draft('Use first video timing, second video appearance only.', video, credit_ceiling=12)
        self.assertEqual([asset['type'] for asset in self.bridge.state['assets']], ['video', 'video'])
        self.assertEqual(self.bridge.state['assets'][1]['path'], str(video.resolve()))
        self.assertEqual(self.bridge.state['mode'], 'm2v')

    def test_empty_completed_resources_are_not_success(self):
        ident = self.submit(12)
        self.bridge.operation = {'state': 'succeeded', 'resources': []}
        with self.assertRaises(bridge.RecoveryRequired):
            self.bridge.collect_result(ident)
        self.assertFalse((self.folder / 'final-preview.mp4').exists())

    def test_collection_is_read_only_and_restores_final_audio(self):
        import av
        import numpy as np
        source = self.folder / 'fake-result.mp4'
        with av.open(str(source), 'w') as output:
            stream = output.add_stream('libx264', rate=24)
            stream.width = stream.height = 32
            stream.pix_fmt = 'yuv420p'
            frame = av.VideoFrame.from_ndarray(np.zeros((32, 32, 3), dtype=np.uint8), format='rgb24')
            for packet in stream.encode(frame):
                output.mux(packet)
            for packet in stream.encode():
                output.mux(packet)
        ident = self.submit(12)
        self.bridge.download_bytes = source.read_bytes()
        self.bridge.operation = {'state': 'succeeded', 'resources': [{'resourceId': 'result-id', 'state': 'succeeded'}]}
        self.bridge.calls.clear()
        def finish(generated, folder):
            final = folder / 'final-preview.mp4'
            final.write_bytes(b'original audio restored')
            return final
        with patch('dreamina_bridge.finish_preview', side_effect=finish) as restore:
            final = self.bridge.collect_result(ident)
        self.assertEqual(final.read_bytes(), b'original audio restored')
        self.assertEqual((self.folder / 'draft_final.mp4').read_bytes(), final.read_bytes())
        restore.assert_called_once()
        self.assertFalse(any(args[:2] in (['node', 'run'], ['node', 'create']) for args in self.bridge.calls))
        self.assertEqual(self.bridge.state['status'], 'completed')

    def test_interrupted_preparation_resumes_only_to_quote_without_spending(self):
        original_call = self.bridge._call
        def interrupted_upload(args, **kwargs):
            if args[:2] == ['resource', 'upload']:
                raise bridge.DreaminaError('simulated upload interruption')
            return original_call(args, **kwargs)
        with patch.object(self.bridge, '_call', side_effect=interrupted_upload):
            with self.assertRaises(bridge.DreaminaError):
                self.submit(100)
        saved = json.loads((self.folder / bridge.STATE_FILE).read_text())
        self.assertEqual(saved['status'], 'preparing')
        self.assertFalse(saved['submit_attempted'])
        # Even an old ceiling in persisted state must not authorize resume spending.
        saved['approved_credit_ceiling'] = 100
        bridge._atomic_json(self.folder / bridge.STATE_FILE, saved)
        with self.assertRaises(bridge.CreditApprovalRequired) as caught:
            self.bridge.resume_preparation()
        self.assertEqual(caught.exception.minimum_credit_ceiling, 12)
        self.assertEqual(self.bridge.state['submit_id'], saved['submit_id'])
        self.assertEqual(self.bridge.state['status'], 'awaiting_credit_approval')
        self.assertFalse(any(args[:2] in (['node', 'confirm'], ['node', 'run']) for args in self.bridge.calls))

    def test_preparation_resume_rejects_already_attempted_generation(self):
        self.submit(12)
        self.bridge.calls.clear()
        with self.assertRaises(bridge.RecoveryRequired):
            self.bridge.resume_preparation()
        self.assertEqual(self.bridge.calls, [])

    def test_hd_never_silently_starts_fresh_generation(self):
        with self.assertRaises(ValueError):
            self.bridge.submit_hd_upgrade()
        with self.assertRaisesRegex(bridge.DreaminaError, 'no verified video HD'):
            self.bridge.submit_hd_upgrade(approved=True)
        self.assertEqual(self.bridge.calls, [])

    def test_mask_approval_failure_happens_before_any_provider_operation(self):
        self.gate.side_effect = ValueError('Review required')
        with self.assertRaises(ValueError):
            self.submit(12)
        self.assertEqual(self.bridge.calls, [])

    def test_unsupported_duration_is_rejected_before_paid_work(self):
        with self.assertRaises(bridge.DreaminaError):
            bridge._video_parameters(MODE, dict(GEOMETRY, duration=8))
        chosen = bridge._video_parameters(MODE, dict(GEOMETRY, duration=5.3))
        self.assertAlmostEqual(chosen['last_frame_hold_seconds'], .3)
        self.assertEqual(chosen['resolution'], '720P')

    def test_catalog_reference_limits_include_prepared_video(self):
        mode = copy.deepcopy(MODE)
        mode['references']['types'][0]['max'] = 1
        with self.assertRaises(bridge.DreaminaError):
            bridge._validate_references(mode, [{'type': 'video'}, {'type': 'video'}])

    def test_known_resolution_entitlement_blocks_before_canvas_or_upload(self):
        mode = copy.deepcopy(MODE)
        mode['vipResolutions'] = ['720p']
        calls = []
        def read_only(args, **kwargs):
            calls.append(args)
            if args == ['--version']:
                data = {'version': '1.0.3'}
            elif args == ['schema']:
                data = {}
            elif args == ['auth', 'status']:
                data = {'loggedIn': True, 'region': 'sg', 'environment': 'prod'}
            elif args[:2] == ['model', 'find']:
                data = {'items': [{'model': 'seedance_2.0_mini', 'modes': [mode]}]}
            elif args == ['auth', 'account']:
                data = {'isVip': False}
            else:
                raise AssertionError('Unexpected mutation: ' + repr(args))
            return {'ok': True, 'data': data}
        actual = bridge.DreaminaCanvasBridge(self.folder, status=lambda message: None)
        with patch.object(actual, '_call', side_effect=read_only), patch('dreamina_bridge._command', return_value={}):
            with self.assertRaisesRegex(bridge.DreaminaError, 'Advertised VIP requirement unmet'):
                actual.submit_draft('Approved prompt', self.reference, credit_ceiling=100)
        self.assertFalse((self.folder / bridge.STATE_FILE).exists())
        self.assertTrue(all(args[0] in ('--version', 'schema', 'auth', 'model') for args in calls))

    def test_resumed_preparation_rechecks_membership_before_upload(self):
        with self.assertRaises(bridge.CreditApprovalRequired):
            self.submit()
        self.bridge.state['model_mode']['vipResolutions'] = ['720p']
        self.bridge.state['canvas_created'] = False
        self.bridge._save()
        self.bridge.calls.clear()
        with self.assertRaisesRegex(bridge.DreaminaError, 'Advertised VIP requirement unmet'):
            self.bridge.resume_approved(100)
        self.assertTrue(all(args[0] == 'auth' for args in self.bridge.calls))


class EntitlementTests(unittest.TestCase):
    def test_resolution_requirement_overrides_model_level_false(self):
        mode = {'vipRequired': False, 'vipResolutions': ['720p']}
        status = bridge.entitlement_status(mode, '720P', {'isVip': False})
        self.assertTrue(status['required'])
        self.assertTrue(status['blocked'])
        self.assertIn('Server admission is untested', status['detail'])

    def test_unselected_vip_resolution_does_not_block(self):
        status = bridge.entitlement_status({'vipRequired': False, 'vipResolutions': ['1080p']}, '720p', {'isVip': False})
        self.assertFalse(status['required'])
        self.assertFalse(status['blocked'])

    def test_missing_membership_fields_do_not_mean_free_access(self):
        status = bridge.entitlement_status({}, '720p', {})
        self.assertIsNone(status['required'])
        self.assertIsNone(status['account_is_vip'])
        self.assertIn('not fully advertised', status['detail'])
        known_requirement = bridge.entitlement_status({'vipRequired': True}, '720p', {})
        self.assertFalse(known_requirement['blocked'])
        self.assertIn('membership is unavailable', known_requirement['detail'])

    def test_vip_membership_does_not_claim_server_admission(self):
        status = bridge.entitlement_status({'vipRequired': True}, '720p', {'isVip': True})
        self.assertFalse(status['blocked'])
        self.assertIn('server admission remains untested', status['detail'])


class CLIEnvelopeTests(unittest.TestCase):
    def test_auth_error_from_stderr_is_actionable_and_sanitized(self):
        error = {'ok': False, 'error': {'code': 'cli.authentication_required', 'requiredAction': 'login',
                                       'message': 'PRIVATE-KEY-MUST-NOT-APPEAR'}}
        result = Mock(returncode=11, stdout='', stderr=json.dumps(error))
        with patch('dreamina_bridge.subprocess.run', return_value=result):
            with self.assertRaises(bridge.DreaminaError) as caught:
                bridge.DreaminaCanvasBridge()._call(['auth', 'account'])
        self.assertIn('cli.authentication_required', str(caught.exception))
        self.assertIn('login', str(caught.exception))
        self.assertNotIn('PRIVATE-KEY', str(caught.exception))

    def test_stderr_resume_envelope_preserves_partial_result_despite_junk_stdout(self):
        error = {'ok': False, 'error': {'code': 'cli.operation_incomplete', 'requiredAction': 'resume'},
                 'partialData': {'operationRef': 'saved-operation', 'state': 'running',
                                 'resources': [{'resourceId': 'saved-resource', 'state': 'pending'}]}}
        result = Mock(returncode=20, stdout='unexpected non-JSON output', stderr=json.dumps(error))
        with patch('dreamina_bridge.subprocess.run', return_value=result):
            observed = bridge.DreaminaCanvasBridge()._call(['operation', 'wait', 'saved-operation'], allow_error=True)
        self.assertEqual(observed, error)

    def test_failed_exit_cannot_become_success_even_when_allow_error_is_true(self):
        result = Mock(returncode=1, stdout=json.dumps({'ok': True, 'data': {'state': 'succeeded'}}), stderr='PRIVATE-RAW-OUTPUT')
        with patch('dreamina_bridge.subprocess.run', return_value=result):
            with self.assertRaisesRegex(bridge.DreaminaError, 'exited unsuccessfully') as caught:
                bridge.DreaminaCanvasBridge()._call(['operation', 'wait', 'saved-operation'], allow_error=True)
        self.assertNotIn('PRIVATE', str(caught.exception))

    def test_successful_exit_with_junk_stdout_cannot_trust_stderr_success(self):
        result = Mock(returncode=0, stdout='junk', stderr=json.dumps({'ok': True, 'data': {}}))
        with patch('dreamina_bridge.subprocess.run', return_value=result):
            with self.assertRaisesRegex(bridge.DreaminaError, 'invalid JSON'):
                bridge.DreaminaCanvasBridge()._call(['auth', 'status'])

    def test_unsafe_error_codes_and_actions_are_not_displayed(self):
        message = bridge._safe_error({'error': {'code': 'https://example.org?token=PRIVATE', 'requiredAction': 'PRIVATE-KEY'}})
        self.assertEqual(message, 'Dreamina CLI: cli.invalid_response')


if __name__ == '__main__':
    unittest.main()

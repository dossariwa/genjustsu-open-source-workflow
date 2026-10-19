"""Offline coverage of OpenArt quotes, identity preservation and recovery.

The injected transport never accesses credentials, the network or user credits.
"""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import openart_bridge as bridge


SCHEMA = {'type': 'object', 'properties': {
    'prompt': {'type': 'string', 'maxLength': 30000},
    'videoCount': {'type': 'integer', 'minimum': 1, 'maximum': 8},
    'duration': {'type': 'integer', 'minimum': 4, 'maximum': 30},
    'aspectRatio': {'type': 'string', 'enum': ['16:9', '4:3', '1:1', '3:4', '9:16', '21:9', 'adaptive']},
    'resolution': {'type': 'string', 'const': '480p'},
    'generateAudio': {'type': 'boolean'}, 'autoEnhancePrompt': {'type': 'boolean'},
    'visualReferences': {'type': 'array', 'minItems': 1, 'items': {
        'type': 'object', 'properties': {key: {'type': 'string'} for key in ('type', 'id', 'url', 'label')},
        'required': ['type', 'id', 'url', 'label']}},
}, 'required': ['visualReferences'], 'additionalProperties': False}
GEOMETRY = {'duration': 5, 'width': 960, 'height': 540}


class FakeTransport:
    def __init__(self, folder):
        self.folder = folder
        self.calls = []
        self.uploads = []
        self.resolved = []
        self.assets = {}
        self.credits = 4000
        self.cost = 300
        self.schema = copy.deepcopy(SCHEMA)
        self.element_types = ['image', 'video', 'audio']
        self.account_id = 'account-one'
        self.project_id = 'project-one'
        self.workspace = None
        self.fail_submit = False
        self.fail_upload = False
        self.quote_mutation = False
        self.reference_mutation = False
        self.before_generate = None
        self.result = {'historyId': 'history-one', 'status': 'RUNNING', 'pollAfterSeconds': 10}

    def call(self, tool, arguments):
        self.calls.append((tool, copy.deepcopy(arguments)))
        if tool == 'openart_account_get':
            result = {'user': {'uid': self.account_id, 'email': 'private@example.test'}, 'credits': self.credits, 'plan': 'Starter'}
            if self.workspace:
                result['workspace'] = self.workspace
            return result
        if tool == 'openart_model_list':
            return {'models': [{'id': bridge.MODEL, 'modes': {'video': [
                {'mode': bridge.MODE, 'elementTypes': self.element_types}]}}]}
        if tool == 'openart_model_form_get':
            return {'model': bridge.MODEL, 'mode': bridge.MODE, 'media': 'video', 'jsonSchema': self.schema}
        if tool == 'openart_project_list':
            return {'items': [{'id': self.project_id, 'canGenerate': True, 'isDefault': True}], 'hasMore': False}
        if tool == 'openart_model_cost':
            config = {key: value for key, value in arguments['params'].items()
                      if key in ('resolution', 'duration', 'aspectRatio', 'videoCount', 'generateAudio')}
            if self.quote_mutation:
                config['resolution'] = '1080p'
            return {'currency': 'credits', 'balance': self.credits, 'items': [{
                'model': arguments['model'], 'mode': arguments['mode'], 'totalCredits': self.cost,
                'quantity': 1, 'config': config, 'affordable': self.credits >= self.cost}]}
        if tool == 'openart_generate_video':
            state = json.loads((self.folder / bridge.STATE_FILE).read_text())
            if not state['submit_attempted'] or state['status'] != 'submitting':
                raise AssertionError('The spend was attempted before durable uncertainty protection.')
            if self.before_generate:
                self.before_generate(arguments)
            if self.fail_submit:
                raise RuntimeError('SECRET provider error https://example.test?token=PRIVATE')
            return {'historyId': 'history-one', 'status': 'PENDING'}
        if tool == 'openart_creation_get':
            return copy.deepcopy(self.result)
        raise AssertionError('Unexpected tool ' + tool)

    def upload(self, path, media_type, label, project_id=None):
        self.uploads.append((str(path), media_type, label, project_id))
        if self.fail_upload:
            raise RuntimeError('PRIVATE upload failure')
        ident = 'upload-' + str(len(self.assets) + 1)
        ref = {'id': ident, 'type': media_type, 'label': label,
               'url': 'https://cdn.openart.ai/' + ident + '?signature=PRIVATE'}
        self.assets[ident] = copy.deepcopy(ref)
        return ref

    def resolve_reference(self, upload_id, project_id):
        self.resolved.append((upload_id, project_id))
        ref = copy.deepcopy(self.assets[upload_id])
        if self.reference_mutation:
            ref['id'] = 'different-upload'
        return ref

    def download(self, url, target):
        Path(target).write_bytes(self.download_bytes)


class OpenArtTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        (self.folder / 'seedance-input.mp4').write_bytes(b'reviewed video and embedded guidance')
        (self.folder / 'audio-manifest.json').write_text('{}')
        self.reference = self.folder / 'identity.png'
        self.reference.write_bytes(b'reviewed identity')
        self.transport = FakeTransport(self.folder)
        self.bridge = bridge.OpenArtBridge(self.folder, status=lambda text: None, transport=self.transport)
        self.gate = patch('mask_review.require_approved').start()
        patch('openart_bridge._geometry', return_value=GEOMETRY).start()
        patch('openart_bridge.setting', side_effect=lambda key, default='': default).start()
        self.addCleanup(patch.stopall)

    def submit(self, ceiling=None):
        return self.bridge.submit_draft('Exact reviewed prompt. Prepared source controls timing.', self.reference, credit_ceiling=ceiling)

    def assert_no_generation(self):
        self.assertFalse(any(tool == 'openart_generate_video' for tool, _ in self.transport.calls))

    def test_readiness_only_reads_account_and_model_contract(self):
        result = self.bridge.readiness()
        self.assertEqual(result['plan'], 'Starter')
        self.assertEqual(result['credits'], 4000)
        self.assertEqual(result['model'], bridge.MODEL)
        self.assertTrue(result['schema_verified'])
        self.assertFalse(result['live_generation_verified'])
        self.assertEqual(self.transport.uploads, [])
        self.assertEqual([tool for tool, _ in self.transport.calls],
                         ['openart_account_get', 'openart_model_list', 'openart_model_form_get'])
        self.assertNotIn('email', json.dumps(result))

    def test_unsupported_video_reference_contract_blocks_before_upload(self):
        self.transport.element_types = ['image']
        with self.assertRaisesRegex(bridge.OpenArtError, 'video and image references'):
            self.submit(300)
        self.assertEqual(self.transport.uploads, [])
        self.assert_no_generation()

    def test_other_model_or_resolution_override_is_rejected_explicitly(self):
        for key, value in [('OPENART_DRAFT_MODEL', 'different-model'), ('OPENART_DRAFT_RESOLUTION', '1080p')]:
            with self.subTest(key=key), patch('openart_bridge.setting', side_effect=lambda name, default='', key=key, value=value: value if name == key else default):
                with self.assertRaisesRegex(bridge.OpenArtError, 'Restore OPENART_DRAFT_MODEL'):
                    self.bridge.readiness()
        self.assertEqual(self.transport.calls, [])

    def test_unknown_credit_balance_is_not_reported_ready(self):
        self.transport.credits = None
        result = self.bridge.readiness()
        self.assertIsNone(result['credits'])
        self.assertTrue(result['generation_blockers'])

    def test_live_output_count_drift_blocks_before_upload(self):
        self.transport.schema['properties']['videoCount']['minimum'] = 2
        with self.assertRaisesRegex(bridge.OpenArtError, 'one output'):
            self.submit(4000)
        self.assertEqual(self.transport.uploads, [])
        self.assert_no_generation()

    def test_resume_rechecks_prompt_limits_before_resolving_or_spending(self):
        with self.assertRaises(bridge.CreditApprovalRequired):
            self.submit()
        self.transport.schema['properties']['prompt']['maxLength'] = 2
        with self.assertRaisesRegex(bridge.OpenArtError, 'no longer fit'):
            self.bridge.resume_approved(4000)
        self.assertEqual(self.transport.resolved, [])
        self.assert_no_generation()

    def test_mask_review_is_required_before_any_provider_read_or_upload(self):
        self.gate.side_effect = ValueError('Full visual review required')
        with self.assertRaises(ValueError):
            self.submit(300)
        self.assertEqual(self.transport.calls, [])
        self.assertEqual(self.transport.uploads, [])

    def test_no_ceiling_stops_at_quote_and_never_persists_urls(self):
        with self.assertRaises(bridge.CreditApprovalRequired) as caught:
            self.submit()
        self.assertEqual(caught.exception.minimum_credit_ceiling, 300)
        self.assert_no_generation()
        saved = json.loads((self.folder / bridge.STATE_FILE).read_text())
        self.assertEqual(saved['status'], 'awaiting_credit_approval')
        self.assertFalse(saved['submit_attempted'])
        self.assertEqual(saved['reference_labels'], ['Prepared source', 'Character 1 · identity.png'])
        self.assertEqual((self.folder / bridge.STATE_FILE).stat().st_mode & 0o777, 0o600)
        for path in self.folder.glob('*.json'):
            self.assertNotIn('PRIVATE', path.read_text())
            self.assertNotIn('https://', path.read_text())

    def test_approved_exact_quote_uses_saved_refs_and_embedded_video(self):
        with self.assertRaises(bridge.CreditApprovalRequired):
            self.submit()
        original = copy.deepcopy(self.bridge.state)
        ident = self.bridge.resume_approved(300)
        self.assertEqual(ident, original['submit_id'])
        self.assertEqual(len(self.transport.uploads), 2)
        self.assertEqual(len(self.transport.resolved), 2)
        generated = [args for tool, args in self.transport.calls if tool == 'openart_generate_video']
        self.assertEqual(len(generated), 1)
        call = generated[0]
        self.assertEqual(call['model'], bridge.MODEL)
        self.assertEqual(call['mode'], 'element2video')
        self.assertEqual(call['params']['resolution'], '480p')
        self.assertEqual(call['params']['videoCount'], 1)
        self.assertFalse(call['params']['autoEnhancePrompt'])
        self.assertEqual(call['params']['prompt'], original['prompt'])
        self.assertEqual([ref['type'] for ref in call['params']['visualReferences']], ['video', 'image'])
        self.assertTrue(all(item[3] == 'project-one' for item in self.transport.uploads))
        self.assertGreaterEqual(self.gate.call_count, 3)

    def test_video_identity_stays_video_and_keeps_order(self):
        reference = self.folder / 'identity.mov'
        reference.write_bytes(b'identity video')
        self.bridge.submit_draft('Use identity video appearance only.', reference, credit_ceiling=300)
        call = next(args for tool, args in self.transport.calls if tool == 'openart_generate_video')
        self.assertEqual([ref['type'] for ref in call['params']['visualReferences']], ['video', 'video'])
        self.assertEqual(self.bridge.state['assets'][1]['path'], str(reference.resolve()))

    def test_insufficient_ceiling_or_balance_never_spends(self):
        with self.assertRaises(bridge.CreditApprovalRequired):
            self.submit(299)
        self.assert_no_generation()
        self.transport.credits = 40
        with self.assertRaisesRegex(bridge.CreditApprovalRequired, 'balance is insufficient'):
            self.bridge.resume_approved(300)
        self.assert_no_generation()

    def test_changed_quote_settings_block_even_with_high_ceiling(self):
        self.transport.quote_mutation = True
        with self.assertRaisesRegex(bridge.OpenArtError, 'different output settings'):
            self.submit(4000)
        self.assert_no_generation()

    def test_incomplete_quote_is_rejected_before_spending(self):
        original = self.transport.call
        def missing_config(tool, arguments):
            result = original(tool, arguments)
            if tool == 'openart_model_cost':
                result['items'][0]['config'].pop('duration')
            return result
        with patch.object(self.transport, 'call', side_effect=missing_config):
            with self.assertRaisesRegex(bridge.OpenArtError, 'different output settings'):
                self.submit(4000)
        self.assert_no_generation()

    def test_quote_without_balance_is_rejected_before_spending(self):
        original = self.transport.call
        def missing_balance(tool, arguments):
            result = original(tool, arguments)
            if tool == 'openart_model_cost':
                result.pop('balance')
            return result
        with patch.object(self.transport, 'call', side_effect=missing_balance):
            with self.assertRaisesRegex(bridge.OpenArtError, 'current credit balance'):
                self.submit(4000)
        self.assert_no_generation()

    def test_changed_artifact_blocks_old_credit_approval(self):
        with self.assertRaises(bridge.CreditApprovalRequired):
            self.submit()
        self.reference.write_bytes(b'new identity')
        with self.assertRaises(ValueError):
            self.bridge.resume_approved(300)
        self.assert_no_generation()

    def test_resolved_upload_identity_must_match_saved_id(self):
        with self.assertRaises(bridge.CreditApprovalRequired):
            self.submit()
        self.transport.reference_mutation = True
        with self.assertRaisesRegex(bridge.OpenArtError, 'different uploaded reference'):
            self.bridge.resume_approved(300)
        self.assert_no_generation()

    def test_different_account_or_workspace_blocks_resumption(self):
        with self.assertRaises(bridge.CreditApprovalRequired):
            self.submit()
        self.transport.workspace = {'id': 'team-other'}
        with self.assertRaisesRegex(bridge.RecoveryRequired, 'workspace changed'):
            self.bridge.resume_approved(300)
        self.assert_no_generation()

    def test_lost_generate_response_never_replays(self):
        self.transport.fail_submit = True
        with self.assertRaises(bridge.RecoveryRequired) as caught:
            self.submit(300)
        self.assertNotIn('PRIVATE', str(caught.exception))
        state = json.loads((self.folder / bridge.STATE_FILE).read_text())
        self.assertEqual(state['state'], 'uncertain')
        self.transport.calls.clear()
        self.assertEqual(self.bridge.resume_approved(300), state['submit_id'])
        self.assertEqual(self.transport.calls, [])
        with self.assertRaisesRegex(bridge.RecoveryRequired, 'no confirmed history ID'):
            self.bridge.collect_result(state['submit_id'])
        self.assertEqual(self.transport.calls, [])

    def test_interrupted_upload_can_resume_to_quote_but_cannot_reuse_ceiling(self):
        self.transport.fail_upload = True
        with self.assertRaises(bridge.OpenArtError):
            self.submit(4000)
        saved = copy.deepcopy(self.bridge.state)
        self.transport.fail_upload = False
        with self.assertRaises(bridge.CreditApprovalRequired):
            self.bridge.resume_preparation()
        self.assertEqual(self.bridge.state['submit_id'], saved['submit_id'])
        self.assert_no_generation()

    def test_existing_legacy_generation_cannot_be_resubmitted(self):
        (self.folder / 'dreamina-state.json').write_text('{}')
        with self.assertRaisesRegex(bridge.RecoveryRequired, 'original provider'):
            self.submit(300)
        self.assertEqual(self.transport.calls, [])

    def test_preparation_resume_rejects_attempted_generation(self):
        self.submit(300)
        self.transport.calls.clear()
        with self.assertRaises(bridge.RecoveryRequired):
            self.bridge.resume_preparation()
        self.assertEqual(self.transport.calls, [])

    def test_completed_without_one_video_is_not_success(self):
        ident = self.submit(300)
        self.transport.result = {'historyId': 'history-one', 'status': 'COMPLETED', 'resources': []}
        with self.assertRaises(bridge.RecoveryRequired):
            self.bridge.collect_result(ident)
        self.assertFalse((self.folder / 'final-preview.mp4').exists())

    def test_collection_preserves_draft_and_restores_audio_without_mutations(self):
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
        ident = self.submit(300)
        self.transport.download_bytes = source.read_bytes()
        self.transport.result = {'historyId': 'history-one', 'status': 'COMPLETED', 'resources': [
            {'id': 'video-one', 'mediaType': 'video', 'url': 'https://cdn.openart.ai/video?signature=PRIVATE'}]}
        self.transport.calls.clear()
        def restore(generated, folder):
            final = folder / 'final-preview.mp4'
            final.write_bytes(b'complete original audio restored')
            return final
        with patch('openart_bridge.finish_preview', side_effect=restore) as finish:
            final = self.bridge.collect_result(ident)
        finish.assert_called_once()
        self.assertEqual(final.read_bytes(), b'complete original audio restored')
        self.assertEqual((self.folder / 'draft_final.mp4').read_bytes(), final.read_bytes())
        self.assert_no_generation()
        self.assertEqual(self.bridge.state['status'], 'completed')
        self.assertTrue(all(tool in ('openart_account_get', 'openart_project_list', 'openart_creation_get')
                            for tool, _ in self.transport.calls))
        for path in self.folder.glob('*.json'):
            self.assertNotIn('PRIVATE', path.read_text())

    def test_wrong_history_cannot_be_collected(self):
        ident = self.submit(300)
        self.transport.result['historyId'] = 'another-job'
        with self.assertRaisesRegex(bridge.OpenArtError, 'different generation history'):
            self.bridge.collect_result(ident)

    def test_hd_is_never_substituted_with_new_generation(self):
        with self.assertRaises(ValueError):
            self.bridge.submit_hd_upgrade()
        with self.assertRaisesRegex(bridge.OpenArtError, 'draft is preserved'):
            self.bridge.submit_hd_upgrade(approved=True)
        self.assertEqual(self.transport.calls, [])
        self.assertFalse(bridge.capabilities()['video_hd_supported'])

    def test_model_duration_rounding_preserves_audio_hold_disclosure(self):
        result = bridge._video_parameters(SCHEMA, dict(GEOMETRY, duration=5.3))
        self.assertEqual(result['duration'], 5)
        self.assertAlmostEqual(result['last_frame_hold_seconds'], .3)
        with self.assertRaises(bridge.OpenArtError):
            bridge._video_parameters(SCHEMA, dict(GEOMETRY, duration=31))


if __name__ == '__main__':
    unittest.main()

import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
import mask_review
import seedance_bridge
import workflow
import dreamina_bridge


class WorkflowTests(unittest.TestCase):
    def test_mask_changed_invalidates_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for name in mask_review.FILES:
                (folder / name).write_bytes(b'original')
            fingerprint = mask_review.fingerprint(folder)
            mask_review.review(folder, True, 'Entire clip reviewed', fingerprint)
            mask_review.require_approved(folder)
            (folder / 'mask.mp4').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                mask_review.require_approved(folder)
            with self.assertRaises(ValueError):
                mask_review.review(folder, True, 'stale', fingerprint)

    def test_original_source_change_invalidates_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for name in mask_review.FILES:
                (folder / name).write_bytes(b'original')
            mask_review.review(folder, True, 'Entire clip reviewed', mask_review.fingerprint(folder))
            (folder / 'upload.mp4').write_bytes(b'different original audio')
            with self.assertRaises(ValueError):
                mask_review.require_approved(folder)

    def test_legacy_submission_not_requeued(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'seedance-response.json').write_text('{}')
            with patch('mask_review.require_approved'), patch('subprocess.run') as call:
                with self.assertRaises((ValueError, RuntimeError)):
                    seedance_bridge.submit(folder, 'prompt', 'reference.png')
                call.assert_not_called()

    def test_cli_resume_collects_openart_history_without_new_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ident = 'a' * 32
            folder = root / 'runs' / ident
            folder.mkdir(parents=True)
            (folder / 'openart-state.json').write_text(json.dumps({'history_id': 'saved-history', 'status': 'submitted'}))
            with patch.object(workflow, 'ROOT', root), patch.object(workflow, 'load_env'), patch('seedance_bridge.wait_and_finish') as collect, patch('seedance_bridge.submit') as submit, patch('seedance_bridge.resume_approved') as approve:
                workflow.main(['resume', ident])
            collect.assert_called_once_with(folder, 'saved-history')
            submit.assert_not_called()
            approve.assert_not_called()

    def test_cli_resume_without_history_never_retries_uncertain_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ident = 'b' * 32
            folder = root / 'runs' / ident
            folder.mkdir(parents=True)
            (folder / 'openart-state.json').write_text('{"status":"uncertain"}')
            with patch.object(workflow, 'ROOT', root), patch.object(workflow, 'load_env'), patch('seedance_bridge.wait_and_finish') as collect, patch('seedance_bridge.submit') as submit:
                with self.assertRaises(SystemExit):
                    workflow.main(['resume', ident])
            collect.assert_not_called()
            submit.assert_not_called()

    def test_cli_prompt_is_frozen_once_openart_request_is_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ident = 'c' * 32
            folder = root / 'runs' / ident
            folder.mkdir(parents=True)
            (folder / 'openart-state.json').write_text('{"status":"awaiting_credit_approval"}')
            with patch.object(workflow, 'ROOT', root), patch.object(workflow, 'load_env'), patch('openai_helper.sample_video_frames') as sample, patch('openai_helper.generate_seedance_prompt') as prompt:
                with self.assertRaises(SystemExit):
                    workflow.main(['prompt', ident, '--reference', 'character.png'])
            sample.assert_not_called()
            prompt.assert_not_called()

    def test_legacy_provider_work_cannot_spend_through_new_facade(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'dreamina-state.json').write_text('{"submit_id":"legacy"}')
            with patch('openart_bridge.submit') as submit, patch('openart_bridge.resume_preparation') as prepare, patch('openart_bridge.resume_approved') as approve:
                for action in [lambda: seedance_bridge.submit(folder, 'prompt', 'reference.png'),
                               lambda: seedance_bridge.resume_preparation(folder),
                               lambda: seedance_bridge.resume_approved(folder, 240),
                               lambda: seedance_bridge.submit_hd(folder, approved=True)]:
                    with self.assertRaises(seedance_bridge.ProviderError):
                        action()
            submit.assert_not_called()
            prepare.assert_not_called()
            approve.assert_not_called()

    def test_legacy_collection_routes_only_to_original_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'dreamina-state.json').write_text('{"submit_id":"legacy"}')
            with patch('dreamina_bridge.wait_and_finish', return_value=folder / 'final-preview.mp4') as legacy, patch('openart_bridge.wait_and_finish') as active:
                result = seedance_bridge.wait_and_finish(folder, 'legacy', status=None)
            self.assertEqual(result, folder / 'final-preview.mp4')
            legacy.assert_called_once_with(folder, 'legacy', None)
            active.assert_not_called()

    def test_openart_response_and_state_allow_existing_generation_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'openart-state.json').write_text('{"provider":"openart","history_id":"accepted","submit_id":"request"}')
            (folder / 'seedance-response.json').write_text('{"provider":"openart","historyId":"accepted","requestId":"request"}')
            (folder / 'generation.json').write_text('{"provider":"openart","history_id":"accepted"}')
            with patch('openart_bridge.wait_and_finish', return_value=folder / 'final-preview.mp4') as active, patch('dreamina_bridge.wait_and_finish') as legacy:
                result = seedance_bridge.wait_and_finish(folder, 'accepted', status=None)
            self.assertEqual(result, folder / 'final-preview.mp4')
            active.assert_called_once_with(folder, 'accepted', None)
            legacy.assert_not_called()

    def test_old_response_cannot_be_reclassified_by_an_openart_state_file(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'openart-state.json').write_text('{"provider":"openart"}')
            (folder / 'seedance-response.json').write_text('{"requestId":"legacy"}')
            with patch('openart_bridge.submit') as active:
                with self.assertRaises(seedance_bridge.ProviderError):
                    seedance_bridge.submit(folder, 'prompt', 'reference.png')
            active.assert_not_called()

    def test_unsubmitted_legacy_draft_does_not_offer_new_credit_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'dreamina-state.json').write_text('{}')
            with patch('dreamina_bridge.wait_and_finish', side_effect=dreamina_bridge.CreditApprovalRequired(12)):
                with self.assertRaisesRegex(seedance_bridge.ProviderError, 'legacy spending cannot be resumed') as error:
                    seedance_bridge.wait_and_finish(folder, 'legacy')
            self.assertNotIsInstance(error.exception, seedance_bridge.CreditApprovalRequired)

    def test_unknown_saved_generation_never_falls_through_to_openart(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'generation.json').write_text('{"request_id":"old-provider"}')
            with patch('openart_bridge.submit') as active:
                with self.assertRaises(seedance_bridge.ProviderError):
                    seedance_bridge.submit(folder, 'prompt', 'reference.png')
            active.assert_not_called()

    def test_state_selection_and_hd_capability_remain_safe_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.assertEqual(seedance_bridge.state_filename(folder), 'openart-state.json')
            (folder / 'dreamina-state.json').write_text('{}')
            self.assertEqual(seedance_bridge.state_filename(folder), 'dreamina-state.json')
            (folder / 'openart-state.json').write_text('{}')
            self.assertEqual(seedance_bridge.state_filename(folder), 'openart-state.json')
            with patch('subprocess.run') as process:
                self.assertFalse(seedance_bridge.capabilities()['video_hd_supported'])
            process.assert_not_called()


if __name__ == '__main__':
    unittest.main()

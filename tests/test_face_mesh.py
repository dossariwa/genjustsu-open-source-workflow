import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
import mask_review
import dreamina_bridge


class FaceMeshTests(unittest.TestCase):
    def test_mesh_approval_tracks_overlay_and_audio_without_masks(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'workflow-mode.json').write_text('{"mode":"face_mesh"}')
            for name in ['upload.mp4', 'original.mp4', 'face-landmarks.json', 'composite-silent.mp4',
                         'seedance-input.mp4', 'audio-manifest.json', 'guidance-audio.wav']:
                (folder / name).write_bytes(b'test')
            mask_review.review(folder, True, 'Full mesh reviewed', mask_review.fingerprint(folder))
            mask_review.require_approved(folder)
            (folder / 'seedance-input.mp4').write_bytes(b'changed')
            with self.assertRaises(ValueError):
                mask_review.require_approved(folder)

    def test_mesh_submission_never_rebuilds_reviewed_input(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'workflow-mode.json').write_text('{"mode":"face_mesh"}')
            (folder / 'audio-manifest.json').write_text('{}')
            (folder / 'seedance-input.mp4').write_bytes(b'reviewed video with audio')
            reference = folder / 'reference.png'
            reference.write_bytes(b'identity')
            with patch('mask_review.require_approved'), patch('audio_workflow.prepare_seedance_video') as prepare:
                with patch.object(dreamina_bridge.DreaminaCanvasBridge, '_preflight', side_effect=dreamina_bridge.DreaminaError('Not signed in')):
                    with self.assertRaises(dreamina_bridge.DreaminaError):
                        dreamina_bridge.submit(folder, 'Remove all mesh lines and replace the subject including hair', reference)
                prepare.assert_not_called()

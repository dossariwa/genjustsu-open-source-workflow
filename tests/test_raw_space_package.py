"""Offline package checks: never import the upstream app or load model weights."""
import hashlib
import importlib.util
from io import BytesIO
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import zipfile

import av
import numpy as np
from PIL import Image

PACKAGE = Path(__file__).resolve().parents[1] / "spaces" / "sam3-raw"


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, PACKAGE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


raw = load_module("raw_space_endpoint", "raw_endpoint.py")
patcher = load_module("raw_space_patcher", "patch_space.py")


def write_video(path, count=3, fps=24):
    with av.open(str(path), "w") as output:
        stream = output.add_stream("libx264rgb", rate=fps)
        stream.width, stream.height, stream.pix_fmt = 16, 16, "rgb24"
        for index in range(count):
            frame = av.VideoFrame.from_ndarray(np.full((16, 16, 3), index % 255, dtype=np.uint8), format="rgb24")
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)


class RawSpacePackageTests(unittest.TestCase):
    def test_video_limit_accepts_8_seconds_rejects_next_frame_and_wrong_fps(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source.mp4"
            write_video(path, 192)
            self.assertEqual(raw.inspect_video(path), raw.VideoSpec(192, 16, 16))
            write_video(path, 193)
            with self.assertRaisesRegex(ValueError, "8 seconds"):
                raw.inspect_video(path)
            write_video(path, 3, fps=25)
            with self.assertRaisesRegex(ValueError, "24 fps"):
                raw.inspect_video(path)

    def test_nonconsecutive_timestamps_rejected_even_with_24_fps_metadata(self):
        frames = [SimpleNamespace(width=16, height=16, pts=pts, time_base=raw.Fraction(1, 24))
                  for pts in (0, 1, 3)]
        stream = SimpleNamespace(average_rate=raw.Fraction(24), duration=None)
        container = MagicMock()
        container.streams.video = [stream]
        container.decode.return_value = iter(frames)
        with tempfile.NamedTemporaryFile() as source, patch.object(av, "open") as opened:
            opened.return_value.__enter__.return_value = container
            with self.assertRaisesRegex(ValueError, "timestamps"):
                raw.inspect_video(source.name)

    def test_export_unions_masks_preserves_geometry_and_explicit_empty(self):
        spec = raw.VideoSpec(2, 5, 3)
        first = np.zeros((3, 5), np.float32)
        second = first.copy()
        first[0, 0], second[-1, -1] = 1, 1
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "masks.zip"
            raw.export_masks({0: {7: first, 11: second}, 1: {}}, spec, archive)
            with zipfile.ZipFile(archive) as zipped:
                self.assertEqual(zipped.namelist(), ["mask_000000.png", "mask_000001.png"])
                arrays = [np.asarray(Image.open(BytesIO(zipped.read(name)))) for name in zipped.namelist()]
            self.assertEqual(arrays[0].shape, (3, 5))
            self.assertEqual(set(np.unique(arrays[0])), {0, 255})
            self.assertEqual(arrays[0].sum(), 510)
            self.assertEqual(arrays[1].sum(), 0)

    def test_missing_frame_differs_from_empty_and_no_resize_or_overlay_guessing(self):
        spec = raw.VideoSpec(2, 5, 3)
        invalid = [({0: {}}, "Missing"), ({0: {}, 1: {}, 2: {}}, "extra"),
                   ({0: None, 1: {}}, "Invalid"),
                   ({0: {1: np.ones((5, 3))}, 1: {}}, "dimensions"),
                   ({0: {1: np.full((3, 5), .3)}, 1: {}}, "nonbinary"),
                   ({0: {1: np.full((3, 5), np.nan)}, 1: {}}, "nonbinary"),
                   ({0: {1: np.zeros((3, 5, 3))}, 1: {}}, "dimensions")]
        for masks, message in invalid:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temp:
                with self.assertRaisesRegex(ValueError, message):
                    raw.export_masks(masks, spec, Path(temp) / "masks.zip")

    def test_callback_passes_original_file_and_clears_stale_initial_masks(self):
        frames = [Image.new("RGB", (5, 3), (193, 11, 71)) for _ in range(2)]
        state = SimpleNamespace(video_frames=frames, video_fps=24, reset=MagicMock())
        init = MagicMock(return_value=(state, 0, 1, frames[0], "loaded"))

        def prompt(current, index, text):
            current.masks_by_frame = {0: {99: np.ones((3, 5))}}
            return None, "prompted", "person", current

        def propagate(current):
            self.assertEqual(current.masks_by_frame, {})
            current.masks_by_frame = {0: {}, 1: {1: np.ones((3, 5))}}
            yield current, "done", {}

        run = raw.make_segment_raw(lambda: state, init, prompt, propagate)
        with patch.object(raw, "inspect_video", return_value=raw.VideoSpec(2, 5, 3)):
            archive = Path(run("original-rgb.mp4", "person"))
        try:
            init.assert_called_once_with(state, "original-rgb.mp4", "text")
            self.assertEqual(frames[0].getpixel((0, 0)), (193, 11, 71))
            with zipfile.ZipFile(archive) as zipped:
                first = np.asarray(Image.open(BytesIO(zipped.read("mask_000000.png"))))
                self.assertEqual(first.sum(), 0)
            state.reset.assert_called_once()
        finally:
            archive.unlink()

    def test_duration_or_prompt_rejection_happens_before_model_callbacks(self):
        callbacks = [MagicMock() for _ in range(4)]
        run = raw.make_segment_raw(*callbacks)
        with patch.object(raw, "inspect_video", side_effect=ValueError("at most 8 seconds")):
            with self.assertRaisesRegex(ValueError, "8 seconds"):
                run("long.mp4", "person")
        with self.assertRaisesRegex(ValueError, "nonempty"):
            run("long.mp4", " , ")
        for callback in callbacks:
            callback.assert_not_called()

    def test_initial_frame_zero_does_not_cover_missing_propagation_frame_zero(self):
        frames = [Image.new("RGB", (5, 3)) for _ in range(2)]
        state = SimpleNamespace(video_frames=frames, video_fps=24, reset=MagicMock())

        def prompt(current, index, text):
            current.masks_by_frame = {0: {1: np.ones((3, 5))}}
            return None, "prompted", "person", current

        def propagate(current):
            current.masks_by_frame[1] = {}  # Actual missing frame 0, not an empty result.
            yield current, "done", {}

        run = raw.make_segment_raw(lambda: state, lambda *args: (state,), prompt, propagate)
        with patch.object(raw, "inspect_video", return_value=raw.VideoSpec(2, 5, 3)):
            with self.assertRaisesRegex(ValueError, "Missing"):
                run("original.mp4", "person")
        state.reset.assert_called_once()

    def test_changed_frame_count_or_rgb_geometry_rejected(self):
        for frames in ([Image.new("RGB", (5, 3))],
                       [Image.new("RGB", (3, 5))] * 2,
                       [Image.new("L", (5, 3))] * 2):
            with self.assertRaises(ValueError):
                raw.validate_frames(frames, raw.VideoSpec(2, 5, 3))

    def test_checksum_drift_aborts_without_output_or_fetching_weights(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(patcher, "urlopen") as network:
            output = Path(temp) / "bundle"
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                patcher.build_bundle(output, b"changed upstream source")
            self.assertFalse(output.exists())
            network.assert_not_called()

    def test_patcher_changes_only_two_anchors_and_bundle_refuses_overwrite(self):
        fixture = ("def load():\n" + patcher.TRIM_BLOCK + "\n" + patcher.LAUNCH + "\n").encode()
        lock, requirements = b"test-lock", b"test-requirements"
        metadata = dict(patcher.UPSTREAM, app_sha256=hashlib.sha256(fixture).hexdigest(),
                        dependency_lock_sha256=hashlib.sha256(lock).hexdigest(),
                        upstream_requirements_sha256=hashlib.sha256(requirements).hexdigest())
        with patch.object(patcher, "UPSTREAM", metadata), tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "bundle"
            for bad_lock, bad_requirements in ((b"changed", requirements), (lock, b"changed")):
                with self.assertRaisesRegex(ValueError, "dependency drift"):
                    patcher.build_bundle(output, fixture, bad_lock, bad_requirements)
                self.assertFalse(output.exists())
            patcher.build_bundle(output, fixture, lock, requirements)
            expected = fixture.decode().replace(patcher.TRIM_BLOCK, patcher.REJECT_BLOCK).replace(
                patcher.LAUNCH, patcher.REGISTER.rstrip())
            self.assertEqual((output / "app.py").read_text(), expected)
            self.assertIn("sdk_version: 5.49.1", (output / "README.md").read_text())
            self.assertTrue((output / "LICENSE").is_file())
            with self.assertRaisesRegex(ValueError, "already exists"):
                patcher.build_bundle(output, fixture, lock, requirements)


if __name__ == "__main__":
    unittest.main()

"""Cloud-only extension for the pinned merve SAM3 Space; no models at import.

SPDX-License-Identifier: Apache-2.0
This extension remains inference-unverified until its cloud output is reviewed.
"""
from fractions import Fraction
from io import BytesIO
from pathlib import Path
import tempfile
from typing import NamedTuple
import zipfile

import numpy as np
from PIL import Image

MAX_SECONDS = 8
FPS = 24
MAX_SIDE = 960


class VideoSpec(NamedTuple):
    frames: int
    width: int
    height: int


def inspect_video(video):
    """Decode, check timestamps and reject long input before model processing."""
    import av

    path = Path(video)
    if not path.is_file():
        raise ValueError("Supply an uploaded video file.")
    with av.open(str(path)) as container:
        if len(container.streams.video) != 1:
            raise ValueError("Supply exactly one video stream.")
        stream = container.streams.video[0]
        if stream.average_rate != Fraction(FPS):
            raise ValueError("Supply normalized constant 24 fps video.")
        if stream.duration is not None and stream.duration * stream.time_base > MAX_SECONDS:
            raise ValueError("This Space supports at most 8 seconds; truncation is forbidden.")
        expected_time = None
        dimensions = None
        count = 0
        for frame in container.decode(stream):
            count += 1
            if count > MAX_SECONDS * FPS:
                raise ValueError("This Space supports at most 8 seconds; truncation is forbidden.")
            size = (frame.width, frame.height)
            if min(size) <= 0 or max(size) > MAX_SIDE:
                raise ValueError("Video dimensions must be positive and at most 960 pixels per side.")
            if dimensions is not None and size != dimensions:
                raise ValueError("Video dimensions changed between frames.")
            dimensions = size
            if frame.pts is None or frame.time_base is None:
                raise ValueError("Video is missing frame timestamps.")
            timestamp = frame.pts * frame.time_base
            if expected_time is not None and timestamp != expected_time:
                raise ValueError("Video timestamps are not consecutive at 24 fps.")
            expected_time = timestamp + Fraction(1, FPS)
        if not count:
            raise ValueError("Video contains no frames.")
    return VideoSpec(count, *dimensions)


def validate_frames(frames, spec):
    """Upstream decoding may not resize, crop, drop or append source frames."""
    if len(frames) != spec.frames:
        raise ValueError("Video initialization changed the source frame count.")
    if any(frame.size != (spec.width, spec.height) or frame.mode != "RGB" for frame in frames):
        raise ValueError("Video initialization changed source geometry or RGB format.")


def export_masks(masks_by_frame, spec, archive):
    """Union actual binary object masks; missing output is never an empty mask."""
    if set(masks_by_frame) != set(range(spec.frames)):
        raise ValueError("Missing or extra frame results; no shortened or shifted masks are accepted.")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for index in range(spec.frames):
            masks = masks_by_frame[index]
            if not isinstance(masks, dict):
                raise ValueError(f"Invalid mask result for frame {index}.")
            merged = np.zeros((spec.height, spec.width), dtype=bool)
            for mask in masks.values():
                raw = np.asarray(mask)
                if raw.shape != merged.shape:
                    raise ValueError(f"Mask dimensions changed at frame {index}; resizing is forbidden.")
                if not np.isin(raw, (0, 1)).all():
                    raise ValueError(f"Frame {index} contains a nonbinary mask; overlays are forbidden.")
                merged |= raw.astype(bool)
            # An explicit empty dictionary is a valid all-zero detection result.
            # The workflow diagnoses it and retries on the original RGB input.
            buffer = BytesIO()
            Image.fromarray(merged.astype(np.uint8) * 255).save(buffer, format="PNG")
            zipped.writestr(f"mask_{index:06d}.png", buffer.getvalue())


def make_segment_raw(app_state, init_video_session, on_text_prompt, propagate_masks):
    """Bind the audited upstream callbacks without importing its model loader."""
    def segment_raw(video, text_prompt):
        if not isinstance(text_prompt, str) or not any(part.strip() for part in text_prompt.split(",")):
            raise ValueError("Supply a nonempty subject text prompt.")
        spec = inspect_video(video)
        state = app_state()
        archive = None
        try:
            state, *_ = init_video_session(state, video, "text")
            validate_frames(state.video_frames, spec)
            if state.video_fps is None or abs(state.video_fps - FPS) > 0.000001:
                raise ValueError("Upstream decoding changed the video frame rate.")
            # Input frames stay RGB, whether the caller supplies colored depth
            # or its original RGB fallback. Never construct masks from previews.
            _, _, _, state = on_text_prompt(state, 0, text_prompt)
            # Only propagation results count; an initial frame-0 prompt mask
            # must not conceal a missing propagation result or a vanished object.
            state.masks_by_frame = {}
            for update in propagate_masks(state):
                state = update[0]
            validate_frames(state.video_frames, spec)
            with tempfile.NamedTemporaryFile(prefix="sam3-raw-", suffix=".zip", delete=False) as handle:
                archive = Path(handle.name)
            export_masks(state.masks_by_frame, spec, archive)
            return str(archive)
        except BaseException:
            if archive is not None:
                archive.unlink(missing_ok=True)
            raise
        finally:
            state.reset()

    return segment_raw


def install_raw_endpoint(demo, app_state, init_video_session, on_text_prompt, propagate_masks):
    """Register File + Textbox -> File, keeping uploaded video bytes unchanged."""
    import gradio as gr

    run = make_segment_raw(app_state, init_video_session, on_text_prompt, propagate_masks)

    def segment_raw(video, text_prompt):
        try:
            return run(video, text_prompt)
        except ValueError as exc:
            raise gr.Error(str(exc)) from None
        except Exception:
            raise gr.Error("Cloud SAM processing failed; no valid aligned raw-mask archive was produced.") from None

    with demo:
        # File, rather than Video, avoids Gradio video transcoding/preprocessing.
        raw_video = gr.File(label="Input video", type="filepath", file_types=["video"], visible=False)
        raw_prompt = gr.Textbox(label="Subject text prompt", visible=False)
        raw_output = gr.File(label="Raw masks ZIP", visible=False)
        raw_button = gr.Button("Export raw masks", visible=False)
        raw_button.click(segment_raw, [raw_video, raw_prompt], raw_output,
                         api_name="segment_raw", concurrency_limit=1)

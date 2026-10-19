# Hugging Face raw SAM 3 masks

The application uses cloud Gradio calls; it never downloads depth or SAM model
weights locally. `HF_ACCESS_TOKEN` (or its `HF_TOKEN` alias) authenticates calls.

Setup on 2026-10-18 deployed the private
[`wosx/genjustsu-sam3-raw`](https://huggingface.co/spaces/wosx/genjustsu-sam3-raw)
Space on free ZeroGPU. Its `/segment_raw` schema is verified, and the project's
ignored `.env` selects it. The Space requires the owner's token for access.
No mask inference or media upload was performed during setup. The eight-second
limit below still applies.

Public API/source inspection on 2026-10-18 established:

- [Video Depth Anything source](https://huggingface.co/spaces/depth-anything/Video-Depth-Anything/blob/main/app.py)
  exposes `/infer_video_depth(input_video, max_len, target_fps, max_res, grayscale)`.
  Output 0 is the processed source; output 1 is colored depth. We send `-1`, `24`,
  `960`, `False` and preserve the downloaded depth file unchanged.
- [merve SAM 3 source](https://huggingface.co/spaces/merve/SAM3-video-segmentation/blob/main/app.py)
  retains raw masks in server-side Gradio state. Its public endpoints return
  previews/overlay playback, not a raw-mask ZIP. It also truncates inputs to eight
  seconds. `facebook/sam3` is a model repository, not a verified video inference
  endpoint. A model ID alone is not an API integration.
- [linoyts SAM 3 source](https://huggingface.co/spaces/linoyts/SAM3-Video/blob/main/app.py)
  also returns only a green overlay video.

The application intentionally refuses these overlay-only endpoints. Extracting
masks by guessing the overlay colors would contaminate subject edges and cannot
establish exact mask alignment. Doctor reports depth modes as unavailable until
a compatible endpoint is configured. The independent `face_mesh` preparation
mode remains available when its own dependencies are ready.

## Compatible endpoint contract

Configure a private or public Hugging Face Space that you control:

```ini
HF_SAM_SPACE=your-account/your-raw-sam3-space
HF_SAM_API_NAME=/segment_raw
# Optional alternate endpoint implementing exactly the same output contract:
HF_SAM_FALLBACK_SPACE=
HF_SAM_FALLBACK_API_NAME=
```

The application reads the live Gradio schema before inference. The endpoint must
have one Video or File parameter whose name contains `video`, one Textbox
parameter whose name contains `text`, `query`, or `prompt`, and a File output
whose label contains `mask`. Any other parameters must have defaults. The File
output must be a ZIP containing exactly one `mask_000000.png` per input frame,
starting at zero. PNGs must be full-size binary masks (0 background, 255 subject),
with no crop, scaling, skipped frames, overlays, or renamed ordering. Multiple
subject masks should be unioned into one frame mask on the server.

Every returned PNG is validated locally. The ZIP is bounded and paths are never
extracted directly. Frame count, dimensions and indexing must agree. Depth must
also preserve the normalized source's timestamps. Empty or nearly full depth
masks trigger a fresh segmentation of the original RGB video; the colored depth
is still composited unchanged through the new masks. Both attempts and the
fallback reason remain saved. Coverage statistics are diagnostics only. Full
visual review remains mandatory before submission.

## Reviewed cloud extension

The repository includes a checksum-guarded package in
[`spaces/sam3-raw`](../spaces/sam3-raw/README.md). It builds a small upload bundle
from a pinned upstream source revision without importing SAM, installing GPU
packages locally, or downloading model weights. Upstream source and dependency
hashes are checked before any output is written. License attribution is retained.

The endpoint accepts File input to preserve the uploaded video bytes. It checks
24 fps timestamps, full-size RGB frames and every propagation result, then
exports one binary PNG per frame. Explicit empty detections produce black masks;
missing frame results fail. Offline tests cover those distinctions, geometry,
timestamp and duration failures, and source drift. They do not establish cloud
inference quality.

**The initial endpoint supports at most 8 seconds (192 frames), while the main
workflow accepts up to 30 seconds.** Longer videos are rejected, never silently
trimmed. Raising the limit requires cloud capacity and full-length validation.

Follow the package's deployment procedure: obtain SAM 3 model approval, confirm
free ZeroGPU eligibility, build and review the bundle, create a private Space on
explicit `zero-a10g` hardware, and upload through a guarded commit. Do not fall
back to paid hardware or public visibility automatically. Keep credentials in
private Space secrets; never put them in source, arguments or logs.

Once the Space is running, configure `HF_SAM_SPACE` and `HF_SAM_API_NAME` and
validate its live schema with `inspect_endpoint()` before using it. Setup and
schema checks run no inference. A separate authorized generation and full-clip
visual review are still required to establish mask quality and supported limits.

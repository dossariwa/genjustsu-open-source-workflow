# Troubleshooting

Run `.venv/bin/python doctor.py --require-keys` first. It prints presence and readiness, never credential values, and makes no paid inference calls.

- **UI ready but generation blocked:** add this project's three keys privately, authenticate the local OpenArt CLI and resolve `byte-plus-seedance-2-5-draft` from its live model catalog. OpenArt connector login and CLI login are separate.
- **Upgraded account but CLI signed out:** complete the official CLI OAuth login with the upgraded account. Do not paste a browser token into `.env`; OpenArt does not require an API key here.
- **SAM raw masks unsupported:** the public demo returns overlays; configure a raw-PNG Space endpoint per `HF-RAW-MASKS.md`. Do not extract masks from overlay colors. The private SAM3 endpoint accepts at most 8 seconds and rejects longer clips.
- **Mask/mesh review pending:** review the full clip and guidance audio; artifact changes invalidate old approval. Sampled AI advice cannot approve it.
- **OpenArt awaiting credits:** inspect the saved quote, explicitly approve a ceiling, then continue the same saved request. A subscription or positive balance is not permission to spend during setup.
- **Interrupted or unknown generation:** collect the saved provider request ID. Never delete state to force a retry or start replacement work while the outcome is uncertain.
- **Video download rejected:** preserve the completed provider request; use the provider's result download and import the video in the UI for audio restoration if necessary. Never claim delivery without a downloaded and restored file.
- **1080p unavailable:** use only a verified completion/upscale contract tied to the draft and explicit HD approval. A new generation is not an upgrade. Existing Dreamina drafts retain the installed Canvas CLI's lack of video HD completion.
- **Missing Rubber Band:** install the CLI through your package manager. It preserves pitch-shift timing and corrects excessive STS duration drift.
- **Mesh worker missing:** run `bash setup-face-mesh.sh` with Python 3.12; verify `doctor.py --mesh`. The small model downloads on first use.
- **Audio differs:** `original` packet-copies the full source soundtrack. `elevenlabs_sts` deliberately creates a new mix; it cannot be byte-identical. Large video/audio duration mismatches are rejected instead of truncating source audio.

No callbacks, cloudflared, Replicate or Enhancor keys are required. Dreamina is needed only to collect older Dreamina jobs. Never paste keys or raw provider payloads into support messages.

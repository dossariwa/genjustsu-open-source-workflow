# Validation — OpenArt migration, 2026-10-18

Branch: `dev`. Local, uncommitted work in `/opt/Genjustsu-Open-Source-Workflow`. Python 3.12.15 on macOS ARM64. The existing HF, ElevenLabs and OpenAI configuration and private SAM3 Space are preserved. `.env` remains ignored and mode 0600; it now selects the official OpenArt CLI, Seedance 2.5 Draft and 480p. OAuth credentials remain in the CLI's private credential file, outside this repository.

## Current results

- `.venv/bin/python -m unittest discover -s tests`: **163 tests passed**. All inference, media uploads and generation are mocked. Coverage includes preparation/audio/raw masks, review hashes, legacy recovery, OpenArt exact model/schema and quote validation, account/project binding, immutable prompts/references, durable uncertain-submission recovery, provider routing, safe transport errors and credential-free subprocess environments.
- `.venv/bin/python test_composite.py`: **passed**. Synthetic frames preserve exact decoded colored-depth foreground pixels and original RGB background.
- `.venv/bin/python doctor.py --mesh --require-keys`: **exit 0**. Local dependencies, Rubber Band, the isolated face worker and required key presence pass. OpenArt CLI 0.1.1 is authenticated; the live account reports **Starter, 4,000 credits**. The live catalog and schema verify `byte-plus-seedance-2-5-draft`, `element2video`, **480p**. The configured private raw-mask endpoint is retained.
- Independent read-only OpenArt project discovery verifies a writable default project. The official MCP service accepts the local CLI's OAuth credential. The CLI owns refresh; no token is copied into `.env` or persisted job state.
- Python syntax: **33 files passed**. UI JavaScript syntax and `git diff --check` pass.
- Local UI inspection verifies OpenArt / Seedance 2.5 Draft / 480p labels, the three preparation modes, explicit credit-quote gating and disabled HD upgrade. The UI runs only on loopback at `http://127.0.0.1:8770`.
- **No media uploads, inference, generation, HD purchases or credit spending occurred during this migration. OpenArt remained at 4,000 credits.**

## Provider behavior and remaining limits

The installed OpenArt CLI's video command supports text-to-video and image-to-video only. The workflow therefore uses OpenArt's official Streamable HTTP MCP endpoint for video references, exact quotes, generation and result collection. Live model schema permits a 4–30 second integer duration, one or more visual references, image/video reference types and 480p output. The reviewed source with embedded guidance is first; appearance references follow. The exact creative prompt and actual mode are saved.

New jobs use OpenArt. Saved Dreamina jobs retain their original identities and may only collect existing results; they cannot be silently resubmitted through OpenArt. A durable attempted marker precedes every generation call. Missing or uncertain history IDs never trigger an automatic retry. The provider does not expose a client idempotency key or server-enforced maximum charge. A fresh exact quote is checked against explicit approval immediately before submission; pricing could still change between those calls.

Live uploads, generation admission, media quality and downloading remain **untested** because they require an authorized media job. Tests and account/schema checks are not end-to-end delivery proof. Full-clip visual review and explicit approval of each generation's quote remain required. The local HD action is disabled, although OpenArt advertises a paid upgrade action on eligible completed drafts; implementing it requires a separately approved quote and preserved draft lineage.

## Preserved preparation setup

Earlier read-only setup verified HF account authentication, OpenAI configured-model metadata, ElevenLabs account/George voice access, and the private SAM3 `/segment_raw` schema. These were not inference checks and were not all repeated during the provider migration. `ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb` remains selected. The private `wosx/genjustsu-sam3-raw` Space was RUNNING on free ZeroGPU at commit `28a44ff891b02b61c885b764ea1c331d842f4f9e` in that verification. Its current configured endpoint is unchanged.

That raw-mask endpoint accepts at most **8 seconds (192 frames at 24 fps)** and rejects longer inputs without truncation. Advanced depth modes share this limit. Fast face mesh skips depth/SAM; its small Google model downloads on first use. Mesh tracking and real mask quality still require full-clip review. Final exports preserve the entire untouched original source audio by default; generated audio is discarded.

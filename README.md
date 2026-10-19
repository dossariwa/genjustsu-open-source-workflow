# GENJUSTSU // 幻術 · 変わり身の術

**Kawarimi Substitution Studio** — an independent, open-source cloud video workflow.

A local FastAPI UI for cloud-assisted video subject replacement. Prepare a clip, review its entire mask or face tracking, review the exact creative prompt, then explicitly submit an OpenArt Seedance 2.5 Draft. Original source files and the complete original soundtrack are preserved.

The dark Shinobi interface uses obsidian surfaces, crimson controls, cyan telemetry and JetBrains Mono readouts. The four stages are preparation, full-clip review, Kawarimi target references with credit approval, and draft comparison with restored audio. Its “Replace anything” concept supports person, creature and object prompts within the configured providers' capabilities. Background preservation is a generation instruction, not a guarantee of byte-identical generated pixels; original audio preservation refers to the source's compressed audio packets.

## Interface and hero reference

The page structure lives in `static/index.html`, styling in `static/styles.css`, and browser behavior in `static/app.js`. Existing endpoint contracts, form names and saved-job reference identifiers remain compatible so earlier jobs can still be reviewed and collected.

Use `static/assets/genjutsu_hero.webp` as the default hero reference, or select an image or GIF with the hero's local banner control. The banner is visual inspiration only and is separate from the job's submitted identity references. Download a Pinterest visual you have permission to use and choose that local file; a Pinterest page link is not an image upload. Hero selection does not submit media or start paid generation.

Telemetry distinguishes local configuration from authenticated provider checks and completed generation. `/capabilities` reports configured model, mask Space and voice settings without provider calls; `/telemetry` reads only the OpenArt account and returns its plan, credit balance and check time without private account fields. A requested account profile is not a live credit balance when that check is unavailable. Voice configuration does not enable speech-to-speech conversion by itself: pitch-shifted guidance remains the default until conversion is explicitly configured.

## Stack

| Stage | Provider / implementation |
| --- | --- |
| Colored depth | Hugging Face Video Depth Anything through `gradio_client` |
| Raw subject masks | Configurable Hugging Face SAM 3 Space exporting per-frame PNG masks |
| Voice isolation, transcription, optional conversion | ElevenLabs isolation, Scribe and speech-to-speech APIs |
| Scene prompt and sampled mask advice | OpenAI vision, editable suggestions; never automatic review approval |
| Generation | Official OpenArt MCP with CLI OAuth, Seedance 2.5 Draft at 480p, persisted request identities |
| Local media work | PyAV, NumPy/SciPy, Rubber Band; optional lightweight CPU face worker |

Replicate, Enhancor, public temporary hosts and callback tunnels are not used. No heavy depth, segmentation or audio model weights are downloaded locally. Optional face-mesh modes retain their small Google Face Landmarker model and isolated CPU environment. Older Dreamina jobs retain their original collector and state; new jobs use OpenArt.

## Current provider limits

The configured private SAM3 endpoint `/segment_raw` accepts **up to 8 seconds** (192 frames at 24 fps). It rejects longer clips rather than silently truncating. The public `merve/SAM3-video-segmentation` demo exposes rendered overlays and cannot replace raw masks; see [the raw-mask contract](docs/HF-RAW-MASKS.md).

OpenArt `byte-plus-seedance-2-5-draft` uses a **480p draft** with the prepared video and image or video identity references. The authenticated OpenArt model schema determines accepted inputs. The official MCP transport supports reference-video mode using the CLI OAuth session; the installed CLI generation command alone only exposes text/start-frame inputs. The OpenArt connector and local CLI have separate authentication sessions; an upgraded connector account does not alone authenticate this repository's CLI. See [the OpenArt contract](docs/OPENART.md).

Generation requires current full-clip review, the exact displayed prompt, sufficient credits and explicit spending approval. HD remains disabled in the current adapter until the provider's draft-linked completion action has an implemented approval flow. Any future HD completion must use that action and separate HD approval. A fresh high-resolution generation is never silently substituted for an upgrade. Local tests, account checks and quotes do not establish end-to-end generation or delivery readiness.

## Setup

Follow [docs/SETUP-AGENT.md](docs/SETUP-AGENT.md), or:

```bash
PYTHON=python3.12 bash setup.sh
# Edit .env privately with your own keys; do not paste keys into chat.
# Install/authenticate the official OpenArt CLI separately.
.venv/bin/python doctor.py --require-keys
bash start.command
```

The UI binds to [127.0.0.1:8770](http://127.0.0.1:8770). `PORT=8771 bash start.command` selects another port. A running UI is distinct from generation readiness. Setup and doctor never upload user media, submit inference or purchase credits.

Required configuration: `HF_ACCESS_TOKEN` (or `HF_TOKEN`), `ELEVENLABS_API_KEY`, `OPENAI_API_KEY`, and an authenticated OpenArt CLI. OpenArt uses its own OAuth session rather than a project API key. See [.env.example](.env.example) for provider endpoints and model selections. Environment variables take precedence over this repository's `.env`; no other project's secrets are read.

## Preparation and audio

- **Depth + SAM**: colored cloud depth composited through raw cloud masks over the original RGB background. RGB segmentation fallback is recorded if depth masks fail objective alignment/coverage checks; human review still checks every frame.
- **Fast · Face Mesh**: skips depth and SAM, overlays facial guidance on the original frames. One centered speaker is the supported experimental use case.
- **Combined Depth + Mesh**: retains the depth composite and adds facial tracking from the original frames. Review both components.

For mesh modes, run `bash setup-face-mesh.sh` with Python 3.12, then `doctor.py --mesh`. The model downloads on first use. The main application stays in its separate `.venv`.

ElevenLabs isolates vocals and Scribe saves `dialogue.txt` and `dialogue_transcript.json`. Verify machine transcription before submission. Guidance uses Rubber Band +3 semitones by default; `AUDIO_DISGUISE_MODE=elevenlabs_sts` plus `ELEVENLABS_VOICE_ID` selects voice conversion. Guidance remains embedded in the prepared MP4; no separate audio reference is submitted.

`FINAL_AUDIO_SOURCE=original` copies original compressed audio packets without re-encoding, discarding generated audio. A small final-frame hold may be recorded to preserve the complete source soundtrack. `FINAL_AUDIO_SOURCE=elevenlabs_sts` explicitly opts into converted voice plus an **estimated residual background**, not a true instrumental stem or byte-identical source audio.

## Review, submission and recovery

Full-clip visual and audio review is mandatory. Artifact hashes invalidate approval after mask, mesh, source, guidance or embedded-audio changes. OpenAI checks only sampled frames and cannot grant approval. Image-reference selection can populate an editable scene prompt; a video identity stays a video and requires a manually written prompt rather than unauthorized still extraction. Review subject mapping and dialogue, then submit the exact displayed prompt.

OpenArt state is written before remote side effects. Restart and resume collect the saved request; uncertain submissions are never blindly repeated. Inspect the quote and explicitly approve a credit ceiling. Draft artifacts remain intact. See [agent operations](docs/AGENT-OPERATIONS.md) and [OpenArt contract](docs/OPENART.md).

```bash
.venv/bin/python workflow.py prepare /path/source.mp4 --mode face_mesh
.venv/bin/python workflow.py status LOCAL_JOB_ID
.venv/bin/python workflow.py review LOCAL_JOB_ID --approve --fingerprint HASH --note 'User reviewed complete clip and audio'
.venv/bin/python workflow.py submit LOCAL_JOB_ID --prompt-file prompt.txt --reference character.png
.venv/bin/python workflow.py resume LOCAL_JOB_ID
# Only after viewing the quote and explicitly approving its ceiling:
.venv/bin/python workflow.py resume LOCAL_JOB_ID --credit-ceiling APPROVED_AMOUNT
```

## Validation

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python test_composite.py
node --check static/app.js
.venv/bin/python doctor.py
.venv/bin/python doctor.py --require-keys
```

Tests use synthetic media and mocked remote calls. Doctor performs dependency and read-only provider checks. See [validation evidence and limitations](docs/VALIDATION.md). The examples are historical media, not proof of the new providers' output. [MIT](LICENSE) covers project code; see [third-party notices](THIRD-PARTY.md) for assets and external tools.

# Dreamina Canvas contract

The installed binary is authoritative. During this refactor it reported version 1.0.3, canvas/node/resource/operation commands and video modes `t2v`, `first_last_frame`, `m2v`. It has no `query_result`, `list_task`, video Edit, draft-completion or video-upscale command. Do not use the unrelated older `dreamina` examples.

The bridge discovers schema/auth/models before saving. It imports authorized local video and image paths into a canvas, saves a single `m2v` draft, quotes the saved node and runs only within explicit generation authorization and any required credit ceiling. It validates model-specific duration, aspect ratio, resolution and reference types. Video identity stays video. Prompt text is saved exactly as reviewed.

State lives in `dreamina-state.json` with public canvas/node/update/submit/resource IDs, source artifact hashes, exact prompt and status. Atomic writes precede side effects. Unknown submissions are inspected using the original ID; resume never invents another. Credit-confirmation tokens remain ephemeral and are never saved. Provider payloads, signed URLs and credentials are not persisted.

Authenticated catalog inspection on 2026-10-18 verified the canonical draft model `seedance_2.0_mini`, with `m2v`, 720p, integer durations of 4–15 seconds, and image/video references. The catalog lists ratios 21:9, 16:9, 4:3, 1:1, 3:4 and 9:16. The configured `seedance_2.5` HD name does not enable an upgrade capability. Resolve the catalog for the current account before submission; catalog access alone does not establish generation admission, membership or credits. In the inspected catalog, the mini model's resolution entries require VIP even though its top-level model flag does not.

On macOS, a restricted process can report `loggedIn: false` when it cannot access the CLI's keychain credential. Verify using the installed CLI in a normal user terminal before asking the user to sign in again. Do not copy keychain credentials into this repository.

Video download is attempted through `resource download` only after positive terminal resource facts; the current help documents images, so a video rejection is surfaced for manual recovery. A completed operation without a downloaded/restored MP4 is not delivered.

HD is explicitly unavailable under this contract. User approval cannot create a nonexistent provider capability. The bridge rejects upgrade without touching the draft or spending on a second generation.

# OpenArt provider contract

New jobs use the official OpenArt API through its MCP transport, authenticated by the official local OpenArt CLI, with `byte-plus-seedance-2-5-draft` at 480p. The prepared source MP4 is the motion/audio guidance reference. Image identities remain images; video identities remain videos and are appearance-only unless the user requests their performance. No standalone audio references are submitted.

## Authentication and setup

`OPENART_CLI_BIN` selects the official CLI executable. OpenArt uses the CLI's own OAuth session, not an `OPENART_API_KEY` in this repository. A connected OpenArt app has a separate session and cannot alone authenticate local workflow execution. The inspected CLI is version 0.1.1. Sign in with `openart login`, then verify the same upgraded account through `openart --json --no-input account`. On this machine the CLI is installed at `/Users/wosi/.local/bin/openart`. An account check returned the Starter plan with 4,000 credits during setup; balance and plan may change.

Setup and doctor only inspect installed capabilities, account state, model catalog and schema. A non-spending price quote is permitted; media upload, generation, HD completion and purchases are not setup checks. Keep all tokens and private result URLs out of logs. The workflow retains its existing HF, ElevenLabs and OpenAI credentials and private SAM3 endpoint.

The installed CLI's `generate video` supports text-to-video and a single start-frame image, so it cannot directly express this workflow's video references. The adapter uses the official `https://mcp.openart.ai/mcp` endpoint for the verified `element2video` schema, exact quotes, generation and collection. It uses the CLI OAuth credential locally and never stores that credential in `.env` or job metadata. Do not invent a `--video` CLI flag.

Read-only inspection commands include:

```bash
openart version
openart --json --no-input account
openart --json --no-input model list
openart --json --no-input model form byte-plus-seedance-2-5-draft element2video
```

The bridge verifies the model and mode through `openart_model_list` and `openart_model_form_get` before any authorized media work. CLI `model cost` is a non-spending estimate; submission uses an exact quote for the actual input parameters.

## Submission and recovery

The adapter validates the installed model contract before upload or submission. A draft requires current artifact-bound full-clip review, the exact shown creative prompt and explicit credit approval. The adapter obtains a fresh exact quote for the actual parameters and compares it with the approved ceiling immediately before submission. The verified provider contract has no server-enforced maximum-charge parameter, so this local quote gate cannot guarantee a price cap if pricing changes between quote and submission. Persist local request identity and input metadata before side effects. Save returned provider IDs immediately. After an uncertain submission, observe the original request and never blindly repeat a potentially charged call.

New jobs are isolated from historical Dreamina state. The legacy Dreamina collector may retrieve an existing result; it must never resubmit that job as an OpenArt generation. Provider status is evidence of processing, not local delivery. Completion requires downloading a real result and restoring the complete source audio to the final preview.

## HD and limitations

Seedance 2.5 Draft is advertised with a 480p draft and a later HD completion path. The current adapter leaves HD disabled: it has not implemented the credit-approved action returned by a completed draft. A future supported upgrade must use that exact action, explicit HD approval, the original draft lineage and a current artifact review. Never replace this unavailable operation with a new generation.

Account authentication, a credit balance and a valid schema do not prove that a particular video/reference combination will be admitted or produce a usable output. No paid inference runs during setup or doctor. The configured private SAM3 Space independently limits depth preparation to 8 seconds; experimental mesh modes require the isolated face worker.

[OpenArt Seedance 2.5 Draft model details](https://i18n.openart.ai/ai-model/seedance-2-5-draft/)

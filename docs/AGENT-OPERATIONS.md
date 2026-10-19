# Agent operations

Read root `AGENTS.md`. All IDs below are local job IDs. New jobs use OpenArt; provider state and identities are persisted in the run directory. Existing Dreamina jobs keep `dreamina-state.json` and their original collector.

```bash
.venv/bin/python workflow.py prepare /path/source.mp4 --subject person --mode depth
.venv/bin/python workflow.py status LOCAL_JOB_ID
.venv/bin/python workflow.py repair-rgb LOCAL_JOB_ID
.venv/bin/python workflow.py audit LOCAL_JOB_ID
.venv/bin/python workflow.py prompt LOCAL_JOB_ID --reference character.png
.venv/bin/python workflow.py review LOCAL_JOB_ID --approve --fingerprint CURRENT_HASH --note 'Who reviewed and full-clip findings'
.venv/bin/python workflow.py submit LOCAL_JOB_ID --prompt-file prompt.txt --reference character.png
.venv/bin/python workflow.py resume LOCAL_JOB_ID
# Explicitly continue interrupted media preparation before submission:
.venv/bin/python workflow.py resume-preparation LOCAL_JOB_ID
```

Audit/prompt and preparation invoke cloud providers and may incur charges; use within the user's authorized scope. Omit `--approve` to record rejection. RGB repair invokes new SAM work and clears approval. The configured private SAM3 endpoint accepts at most 8 seconds. Mesh-only jobs have no SAM mask. Combined repairs reapply the facial mesh. Never run UI and CLI submissions concurrently; saved identities and operation locks guard against accidental duplicate generation.

Review the complete prepared video and listen to guidance. Check every cut, hair, hands, limbs, clothes, holes, background spill, tracking and temporal stability. OpenAI sampled advice is never approval. User review may be recorded explicitly without pretending an agent inspected video.

Show the exact prompt. Describe environment and replacement characters without naming the source actor. Verify machine-transcribed dialogue and mapping. A single identity uses only one reference. The first video is motion/audio guidance; identity video is appearance-only. Mesh/depth colors must disappear and full identity, including hair, must change. The adapter does not silently append or alter creative text. Keep guidance embedded in the prepared MP4 and never add separate audio references.

Inspect the quote before `resume LOCAL_JOB_ID --credit-ceiling AMOUNT`. This flag is explicit credit-ceiling approval, not a status query. The adapter checks a fresh exact quote locally; the provider contract exposes no server-enforced maximum-charge parameter, so a quote is not a guaranteed billing cap. Continue the saved request and preserve all provider identities. Ordinary resume and startup only collect saved work. An unknown or absent operation is not permission to create a replacement. Fix credentials then observe the same work. Failed preparation is not universally resumable; inspect cached artifacts before repeating paid stages.

HD intent alone does not authorize an invented provider operation. Use only a verified OpenArt completion contract tied to the existing draft, after explicit HD spending approval. The current adapter's capability determines whether the UI and CLI permit it. Never substitute a new generation for an upgrade. The legacy Dreamina collector retains its lack of video HD completion.

Final output is `runs/LOCAL_JOB_ID/final-preview.mp4`, with a `draft_final.mp4` alias where available. Restore the complete source soundtrack by default, discard generated audio and record any short last-frame hold. Preserve the raw generation and all draft metadata. If automatic download fails, import the downloaded provider result through the UI to restore audio. No submission or completion claim without actual persisted provider/result evidence.

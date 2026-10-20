import type { ClipLimit, PreparationMode } from "../api/types";

export type StepId = "prepare" | "inspect" | "substitute" | "restore";

export const STEPS: { id: StepId; index: string; title: string; short: string; kanji: string; tag: string; lockedHint: string }[] = [
  { id: "prepare", index: "01", title: "Prepare", short: "Prepare", kanji: "源", tag: "SOURCE", lockedHint: "" },
  { id: "inspect", index: "02", title: "Inspect", short: "Inspect", kanji: "眼", tag: "VISUAL GATE", lockedHint: "Locked · prepare your video first" },
  { id: "substitute", index: "03", title: "Substitute", short: "Substitute", kanji: "術", tag: "KAWARIMI", lockedHint: "Locked · approve the input review first" },
  { id: "restore", index: "04", title: "Restore & Export", short: "Export", kanji: "音", tag: "AUDIO RESTORATION", lockedHint: "Locked · unlocks when your draft is ready" },
];

/** Same preview set and captions as static/app.js. */
export const PREVIEW_ITEMS = [
  { label: "Prepared input", file: "seedance-input.mp4", caption: "Prepared video + isolated vocals pitched +3" },
  { label: "Original", file: "original.mp4", caption: "Original video" },
  { label: "Depth", file: "depth.mp4", caption: "Exact depth colors from the model" },
  { label: "Mask", file: "mask.mp4", caption: "Full subject mask" },
] as const;

export const AUDIO_ITEMS = [
  { file: "isolated_vocals.wav", title: "Isolated vocals" },
  { file: "guidance-audio.wav", title: "Guidance vocals" },
  { file: "music.wav", title: "Estimated background" },
  { file: "dialogue.txt", title: "Scribe transcript" },
] as const;

export const REFERENCE_EXTENSIONS = ["png", "jpg", "jpeg", "webp", "mp4", "mov", "webm"] as const;
export const VIDEO_EXTENSIONS = ["mp4", "mov", "webm"];

export const MODE_OPTIONS: { value: PreparationMode; label: string; description: string }[] = [
  {
    value: "depth",
    label: "Depth + SAM",
    description:
      "Colored Hugging Face depth + raw per-frame SAM masks. Keep exact depth colors and isolate the full selected subject.",
  },
  {
    value: "face_mesh",
    label: "Fast · Face Mesh",
    description:
      "Experimental · one centered speaker. Tracks original frames in the isolated CPU worker; skips depth and SAM. Review every frame for facial alignment and gaps. Seedance drafts support 4–30 seconds.",
  },
  {
    value: "depth_mesh",
    label: "Combined Depth + Mesh",
    description:
      "Experimental · one centered speaker. Colored depth + raw SAM masks with original-frame facial tracking. Both mask and tracking review are required.",
  },
];

/** Depth limit fallback when /capabilities is unavailable (matches config.py). */
export const DEPTH_FALLBACK: Required<ClipLimit> = { max_seconds: 8, max_frames: 192, fps: 24 };

export const DEFAULT_PROMPT =
  "Replace the complete selected subject with the supplied character reference in every frame, including hair, hands, clothing and footwear. Preserve the original background, camera framing, lighting, motion and timing. Match the embedded speech exactly without extra dialogue. Use the embedded vocals in the first, prepared source video for performance and lip synchronization. Any identity video supplies appearance only, not its voice or performance. Remove all colored depth and face-mesh lines from the output. If using two characters, specify which subject each reference replaces before submitting.";

/**
 * Single swappable hero asset. Replace this file (or point this constant at a
 * new file under web/public/ui/hero/) when the final eye artwork is ready.
 * Users can still override it locally via "Customize banner" (IndexedDB).
 */
export const HERO_DEFAULT_SRC = "/ui/hero/eyes-placeholder.webp";
export const HERO_DEFAULT_ALT = "Placeholder eye artwork: a crimson Sharingan and a violet Rinnegan on black";

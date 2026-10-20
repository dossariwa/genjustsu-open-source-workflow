import type { Capabilities, ClipLimit, PreparationMode } from "../api/types";
import { DEPTH_FALLBACK } from "./constants";

export const isDepthMode = (mode: PreparationMode) => mode !== "face_mesh";

/** Display/UX only. FastAPI (PyAV) is authoritative for the depth limit. */
export function clipLimit(capabilities: Capabilities | null, mode: PreparationMode): ClipLimit | null {
  const limit = capabilities?.clip_limits?.[mode];
  if (limit && Number.isFinite(limit.max_seconds)) return limit;
  return isDepthMode(mode) ? DEPTH_FALLBACK : null;
}

export function depthLimit(capabilities: Capabilities | null): Required<ClipLimit> {
  const limit = capabilities?.clip_limits?.depth;
  return {
    max_seconds: limit?.max_seconds ?? DEPTH_FALLBACK.max_seconds,
    max_frames: limit?.max_frames ?? DEPTH_FALLBACK.max_frames,
    fps: limit?.fps ?? DEPTH_FALLBACK.fps,
  };
}

export const describeLimit = (limit: ClipLimit) =>
  `≤ ${limit.max_seconds.toFixed(1)} seconds` + (limit.max_frames ? ` / ${limit.max_frames} frames @ ${limit.fps ?? 24}fps` : "");

export interface DurationCheck {
  /** Blocks submission (depth modes only, exactly like the legacy UI). */
  invalid: boolean;
  /** Non-blocking advisory (face_mesh over the provider draft limit). */
  warning: boolean;
  message: string;
}

export function checkDuration(seconds: number | null, mode: PreparationMode, capabilities: Capabilities | null): DurationCheck | null {
  if (seconds === null) return null;
  const limit = clipLimit(capabilities, mode);
  const depth = isDepthMode(mode);
  const over = !!limit && seconds > limit.max_seconds;
  const max = limit ? limit.max_seconds.toFixed(1) : "";
  if (depth) {
    return {
      invalid: over,
      warning: false,
      message: `${seconds.toFixed(2)}s selected · ${over ? "over the depth limit; shorten the clip or choose Fast · Face Mesh." : `within the ${max}s depth limit.`}`,
    };
  }
  return {
    invalid: false,
    warning: over,
    message: `${seconds.toFixed(2)}s selected · ${over ? `longer than the ${max}s Seedance draft limit; the provider may reject it.` : "Fast mode skips SAM; provider duration limits still apply."}`,
  };
}

export function depthLimitMessage(capabilities: Capabilities | null) {
  const limit = depthLimit(capabilities);
  return `Depth modes accept at most ${limit.max_seconds.toFixed(1)} seconds (${limit.max_frames} frames at ${limit.fps}fps). Choose a shorter clip or Fast · Face Mesh.`;
}

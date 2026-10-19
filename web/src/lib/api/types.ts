/** Shapes returned by the existing FastAPI endpoints (see app.py). */

export type PreparationMode = "depth" | "face_mesh" | "depth_mesh";

export interface ClipLimit {
  max_seconds: number;
  max_frames?: number;
  fps?: number;
}

export interface Capabilities {
  generation?: {
    provider?: string;
    mode?: string;
    model?: string;
    resolution?: string;
    available?: boolean;
    detail?: string;
    hd_detail?: string;
    video_hd_supported?: boolean;
  };
  segmentation?: { ready?: boolean; space?: string; detail?: string };
  audio?: { provider?: string; configured?: boolean; voice_id?: string; guidance_mode?: string };
  final_audio_source?: string;
  clip_limits?: Partial<Record<PreparationMode, ClipLimit>>;
}

export interface TelemetrySummary {
  openart: {
    authenticated: boolean;
    plan: string | null;
    credits: number | null;
    checked_at: string | null;
    detail: string;
  };
}

export interface Health {
  status: string;
  service?: string;
}

export type JobState = "idle" | "running" | "done" | "error" | "awaiting_credit_approval" | string;

export interface Job {
  id?: string;
  state: JobState;
  status: string;
  minimum_credit_ceiling?: number | null;
  final_url?: string;
}

export interface MaskReview {
  approved: boolean;
  status: string;
  note?: string;
  fingerprint?: string;
  audit?: { findings?: string };
}

export interface Generation {
  provider?: string;
  status?: string;
  mode?: string;
  mode_label?: string;
  resolution?: string;
  prompt?: string;
  history_id?: string;
  submit_id?: string;
  request_id?: string;
  submitId?: string;
  reference_labels?: string[];
  web_url?: string;
  approved_credit_ceiling?: number;
  minimum_credit_ceiling?: number;
}

export interface AudioRestoration {
  mode: string;
}

export interface HdJob {
  state: JobState;
  status: string;
}

/**
 * Every call maps 1:1 onto an existing FastAPI route. The UI never decides
 * provider, review or credit outcomes; it only renders server responses.
 */
export interface StudioApi {
  readonly mode: "http" | "mock";
  capabilities(): Promise<Capabilities>;
  health(signal?: AbortSignal): Promise<Health>;
  telemetry(signal?: AbortSignal): Promise<TelemetrySummary>;
  createJob(form: FormData): Promise<Job & { id: string }>;
  getJob(id: string): Promise<Job>;
  getMaskReview(id: string): Promise<MaskReview>;
  saveMaskReview(id: string, form: FormData): Promise<MaskReview>;
  audit(id: string): Promise<{ findings: string }>;
  suggestPrompt(id: string, form: FormData): Promise<{ prompt: string }>;
  seedance(id: string, form: FormData): Promise<Job>;
  creditApproval(id: string, form: FormData): Promise<Job>;
  resume(id: string): Promise<Job>;
  resumePreparation(id: string): Promise<Job>;
  finish(id: string, form: FormData): Promise<{ url: string }>;
  getHd(id: string): Promise<HdJob>;
  createHd(id: string): Promise<HdJob>;
  /** URL of a run artifact, e.g. /runs/<id>/mask.mp4 */
  runUrl(id: string, file: string): string;
  /** HEAD probe for a run artifact. */
  exists(id: string, file: string): Promise<boolean>;
  /** GET a JSON run artifact (generation.json, audio-restoration.json). */
  runJson<T>(id: string, file: string): Promise<T>;
  runBlob(id: string, file: string): Promise<Blob>;
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

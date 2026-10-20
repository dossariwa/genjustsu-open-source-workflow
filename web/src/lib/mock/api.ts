/**
 * Mock API for UI previews (Vercel) only. It mirrors the response shapes of
 * the FastAPI routes and simulates the job lifecycle in localStorage so the
 * four steps, gates and ?job= persistence can be exercised without a backend.
 * It never contacts any provider. Enabled only by NEXT_PUBLIC_API_MODE=mock.
 */
import { ApiError, type Capabilities, type Generation, type Job, type MaskReview, type StudioApi } from "../api/types";

const STORE = "genjustsu-mock-jobs";
const SCENARIOS = "genjustsu-mock-scenarios";
const QUOTE = 120;
const PREP_MS = 7000;
const COLLECT_MS = 9000;
const FIXTURES = "/ui/mock/";

export interface MockScenarios {
  rejectNextUpload: boolean;
  failNextCollection: boolean;
}

interface MockJob {
  id: string;
  mode: string;
  createdAt: number;
  prepDoneAt: number;
  fingerprint: string;
  review: MaskReview | null;
  audit?: string;
  generation: Generation | null;
  awaitingQuote: boolean;
  collectStartedAt?: number;
  collectDoneAt?: number;
  collectFails?: boolean;
  collectError?: string;
  finalReady: boolean;
  referencesSaved: boolean;
}

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const hex = (length: number) =>
  Array.from(crypto.getRandomValues(new Uint8Array(length / 2)), (b) => b.toString(16).padStart(2, "0")).join("");

function load(): Record<string, MockJob> {
  if (typeof localStorage === "undefined") return {};
  try {
    return JSON.parse(localStorage.getItem(STORE) || "{}");
  } catch {
    return {};
  }
}
function save(jobs: Record<string, MockJob>) {
  localStorage.setItem(STORE, JSON.stringify(jobs));
}
function find(id: string): MockJob {
  const job = load()[id];
  if (!job) throw new ApiError("Unknown job", 404);
  return job;
}
function put(job: MockJob) {
  const jobs = load();
  jobs[job.id] = job;
  save(jobs);
}

export function readScenarios(): MockScenarios {
  try {
    return { rejectNextUpload: false, failNextCollection: false, ...JSON.parse(localStorage.getItem(SCENARIOS) || "{}") };
  } catch {
    return { rejectNextUpload: false, failNextCollection: false };
  }
}
export function writeScenarios(value: MockScenarios) {
  localStorage.setItem(SCENARIOS, JSON.stringify(value));
}
export function resetMock() {
  localStorage.removeItem(STORE);
  localStorage.removeItem(SCENARIOS);
}

const prepared = (job: MockJob) => Date.now() >= job.prepDoneAt;

/** Settle time-based transitions (collection finishing or failing). */
function settle(job: MockJob): MockJob {
  if (job.collectDoneAt && Date.now() >= job.collectDoneAt && !job.finalReady && !job.collectError) {
    if (job.collectFails) {
      job.collectError = "OpenArt status check timed out (mock). The saved generation is intact; resume collection.";
      job.collectFails = false;
    } else {
      job.finalReady = true;
      if (job.generation) job.generation.status = "completed";
    }
    put(job);
  }
  return job;
}

const PREP_STEPS: Record<string, string[]> = {
  depth: [
    "Uploading source…",
    "Isolating vocals with ElevenLabs…",
    "Transcribing dialogue with Scribe…",
    "Requesting colored depth from Hugging Face…",
    "Extracting raw per-frame SAM masks…",
    "Compositing original depth colors through masks…",
  ],
  face_mesh: ["Uploading source…", "Isolating vocals with ElevenLabs…", "Tracking original frames in the CPU worker…", "Embedding guidance audio…"],
  depth_mesh: [
    "Uploading source…",
    "Isolating vocals with ElevenLabs…",
    "Requesting colored depth from Hugging Face…",
    "Extracting raw per-frame SAM masks…",
    "Overlaying original-frame facial tracking…",
  ],
};

function jobStatus(job: MockJob): Job {
  settle(job);
  const now = Date.now();
  if (!prepared(job)) {
    const steps = PREP_STEPS[job.mode] ?? PREP_STEPS.depth;
    const index = Math.min(steps.length - 1, Math.floor(((now - job.createdAt) / PREP_MS) * steps.length));
    return { id: job.id, state: "running", status: steps[index] };
  }
  if (job.finalReady)
    return { id: job.id, state: "done", status: "Final preview ready · configured source audio restored", final_url: FIXTURES + "final-preview.mp4" };
  if (job.collectError) return { id: job.id, state: "error", status: job.collectError };
  if (job.collectDoneAt && now < job.collectDoneAt) {
    const id = job.generation?.history_id ?? "saved";
    const half = now - (job.collectStartedAt ?? now) > COLLECT_MS / 2;
    return { id: job.id, state: "running", status: half ? `OpenArt ${id} · rendering draft…` : `Collecting saved generation ${id}` };
  }
  if (job.awaitingQuote)
    return {
      id: job.id,
      state: "awaiting_credit_approval",
      status: `OpenArt quoted ${QUOTE} credits. Approve a credit ceiling for this saved request.`,
      minimum_credit_ceiling: QUOTE,
    };
  return { id: job.id, state: "done", status: "Preparation complete · full-clip review required" };
}

const capabilities: Capabilities = {
  generation: {
    provider: "openart",
    mode: "element2video",
    model: "byte-plus-seedance-2-5-draft",
    resolution: "480p",
    available: true,
    detail: "Mock API · OpenArt is simulated for this UI preview. No provider is contacted and nothing is charged.",
    video_hd_supported: false,
  },
  segmentation: { ready: true, space: "wosx/genjustsu-sam3-raw" },
  audio: { provider: "elevenlabs", configured: true, voice_id: "JBFqnCBsd6RMkjVDRZzb", guidance_mode: "pitch_shift" },
  final_audio_source: "original",
  clip_limits: {
    depth: { max_seconds: 8, max_frames: 192, fps: 24 },
    depth_mesh: { max_seconds: 8, max_frames: 192, fps: 24 },
    face_mesh: { max_seconds: 30 },
  },
};

function files(job: MockJob): Record<string, string> {
  settle(job);
  const present: Record<string, string> = {};
  if (prepared(job)) {
    Object.assign(present, {
      "upload.mp4": "original.mp4",
      "original.mp4": "original.mp4",
      "seedance-input.mp4": "seedance-input.mp4",
      "isolated_vocals.wav": "guidance-audio.wav",
      "guidance-audio.wav": "guidance-audio.wav",
      "music.wav": "guidance-audio.wav",
      "dialogue.txt": "dialogue.txt",
    });
    if (job.mode !== "face_mesh") Object.assign(present, { "depth.mp4": "depth.mp4", "mask.mp4": "mask.mp4" });
  }
  if (job.referencesSaved) present["sirio-reference.png"] = "sirio-reference.png";
  if (job.generation) present["generation.json"] = "";
  if (job.finalReady)
    Object.assign(present, {
      "final-preview.mp4": "final-preview.mp4",
      "seedance-result.mp4": "final-preview.mp4",
      "audio-restoration.json": "",
    });
  return present;
}

function requireReviewable(job: MockJob) {
  if (!prepared(job)) throw new ApiError("Complete preparation, including guidance audio and transcription, before suggesting a prompt.", 409);
}

export const mockApi: StudioApi = {
  mode: "mock",
  async capabilities() {
    await delay(150);
    return structuredClone(capabilities);
  },
  async health() {
    return { status: "ok", service: "Genjustsu Cloud Workflow (mock)" };
  },
  async telemetry() {
    await delay(400);
    return {
      openart: {
        authenticated: true,
        plan: "starter",
        credits: 4000,
        checked_at: new Date().toISOString(),
        detail: "Mock account summary. No provider was contacted.",
      },
    };
  },
  async createJob(form) {
    await delay(700);
    const mode = String(form.get("mode") ?? "depth");
    if (!["depth", "face_mesh", "depth_mesh"].includes(mode)) throw new ApiError("Unknown preparation mode", 400);
    const scenarios = readScenarios();
    if (scenarios.rejectNextUpload) {
      writeScenarios({ ...scenarios, rejectNextUpload: false });
      if (mode !== "face_mesh")
        throw new ApiError(
          "Depth modes accept at most 8.0 seconds (192 frames at 24fps). Choose a shorter clip or Fast · Face Mesh.",
          400,
        );
    }
    const now = Date.now();
    const job: MockJob = {
      id: hex(32),
      mode,
      createdAt: now,
      prepDoneAt: now + PREP_MS,
      fingerprint: hex(64),
      review: null,
      generation: null,
      awaitingQuote: false,
      finalReady: false,
      referencesSaved: false,
    };
    put(job);
    return { id: job.id, state: "running", status: "Starting preparation" };
  },
  async getJob(id) {
    return jobStatus(find(id));
  },
  async getMaskReview(id) {
    const job = find(id);
    if (!prepared(job)) return { approved: false, status: "unavailable", note: "Prepare the video first." };
    const base: MaskReview = job.review ?? {
      approved: false,
      status: "pending",
      note: "Review the entire prepared input: mask coverage for depth mode; facial tracking and overlay alignment for fast mode.",
      fingerprint: job.fingerprint,
    };
    return job.audit ? { ...base, audit: { findings: job.audit } } : base;
  },
  async saveMaskReview(id, form) {
    await delay(300);
    const job = find(id);
    if (form.get("fingerprint") !== job.fingerprint) throw new ApiError("The mask changed. Reload and review the latest preview.", 409);
    const approved = form.get("approved") === "true";
    const note = String(form.get("note") ?? "");
    if (approved && !note.trim()) throw new ApiError("Record who reviewed the entire clip and their findings.", 409);
    job.review = { approved, status: approved ? "approved" : "rejected", note, fingerprint: job.fingerprint };
    put(job);
    return job.review;
  },
  async audit(id) {
    await delay(1400);
    const job = find(id);
    requireReviewable(job);
    job.audit = "6 sampled frames: mask edges follow hair and hands; no spill detected in samples (mock advice).";
    put(job);
    return { findings: job.audit };
  },
  async suggestPrompt(id) {
    await delay(1400);
    const job = find(id);
    if (job.generation) throw new ApiError("A generation is already saved; its prompt is frozen.", 409);
    requireReviewable(job);
    return {
      prompt:
        "Replace the complete selected subject with Character 1 in every frame, including hair, hands, clothing and footwear. Preserve the dim room, both windows, camera framing, lighting, motion and timing. Match the embedded speech exactly without extra dialogue. Use the embedded vocals in the first, prepared source video for performance and lip synchronization. Remove all colored depth lines from the output. (Mock suggestion.)",
    };
  },
  async seedance(id, form) {
    await delay(900);
    const job = find(id);
    if (!job.review?.approved)
      throw new ApiError("Input review required: inspect the whole prepared video and approve its current artifacts before submitting.", 409);
    if (job.generation) throw new ApiError("This job has saved provider work. Resume it instead of submitting again.", 409);
    const tein = form.get("tein");
    job.referencesSaved = true;
    job.generation = {
      provider: "openart",
      status: "awaiting_credit_approval",
      mode: "element2video",
      mode_label: "OpenArt reference video (element2video)",
      resolution: "480p",
      prompt: String(form.get("prompt") ?? ""),
      submit_id: crypto.randomUUID(),
      minimum_credit_ceiling: QUOTE,
      reference_labels: ["Prepared source video", "Character 1 · sirio-reference.png", ...(tein ? ["Character 2 · tein-reference.png"] : [])],
    };
    job.awaitingQuote = true;
    put(job);
    return jobStatus(job);
  },
  async creditApproval(id, form) {
    await delay(700);
    const job = find(id);
    if (!job.generation || !job.awaitingQuote) throw new ApiError("No saved quote is awaiting approval.", 409);
    const ceiling = Number(form.get("credit_ceiling"));
    if (!Number.isFinite(ceiling) || ceiling < QUOTE) return jobStatus(job);
    const scenarios = readScenarios();
    if (scenarios.failNextCollection) writeScenarios({ ...scenarios, failNextCollection: false });
    const now = Date.now();
    Object.assign(job, {
      awaitingQuote: false,
      collectStartedAt: now,
      collectDoneAt: now + COLLECT_MS,
      collectFails: scenarios.failNextCollection,
      collectError: undefined,
    });
    job.generation = { ...job.generation, status: "submitted", history_id: "gen_" + hex(12), approved_credit_ceiling: ceiling };
    put(job);
    return jobStatus(job);
  },
  async resume(id) {
    await delay(400);
    const job = find(id);
    if (!job.generation?.history_id) throw new ApiError("No saved generation to collect.", 409);
    const now = Date.now();
    Object.assign(job, { collectError: undefined, collectStartedAt: now, collectDoneAt: now + COLLECT_MS / 2 });
    put(job);
    return jobStatus(job);
  },
  async resumePreparation() {
    await delay(400);
    throw new ApiError("Preparation did not produce a credit quote. Inspect the saved operation.", 409);
  },
  async finish(id) {
    await delay(900);
    const job = find(id);
    job.finalReady = true;
    put(job);
    return { url: FIXTURES + "final-preview.mp4" };
  },
  async getHd() {
    return { state: "idle", status: "HD completion requires a verified provider upgrade contract and explicit approval." };
  },
  async createHd() {
    throw new ApiError("HD upgrade is disabled until separate quote approval and lineage checks are implemented.", 409);
  },
  runUrl(id, file) {
    try {
      return FIXTURES + (files(find(id))[file] || file);
    } catch {
      return FIXTURES + file;
    }
  },
  async exists(id, file) {
    try {
      return file in files(find(id));
    } catch {
      return false;
    }
  },
  async runJson<T>(id: string, file: string): Promise<T> {
    const job = find(id);
    if (file === "generation.json" && job.generation) return structuredClone(job.generation) as T;
    if (file === "audio-restoration.json" && job.finalReady) return { mode: "original" } as T;
    throw new ApiError("Not Found", 404);
  },
  async runBlob(id, file) {
    return (await fetch(this.runUrl(id, file))).blob();
  },
};

import { ApiError, type StudioApi } from "./types";

function responseError(body: unknown, status: number) {
  const detail = (body as { detail?: unknown } | null)?.detail;
  return new ApiError(typeof detail === "string" ? detail : "The request could not be completed.", status);
}

/** Same error contract as static/app.js: surface FastAPI's string `detail`. */
async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    throw responseError(body, response.status);
  }
  return body as T;
}

const post = <T>(url: string, body?: FormData) => json<T>(url, { method: "POST", body });

export const httpApi: StudioApi = {
  mode: "http",
  capabilities: () => json("/capabilities"),
  health: (signal) => json("/health", { signal }),
  telemetry: (signal) => json("/telemetry", { signal }),
  createJob: (form) => post("/jobs", form),
  getJob: (id) => json(`/jobs/${id}`),
  getMaskReview: (id) => json(`/jobs/${id}/mask-review`),
  saveMaskReview: (id, form) => post(`/jobs/${id}/mask-review`, form),
  audit: (id) => post(`/jobs/${id}/audit`),
  suggestPrompt: (id, form) => post(`/jobs/${id}/prompt`, form),
  seedance: (id, form) => post(`/jobs/${id}/seedance`, form),
  creditApproval: (id, form) => post(`/jobs/${id}/credit-approval`, form),
  resume: (id) => post(`/jobs/${id}/resume`),
  resumePreparation: (id) => post(`/jobs/${id}/resume-preparation`),
  finish: (id, form) => post(`/jobs/${id}/finish`, form),
  getHd: (id) => json(`/jobs/${id}/hd`),
  createHd: (id) => post(`/jobs/${id}/hd`),
  runUrl: (id, file) => `/runs/${id}/${file}`,
  exists: async (id, file) => (await fetch(`/runs/${id}/${file}`, { method: "HEAD", cache: "no-store" })).ok,
  runJson: (id, file) => json(`/runs/${id}/${file}`),
  runBlob: async (id, file) => {
    const response = await fetch(`/runs/${id}/${file}`);
    if (!response.ok) throw responseError(await response.json().catch(() => null), response.status);
    return response.blob();
  },
};

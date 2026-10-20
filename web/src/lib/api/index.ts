import { httpApi } from "./http";
import { mockApi } from "../mock/api";
import type { StudioApi } from "./types";

/**
 * Mock mode is opt-in at build time (`NEXT_PUBLIC_API_MODE=mock`, used only
 * by `npm run build:mock` / Vercel previews). The FastAPI-served build is
 * always the real HTTP client.
 */
export const API_MODE: "http" | "mock" = process.env.NEXT_PUBLIC_API_MODE === "mock" ? "mock" : "http";
export const api: StudioApi = API_MODE === "mock" ? mockApi : httpApi;
export * from "./types";

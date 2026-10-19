import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

/**
 * The studio is a static export (`web/out`) served by FastAPI. All workflow
 * logic stays in Python; this app only calls the existing HTTP endpoints.
 *
 * `next dev` cannot combine `output: "export"` with rewrites, so the dev
 * server drops the export flag and proxies every FastAPI route instead.
 */
const API_ORIGIN = process.env.GENJUSTSU_API_ORIGIN ?? "http://127.0.0.1:8770";
const PROXIED = ["/capabilities", "/telemetry", "/health", "/jobs", "/jobs/:path*", "/runs/:path*", "/static/:path*"];

const shared: NextConfig = {
  images: { unoptimized: true },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default function config(phase: string): NextConfig {
  const mock = process.env.NEXT_PUBLIC_API_MODE === "mock";
  if (phase === PHASE_DEVELOPMENT_SERVER && !mock) {
    return {
      ...shared,
      async rewrites() {
        return PROXIED.map((source) => ({ source, destination: API_ORIGIN + source }));
      },
    };
  }
  return { ...shared, output: "export" };
}

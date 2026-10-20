"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Capabilities } from "../api";
import { depthLimit } from "./limits";

export interface TelemetryView {
  loopback: string;
  online: boolean;
  account: string;
  accountDetail: string;
  model: string;
  modelDetail: string;
  sam: string;
  samDetail: string;
  voice: string;
  voiceDetail: string;
  checking: boolean;
}

const GEORGE = "JBFqnCBsd6RMkjVDRZzb";

/** Same wording and read-only calls as renderConfiguration/refreshTelemetry in static/app.js. */
export function useTelemetry(capabilities: Capabilities | null, capabilitiesError: boolean) {
  const [health, setHealth] = useState<{ host: string; online: boolean } | null>(null);
  const [account, setAccount] = useState({ summary: "Checking account…", detail: "Requested profile: Starter · 4,000 credits" });
  const [checking, setChecking] = useState(false);
  const busy = useRef(false);

  const refreshTelemetry = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    setChecking(true);
    const [healthResult, accountResult] = await Promise.allSettled([
      api.health(AbortSignal.timeout(10000)),
      api.telemetry(AbortSignal.timeout(30000)),
    ]);
    setHealth({ host: window.location.host, online: healthResult.status === "fulfilled" && healthResult.value.status === "ok" });
    const summary = accountResult.status === "fulfilled" ? accountResult.value.openart : null;
    if (summary?.authenticated) {
      const plan = summary.plan ? summary.plan.charAt(0).toUpperCase() + summary.plan.slice(1) : "Plan unavailable";
      const credits = typeof summary.credits === "number" ? `${summary.credits.toLocaleString()} credits` : "balance unavailable";
      const checked = summary.checked_at ? new Date(summary.checked_at) : null;
      const time =
        checked && !Number.isNaN(checked.getTime()) ? " · " + checked.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
      setAccount({ summary: `${plan} · ${credits}`, detail: `MCP account checked${time} · generation unverified` });
    } else {
      setAccount({ summary: "Account check unavailable", detail: "Requested profile: Starter · 4,000 credits. Balance unverified." });
    }
    busy.current = false;
    setChecking(false);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial read-only telemetry check, as in the legacy UI
    refreshTelemetry();
  }, [refreshTelemetry]);

  const generation = capabilities?.generation ?? {};
  const segmentation = capabilities?.segmentation ?? {};
  const audio = capabilities?.audio ?? {};
  const limit = depthLimit(capabilities);
  const limitText = `≤ ${limit.max_seconds.toFixed(1)}s / ${limit.max_frames} frames @ ${limit.fps}fps`;
  const unverified = capabilitiesError;

  const view: TelemetryView = {
    loopback: health ? `${health.host} · ${health.online ? "UI online" : "health unverified"}` : "checking…",
    online: !!health?.online,
    account: account.summary,
    accountDetail: account.detail,
    model: generation.model || "byte-plus-seedance-2-5-draft",
    modelDetail: unverified
      ? "element2video · 480p · configuration unverified"
      : `${generation.mode || "element2video"} · ${generation.resolution || "480p"} · configured contract`,
    sam: segmentation.space || (capabilities ? "Raw-mask Space not configured" : "wosx/genjustsu-sam3-raw"),
    samDetail: `${limitText} · ${unverified ? "configuration unverified" : !capabilities ? "checking config" : segmentation.ready ? "configured; live unverified" : "configuration required"}`,
    voice: unverified
      ? "George · configuration unverified"
      : !capabilities
        ? "George · checking config"
        : `${audio.voice_id === GEORGE ? "George" : audio.voice_id ? "Custom voice" : "Voice not set"} · ${audio.configured ? "key configured" : "key unverified"}`,
    voiceDetail: `${audio.voice_id || "Requested: " + GEORGE} · ${audio.guidance_mode === "elevenlabs_sts" ? "configured STS" : "+3 semitone guidance"}`,
    checking,
  };
  return { telemetry: view, refreshTelemetry };
}

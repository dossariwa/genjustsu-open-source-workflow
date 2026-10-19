"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Capabilities, type Generation, type HdJob, type Job, type MaskReview } from "../api";
import { AUDIO_ITEMS, PREVIEW_ITEMS, REFERENCE_EXTENSIONS, VIDEO_EXTENSIONS, type StepId } from "./constants";

export interface StatusLine {
  text: string;
  tone: "neutral" | "busy" | "error" | "success";
}

export interface FinalPreview {
  url: string;
  hd: boolean;
  originalUrl: string;
  audioMode: string;
}

export interface SavedReference {
  file: string;
  url: string;
  isVideo: boolean;
}

const POLL_MS = 3000;
const HD_POLL_MS = 4000;

function readJobFromUrl() {
  if (typeof window === "undefined") return null;
  // FastAPI validates the identifier; the UI only persists it in ?job=.
  return new URLSearchParams(window.location.search).get("job");
}

/**
 * Client state for the studio. It mirrors static/app.js call-for-call:
 * the same endpoints, payloads, 3s job polling, 4s HD polling and gates.
 * Every decision (review validity, quotes, limits) comes from FastAPI.
 */
export function useStudio() {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [capabilitiesError, setCapabilitiesError] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [previews, setPreviews] = useState<(typeof PREVIEW_ITEMS)[number][]>([]);
  const [review, setReview] = useState<MaskReview | null>(null);
  const [audioLinks, setAudioLinks] = useState<(typeof AUDIO_ITEMS)[number][]>([]);
  const [savedRefs, setSavedRefs] = useState<{ sirio?: SavedReference; tein?: SavedReference }>({});
  const [generation, setGeneration] = useState<Generation | null>(null);
  const [finalPreview, setFinalPreview] = useState<FinalPreview | null>(null);
  const [hd, setHd] = useState<HdJob | null>(null);
  const [upgradeStatus, setUpgradeStatus] = useState("");
  const [status, setStatusState] = useState<StatusLine>({ text: "Studio ready. Start by choosing your original video.", tone: "neutral" });
  const [loaded, setLoaded] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const jobRef = useRef<string | null>(null);
  const omittedSecondary = useRef(false);
  const watchRef = useRef<() => Promise<void>>(async () => {});
  const pollHdRef = useRef<() => Promise<void>>(async () => {});

  const setStatus = useCallback((text: string, tone: StatusLine["tone"] = "neutral") => setStatusState({ text, tone }), []);
  const busy = job?.state === "running";

  const refresh = useCallback(async () => {
    const id = jobRef.current;
    if (!id) return;
    const present = await Promise.all(PREVIEW_ITEMS.map((item) => api.exists(id, item.file)));
    setPreviews(PREVIEW_ITEMS.filter((_, i) => present[i]));
    const nextReview = await api.getMaskReview(id);
    setReview(nextReview);
    const audio = await Promise.all(AUDIO_ITEMS.map((item) => api.exists(id, item.file)));
    setAudioLinks(AUDIO_ITEMS.filter((_, i) => audio[i]));
    const refs: { sirio?: SavedReference; tein?: SavedReference } = {};
    for (const name of ["sirio", "tein"] as const) {
      if (name === "tein" && omittedSecondary.current) continue;
      for (const ext of REFERENCE_EXTENSIONS) {
        const file = `${name}-reference.${ext}`;
        if (await api.exists(id, file)) {
          refs[name] = { file, url: api.runUrl(id, file), isVideo: VIDEO_EXTENSIONS.includes(ext) };
          break;
        }
      }
    }
    setSavedRefs(refs);
    if (await api.exists(id, "generation.json")) setGeneration(await api.runJson<Generation>(id, "generation.json"));
    else setGeneration(null);
    const [hdReady, draftReady] = await Promise.all([api.exists(id, "hd/final-preview.mp4"), api.exists(id, "final-preview.mp4")]);
    if (draftReady || hdReady) {
      const prefix = hdReady ? "hd/" : "";
      const audioMode = await api
        .runJson<{ mode: string }>(id, prefix + "audio-restoration.json")
        .then((a) => a.mode)
        .catch(() => "unknown");
      setFinalPreview({ url: api.runUrl(id, prefix + "final-preview.mp4"), hd: hdReady, originalUrl: api.runUrl(id, "upload.mp4"), audioMode });
    } else setFinalPreview(null);
    setLoaded(true);
  }, []);

  const watch = useCallback(async () => {
    if (pollTimer.current) clearTimeout(pollTimer.current);
    const id = jobRef.current;
    if (!id) return;
    try {
      const next = await api.getJob(id);
      if (jobRef.current !== id) return;
      setJob(next);
      setStatus(next.status, next.state === "error" ? "error" : next.state === "running" ? "busy" : "neutral");
      if (next.state === "running") pollTimer.current = setTimeout(() => void watchRef.current(), POLL_MS);
      else await refresh();
    } catch (error) {
      setStatus((error as Error).message, "error");
    }
  }, [refresh, setStatus]);

  const pollHD = useCallback(async () => {
    const id = jobRef.current;
    if (!id) return;
    try {
      const next = await api.getHd(id);
      setHd(next);
      setUpgradeStatus(next.status);
      if (next.state === "running") setTimeout(() => void pollHdRef.current(), HD_POLL_MS);
      else await refresh();
    } catch (error) {
      setUpgradeStatus((error as Error).message);
    }
  }, [refresh]);

  useEffect(() => {
    watchRef.current = watch;
    pollHdRef.current = pollHD;
  }, [watch, pollHD]);

  /** Drop Character 2 from future requests (legacy "Remove Character 2"). */
  const omitSecondary = useCallback(() => {
    omittedSecondary.current = true;
    setSavedRefs((refs) => ({ sirio: refs.sirio }));
  }, []);

  const openJob = useCallback(
    (id: string | null) => {
      jobRef.current = id;
      omittedSecondary.current = false;
      setJobId(id);
      setJob(null);
      setPreviews([]);
      setReview(null);
      setAudioLinks([]);
      setSavedRefs({});
      setGeneration(null);
      setFinalPreview(null);
      setHd(null);
      setUpgradeStatus("");
      setLoaded(!id);
      if (!id) return;
      refresh()
        .then(watch)
        .catch((error) => setStatus((error as Error).message, "error"));
      api
        .getHd(id)
        .then((next) => {
          setHd(next);
          if (next.state === "running") pollHD();
        })
        .catch(() => {});
    },
    [pollHD, refresh, setStatus, watch],
  );

  // Initial load: capabilities + ?job= persistence (also on back/forward).
  useEffect(() => {
    api
      .capabilities()
      .then(setCapabilities)
      .catch(() => {
        setCapabilitiesError(true);
        setStatus("Configuration could not be checked. The studio remains available; verify provider setup before preparation.", "error");
      });
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the URL is external state read once on mount
    openJob(readJobFromUrl());
    const onPop = () => openJob(readJobFromUrl());
    window.addEventListener("popstate", onPop);
    return () => {
      window.removeEventListener("popstate", onPop);
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [openJob, setStatus]);

  useEffect(() => {
    if (!jobId && capabilities && !capabilities.segmentation?.ready)
      // eslint-disable-next-line react-hooks/set-state-in-effect -- mirrors the legacy readiness hint
      setStatus("UI ready. Depth preparation needs a raw-mask Space endpoint; Fast face mesh is independent.");
  }, [capabilities, jobId, setStatus]);

  /** Same as the legacy `location.href = "/?job=" + id`, without a full reload. */
  const startJob = useCallback(
    (id: string) => {
      const url = new URL(window.location.href);
      url.searchParams.set("job", id);
      window.history.pushState({}, "", url);
      openJob(id);
    },
    [openJob],
  );

  const newJob = useCallback(() => {
    const url = new URL(window.location.href);
    url.searchParams.delete("job");
    window.history.pushState({}, "", url);
    openJob(null);
    setStatus("Studio ready. Start by choosing your original video.");
  }, [openJob, setStatus]);

  const maskApproved = !!review?.approved;
  const generationSaved = !!generation;
  const awaitingQuote = job?.state === "awaiting_credit_approval";
  const preparing = !!jobId && busy && previews.length === 0;
  const collecting = !!jobId && busy && previews.length > 0;

  const unlocked = useMemo<Record<StepId, boolean>>(
    () => ({
      prepare: true,
      inspect: previews.length > 0,
      substitute: maskApproved || generationSaved || awaitingQuote,
      restore: !!finalPreview || generationSaved,
    }),
    [previews.length, maskApproved, generationSaved, awaitingQuote, finalPreview],
  );

  const complete = useMemo<Record<StepId, boolean>>(
    () => ({
      prepare: previews.length > 0,
      inspect: maskApproved,
      substitute: !!finalPreview,
      restore: false,
    }),
    [previews.length, maskApproved, finalPreview],
  );

  const furthest: StepId = finalPreview
    ? "restore"
    : generationSaved || awaitingQuote || maskApproved
      ? "substitute"
      : previews.length
        ? "inspect"
        : "prepare";

  return {
    api,
    capabilities,
    capabilitiesError,
    jobId,
    job,
    busy,
    preparing,
    collecting,
    previews,
    review,
    audioLinks,
    savedRefs,
    omitSecondary,
    generation,
    finalPreview,
    hd,
    upgradeStatus,
    setUpgradeStatus,
    status,
    setStatus,
    loaded,
    maskApproved,
    generationSaved,
    awaitingQuote,
    unlocked,
    complete,
    furthest,
    refresh,
    watch,
    pollHD,
    startJob,
    newJob,
  };
}

export type Studio = ReturnType<typeof useStudio>;

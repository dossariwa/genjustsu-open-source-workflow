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
interface JobSession {
  id: string | null;
  version: number;
}

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
  const [session, setSession] = useState<JobSession>({ id: null, version: 0 });
  const jobId = session.id;
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
  const hdPollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sessionRef = useRef(session);
  const refreshVersion = useRef(0);
  const watchVersion = useRef(0);
  const hdVersion = useRef(0);
  const omittedSecondary = useRef(false);
  const watchRef = useRef<() => Promise<void>>(async () => {});
  const pollHdRef = useRef<() => Promise<void>>(async () => {});

  const updateStatus = useCallback((text: string, tone: StatusLine["tone"] = "neutral") => setStatusState({ text, tone }), []);
  const busy = job?.state === "running";

  const clearPolls = useCallback(() => {
    if (pollTimer.current) clearTimeout(pollTimer.current);
    if (hdPollTimer.current) clearTimeout(hdPollTimer.current);
    pollTimer.current = null;
    hdPollTimer.current = null;
  }, []);

  const refresh = useCallback(async () => {
    const currentSession = sessionRef.current;
    const id = currentSession.id;
    if (!id) return;
    const version = ++refreshVersion.current;
    const current = () => sessionRef.current === currentSession && refreshVersion.current === version;
    try {
      const present = await Promise.all(PREVIEW_ITEMS.map((item) => api.exists(id, item.file)));
      if (!current()) return;
      const nextReview = await api.getMaskReview(id);
      if (!current()) return;
      const audio = await Promise.all(AUDIO_ITEMS.map((item) => api.exists(id, item.file)));
      if (!current()) return;
      const refs: { sirio?: SavedReference; tein?: SavedReference } = {};
      for (const name of ["sirio", "tein"] as const) {
        if (name === "tein" && omittedSecondary.current) continue;
        for (const ext of REFERENCE_EXTENSIONS) {
          const file = `${name}-reference.${ext}`;
          const exists = await api.exists(id, file);
          if (!current()) return;
          if (exists) {
            refs[name] = { file, url: api.runUrl(id, file), isVideo: VIDEO_EXTENSIONS.includes(ext) };
            break;
          }
        }
      }
      const generationExists = await api.exists(id, "generation.json");
      if (!current()) return;
      const nextGeneration = generationExists ? await api.runJson<Generation>(id, "generation.json") : null;
      if (!current()) return;
      const [hdReady, draftReady] = await Promise.all([api.exists(id, "hd/final-preview.mp4"), api.exists(id, "final-preview.mp4")]);
      if (!current()) return;
      let nextPreview: FinalPreview | null = null;
      if (draftReady || hdReady) {
        const prefix = hdReady ? "hd/" : "";
        const audioMode = await api
          .runJson<{ mode: string }>(id, prefix + "audio-restoration.json")
          .then((a) => a.mode)
          .catch(() => "unknown");
        nextPreview = { url: api.runUrl(id, prefix + "final-preview.mp4"), hd: hdReady, originalUrl: api.runUrl(id, "upload.mp4"), audioMode };
      }
      if (!current()) return;
      // Commit one coherent snapshot only after every read belongs to this session.
      setPreviews(PREVIEW_ITEMS.filter((_, i) => present[i]));
      setReview(nextReview);
      setAudioLinks(AUDIO_ITEMS.filter((_, i) => audio[i]));
      setSavedRefs(omittedSecondary.current ? { sirio: refs.sirio } : refs);
      setGeneration(nextGeneration);
      setFinalPreview(nextPreview);
      setLoaded(true);
    } catch (error) {
      // An old request must not report an error through its caller after navigation.
      if (current()) throw error;
    }
  }, []);

  const watch = useCallback(async () => {
    if (pollTimer.current) clearTimeout(pollTimer.current);
    pollTimer.current = null;
    const currentSession = sessionRef.current;
    const id = currentSession.id;
    if (!id) return;
    const version = ++watchVersion.current;
    const current = () => sessionRef.current === currentSession && watchVersion.current === version;
    try {
      const next = await api.getJob(id);
      if (!current()) return;
      setJob(next);
      updateStatus(next.status, next.state === "error" ? "error" : next.state === "running" ? "busy" : "neutral");
      if (next.state === "running") pollTimer.current = setTimeout(() => {
        if (current()) void watchRef.current();
      }, POLL_MS);
      else await refresh();
    } catch (error) {
      if (current()) updateStatus((error as Error).message, "error");
    }
  }, [refresh, updateStatus]);

  const pollHD = useCallback(async (refreshArtifacts = true) => {
    if (hdPollTimer.current) clearTimeout(hdPollTimer.current);
    hdPollTimer.current = null;
    const currentSession = sessionRef.current;
    const id = currentSession.id;
    if (!id) return;
    const version = ++hdVersion.current;
    const current = () => sessionRef.current === currentSession && hdVersion.current === version;
    try {
      const next = await api.getHd(id);
      if (!current()) return;
      setHd(next);
      setUpgradeStatus(next.status);
      if (next.state === "running") hdPollTimer.current = setTimeout(() => {
        if (current()) void pollHdRef.current();
      }, HD_POLL_MS);
      else if (refreshArtifacts) await refresh();
    } catch (error) {
      if (current()) setUpgradeStatus((error as Error).message);
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
      clearPolls();
      const nextSession = { id, version: sessionRef.current.version + 1 };
      sessionRef.current = nextSession;
      omittedSecondary.current = false;
      setSession(nextSession);
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
        .then(() => {
          if (sessionRef.current === nextSession) return watch();
        })
        .catch((error) => {
          if (sessionRef.current === nextSession) updateStatus((error as Error).message, "error");
        });
      void pollHD(false);
    },
    [clearPolls, pollHD, refresh, updateStatus, watch],
  );

  // Initial load: capabilities + ?job= persistence (also on back/forward).
  useEffect(() => {
    let active = true;
    api
      .capabilities()
      .then((next) => {
        if (active) setCapabilities(next);
      })
      .catch(() => {
        if (!active) return;
        setCapabilitiesError(true);
        if (!sessionRef.current.id) updateStatus("Configuration could not be checked. The studio remains available; verify provider setup before preparation.", "error");
      });
    openJob(readJobFromUrl());
    const onPop = () => openJob(readJobFromUrl());
    window.addEventListener("popstate", onPop);
    return () => {
      active = false;
      sessionRef.current = { id: null, version: sessionRef.current.version + 1 };
      window.removeEventListener("popstate", onPop);
      clearPolls();
    };
  }, [clearPolls, openJob, updateStatus]);

  useEffect(() => {
    if (!jobId && capabilities && !capabilities.segmentation?.ready)
      // eslint-disable-next-line react-hooks/set-state-in-effect -- mirrors the legacy readiness hint
      updateStatus("UI ready. Depth preparation needs a raw-mask Space endpoint; Fast face mesh is independent.");
  }, [capabilities, jobId, updateStatus]);

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
    updateStatus("Studio ready. Start by choosing your original video.");
  }, [openJob, updateStatus]);

  // Async panel handlers retain the actions for their originating job session.
  // Their late success/error paths must not refresh or change a different job.
  const actions = useMemo(() => ({
    setStatus(text: string, tone: StatusLine["tone"] = "neutral") {
      if (sessionRef.current === session) updateStatus(text, tone);
    },
    setUpgradeStatus(text: string) {
      if (sessionRef.current === session) setUpgradeStatus(text);
    },
    async refresh() {
      if (sessionRef.current === session) await refresh();
    },
    async watch() {
      if (sessionRef.current === session) await watch();
    },
    async pollHD() {
      if (sessionRef.current === session) await pollHD();
    },
    startJob(id: string) {
      if (sessionRef.current === session) startJob(id);
    },
  }), [session, updateStatus, refresh, watch, pollHD, startJob]);

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
    jobVersion: session.version,
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
    setUpgradeStatus: actions.setUpgradeStatus,
    status,
    setStatus: actions.setStatus,
    loaded,
    maskApproved,
    generationSaved,
    awaitingQuote,
    unlocked,
    complete,
    furthest,
    refresh: actions.refresh,
    watch: actions.watch,
    pollHD: actions.pollHD,
    startJob: actions.startJob,
    newJob,
  };
}

export type Studio = ReturnType<typeof useStudio>;

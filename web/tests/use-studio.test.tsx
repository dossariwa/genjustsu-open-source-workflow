import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import type { HdJob, Job, MaskReview } from "@/lib/api/types";
import { useStudio } from "@/lib/studio/use-studio";

vi.mock("@/lib/api", () => ({
  api: {
    mode: "http",
    capabilities: vi.fn(),
    exists: vi.fn(),
    getMaskReview: vi.fn(),
    getJob: vi.fn(),
    getHd: vi.fn(),
    runJson: vi.fn(),
    runUrl: (id: string, file: string) => `/runs/${id}/${file}`,
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function settle() {
  await act(async () => { await Promise.resolve(); });
}

async function navigate(id: string) {
  await act(async () => {
    window.history.pushState({}, "", `/?job=${id}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
  window.history.replaceState({}, "", "/?job=a");
  vi.mocked(api.capabilities).mockResolvedValue({ segmentation: { ready: true } });
  vi.mocked(api.exists).mockImplementation(async (_id, file) =>
    ["seedance-input.mp4", "generation.json", "final-preview.mp4"].includes(file));
  vi.mocked(api.getMaskReview).mockImplementation(async (id) => ({ approved: true, status: "approved", fingerprint: `${id}-current` }));
  vi.mocked(api.getJob).mockImplementation(async (id) => ({ id, state: "done", status: `${id} current status` }));
  vi.mocked(api.getHd).mockImplementation(async (id) => ({ state: "idle", status: `${id} current HD` }));
  vi.mocked(api.runJson).mockImplementation(async (id, file) =>
    (file === "generation.json" ? { provider: "openart", prompt: `${id} current prompt` } : { mode: "original" }) as never);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("job sessions", () => {
  it("recovers the job, review, saved request and final media from ?job=", async () => {
    const { result } = renderHook(useStudio);
    await settle();
    expect(result.current.jobId).toBe("a");
    expect(result.current.loaded).toBe(true);
    expect(result.current.review?.fingerprint).toBe("a-current");
    expect(result.current.generation?.prompt).toBe("a current prompt");
    expect(result.current.finalPreview?.url).toBe("/runs/a/final-preview.mp4");
    expect(result.current.status.text).toBe("a current status");
  });

  it.each(["b", "a"])("ignores stale artifact success after navigation to %s", async (destination) => {
    const old = deferred<MaskReview>();
    vi.mocked(api.getMaskReview).mockImplementationOnce(() => old.promise);
    const { result } = renderHook(useStudio);
    await settle();
    await navigate("b");
    if (destination === "a") await navigate("a");
    const snapshot = result.current;

    await act(async () => old.resolve({ approved: false, status: "rejected", fingerprint: "obsolete" }));
    expect(result.current.review).toBe(snapshot.review);
    expect(result.current.generation).toBe(snapshot.generation);
    expect(result.current.finalPreview).toBe(snapshot.finalPreview);
    expect(result.current.review?.fingerprint).toBe(`${destination}-current`);
    expect(result.current.finalPreview?.url).toBe(`/runs/${destination}/final-preview.mp4`);
  });

  it("ignores an artifact failure from an earlier visit to the same job", async () => {
    const old = deferred<MaskReview>();
    vi.mocked(api.getMaskReview).mockImplementationOnce(() => old.promise);
    const { result } = renderHook(useStudio);
    await settle();
    await navigate("b");
    await navigate("a");
    await act(async () => old.reject(new Error("obsolete artifact failure")));
    expect(result.current.status.text).toBe("a current status");
    expect(result.current.status.tone).toBe("neutral");
    expect(result.current.loaded).toBe(true);
  });

  it.each(["success", "error"])("ignores late job %s and cannot restart its polling after A → B → A", async (outcome) => {
    const old = deferred<Job>();
    vi.mocked(api.getJob).mockImplementationOnce(() => old.promise);
    const { result } = renderHook(useStudio);
    await settle();
    await navigate("b");
    await navigate("a");
    await act(async () => {
      if (outcome === "success") old.resolve({ state: "running", status: "obsolete running job" });
      else old.reject(new Error("obsolete job failure"));
    });
    expect(result.current.status.text).toBe("a current status");
    expect(result.current.job?.state).toBe("done");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps the newer snapshot when refreshes for one session finish out of order", async () => {
    const { result } = renderHook(useStudio);
    await settle();
    const old = deferred<MaskReview>();
    vi.mocked(api.getMaskReview).mockImplementationOnce(() => old.promise);
    let first!: Promise<void>;
    act(() => { first = result.current.refresh(); });
    await settle();
    vi.mocked(api.getMaskReview).mockResolvedValue({ approved: false, status: "rejected", fingerprint: "newer" });
    await act(async () => result.current.refresh());
    await act(async () => {
      old.resolve({ approved: true, status: "approved", fingerprint: "obsolete" });
      await first;
    });
    expect(result.current.review?.fingerprint).toBe("newer");
    expect(result.current.maskApproved).toBe(false);
  });

  it("suppresses late panel actions after their originating session is closed", async () => {
    const { result } = renderHook(useStudio);
    await settle();
    const oldActions = result.current;
    await navigate("b");
    const reads = vi.mocked(api.getJob).mock.calls.length;
    await act(async () => {
      oldActions.setStatus("obsolete action error", "error");
      oldActions.setUpgradeStatus("obsolete upgrade error");
      await oldActions.refresh();
      await oldActions.watch();
      await oldActions.pollHD();
      oldActions.startJob("c");
    });
    expect(result.current.jobId).toBe("b");
    expect(result.current.status.text).toBe("b current status");
    expect(result.current.upgradeStatus).toBe("b current HD");
    expect(api.getJob).toHaveBeenCalledTimes(reads);
  });
});

describe("HD polling lifetime", () => {
  it.each(["success", "error"])("ignores a late HD %s from an earlier visit to the same job", async (outcome) => {
    const old = deferred<HdJob>();
    vi.mocked(api.getHd).mockImplementationOnce(() => old.promise);
    const { result } = renderHook(useStudio);
    await settle();
    await navigate("b");
    await navigate("a");
    await act(async () => {
      if (outcome === "success") old.resolve({ state: "running", status: "obsolete HD work" });
      else old.reject(new Error("obsolete HD failure"));
    });
    expect(result.current.hd?.state).toBe("idle");
    expect(result.current.upgradeStatus).toBe("a current HD");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("cancels scheduled HD polls on navigation and unmount", async () => {
    vi.mocked(api.getHd).mockImplementation(async (id) => ({ state: id === "a" ? "running" : "idle", status: `${id} HD` }));
    const { result, unmount } = renderHook(useStudio);
    await settle();
    expect(vi.getTimerCount()).toBe(1);
    await navigate("b");
    const callsAfterNavigation = vi.mocked(api.getHd).mock.calls.length;
    await act(async () => vi.advanceTimersByTimeAsync(4000));
    expect(api.getHd).toHaveBeenCalledTimes(callsAfterNavigation);
    expect(vi.getTimerCount()).toBe(0);

    vi.mocked(api.getHd).mockResolvedValue({ state: "running", status: "Current HD" });
    await act(async () => result.current.pollHD());
    expect(vi.getTimerCount()).toBe(1);
    const callsBeforeUnmount = vi.mocked(api.getHd).mock.calls.length;
    unmount();
    await act(async () => vi.advanceTimersByTimeAsync(8000));
    expect(api.getHd).toHaveBeenCalledTimes(callsBeforeUnmount);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not schedule a poll when an in-flight HD response arrives after unmount", async () => {
    const pending = deferred<HdJob>();
    vi.mocked(api.getHd).mockImplementationOnce(() => pending.promise);
    const { unmount } = renderHook(useStudio);
    await settle();
    unmount();
    await act(async () => pending.resolve({ state: "running", status: "late" }));
    expect(vi.getTimerCount()).toBe(0);
  });
});

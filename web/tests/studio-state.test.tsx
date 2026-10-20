import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Studio as StudioState } from "@/lib/studio/use-studio";
import type { StudioApi } from "@/lib/api/types";
import { DEFAULT_PROMPT, PREVIEW_ITEMS } from "@/lib/studio/constants";
import { Studio } from "@/components/studio/studio";

const current = vi.hoisted(() => ({ studio: null as unknown as StudioState }));
vi.mock("@/lib/studio/use-studio", () => ({ useStudio: () => current.studio }));
vi.mock("@/lib/studio/use-hero", () => ({ useHeroBanner: () => ({}) }));
vi.mock("@/lib/studio/use-telemetry", () => ({ useTelemetry: () => ({ telemetry: {}, refreshTelemetry: vi.fn() }) }));
vi.mock("@/components/studio/top-bar", () => ({ TopBar: () => null }));
vi.mock("@/components/studio/studio-hero", () => ({ StudioHero: () => null }));

function studio(overrides: Partial<StudioState> = {}): StudioState {
  return {
    api: {
      mode: "http",
      runUrl: (id: string, file: string) => `/runs/${id}/${file}`,
      suggestPrompt: vi.fn().mockResolvedValue({ prompt: "Suggested prompt" }),
    } as unknown as StudioApi,
    capabilities: { segmentation: { ready: true } },
    capabilitiesError: false,
    jobId: "job-a",
    jobVersion: 1,
    job: { state: "done", status: "Prepared" },
    busy: false,
    preparing: false,
    collecting: false,
    previews: [...PREVIEW_ITEMS],
    review: { approved: true, status: "approved", fingerprint: "review-a" },
    audioLinks: [],
    savedRefs: {},
    omitSecondary: vi.fn(),
    generation: null,
    finalPreview: null,
    hd: null,
    upgradeStatus: "",
    setUpgradeStatus: vi.fn(),
    status: { text: "Prepared", tone: "neutral" },
    setStatus: vi.fn(),
    loaded: true,
    maskApproved: true,
    generationSaved: false,
    awaitingQuote: false,
    unlocked: { prepare: true, inspect: true, substitute: true, restore: true },
    complete: { prepare: true, inspect: true, substitute: false, restore: false },
    furthest: "prepare",
    refresh: vi.fn().mockResolvedValue(undefined),
    watch: vi.fn().mockResolvedValue(undefined),
    pollHD: vi.fn().mockResolvedValue(undefined),
    startJob: vi.fn(),
    newJob: vi.fn(),
    ...overrides,
  };
}

const openTab = (name: RegExp | string) => fireEvent.keyDown(screen.getByRole("tab", { name }), { key: "Enter" });

beforeEach(() => {
  current.studio = studio();
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
});

describe("workflow panel lifetime", () => {
  it("keeps edited prompts, identity files, selected previews and media position across tabs", () => {
    render(<Studio />);
    // Unvisited panels must not initialize prompts or start their side effects.
    expect(screen.queryByLabelText("Exact creative prompt")).not.toBeInTheDocument();

    openTab(/Substitute/);
    const prompt = screen.getByLabelText("Exact creative prompt");
    fireEvent.change(prompt, { target: { value: "Replace only the centered subject; preserve this wording." } });
    const reference = screen.getByLabelText("Character 1 reference") as HTMLInputElement;
    const identity = new File(["identity video"], "identity.mp4", { type: "video/mp4" });
    fireEvent.change(reference, { target: { files: [identity] } });

    openTab(/Inspect/);
    openTab("Mask");
    const video = document.querySelector("#input-video") as HTMLVideoElement;
    video.currentTime = 2.75;
    Object.defineProperty(video, "paused", { configurable: true, value: false });
    const pause = vi.spyOn(video, "pause").mockImplementation(() => {});

    openTab(/Substitute/);
    expect(screen.getByLabelText("Exact creative prompt")).toBe(prompt);
    expect(prompt).toHaveValue("Replace only the centered subject; preserve this wording.");
    expect(screen.getByLabelText("Character 1 reference")).toBe(reference);
    expect(reference.files?.[0]).toBe(identity);
    expect(pause).toHaveBeenCalledOnce();
    expect(video.currentTime).toBe(2.75);
    expect(video.closest("[hidden]")).not.toBeNull();

    openTab(/Inspect/);
    expect(document.querySelector("#input-video")).toBe(video);
    expect(video.currentTime).toBe(2.75);
    expect(screen.getByRole("tab", { name: "Mask" })).toHaveAttribute("aria-selected", "true");
    expect(current.studio.api.suggestPrompt).not.toHaveBeenCalled();
  });

  it("discards draft references and prompt edits when the job session changes, including a later visit to the same ID", () => {
    const { rerender } = render(<Studio />);
    openTab(/Substitute/);
    const original = screen.getByLabelText("Exact creative prompt");
    fireEvent.change(original, { target: { value: "Old job prompt" } });
    const reference = screen.getByLabelText("Character 1 reference") as HTMLInputElement;
    fireEvent.change(reference, { target: { files: [new File(["old"], "old.mp4", { type: "video/mp4" })] } });

    current.studio = studio({ jobId: "job-b", jobVersion: 2, furthest: "substitute" });
    rerender(<Studio />);
    expect(screen.getByLabelText("Exact creative prompt")).not.toBe(original);
    expect(screen.getByLabelText("Exact creative prompt")).toHaveValue(DEFAULT_PROMPT);
    expect((screen.getByLabelText("Character 1 reference") as HTMLInputElement).files).toHaveLength(0);
    fireEvent.change(screen.getByLabelText("Exact creative prompt"), { target: { value: "Second visit edits" } });

    current.studio = studio({ jobId: "job-b", jobVersion: 3, furthest: "substitute" });
    rerender(<Studio />);
    expect(screen.getByLabelText("Exact creative prompt")).toHaveValue(DEFAULT_PROMPT);
  });

  it("opens a saved job with its frozen prompt only after the artifact snapshot is loaded", () => {
    current.studio = studio({ loaded: false, furthest: "prepare" });
    const { rerender } = render(<Studio />);
    expect(screen.queryByLabelText("Exact creative prompt")).not.toBeInTheDocument();

    current.studio = studio({
      furthest: "substitute",
      generationSaved: true,
      generation: { provider: "openart", prompt: "The exact saved request.", status: "awaiting_credit_approval" },
    });
    rerender(<Studio />);
    const prompt = screen.getByLabelText("Exact creative prompt");
    expect(prompt).toHaveValue("The exact saved request.");
    expect(prompt).toHaveAttribute("readonly");
    openTab(/Inspect/);
    openTab(/Substitute/);
    expect(screen.getByLabelText("Exact creative prompt")).toBe(prompt);
    expect(prompt).toHaveValue("The exact saved request.");
  });
});

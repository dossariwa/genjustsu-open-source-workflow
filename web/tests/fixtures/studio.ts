import { vi } from "vitest";
import { httpApi } from "@/lib/api/http";
import { PREVIEW_ITEMS } from "@/lib/studio/constants";
import type { Studio } from "@/lib/studio/use-studio";

export function makeStudio(overrides: Partial<Studio> = {}): Studio {
  return {
    api: httpApi,
    capabilities: { final_audio_source: "original" },
    capabilitiesError: false,
    jobId: "test-job",
    jobVersion: 0,
    job: { state: "idle", status: "Prepared" },
    busy: false,
    preparing: false,
    collecting: false,
    previews: [PREVIEW_ITEMS[0]],
    review: { approved: true, status: "Approved" },
    audioLinks: [],
    savedRefs: {},
    omitSecondary: vi.fn(),
    generation: null,
    finalPreview: null,
    hd: null,
    upgradeStatus: "",
    setUpgradeStatus: vi.fn(),
    status: { text: "Ready", tone: "neutral" },
    setStatus: vi.fn(),
    loaded: true,
    maskApproved: true,
    generationSaved: false,
    awaitingQuote: false,
    unlocked: { prepare: true, inspect: true, substitute: true, restore: false },
    complete: { prepare: true, inspect: true, substitute: false, restore: false },
    furthest: "substitute",
    refresh: vi.fn().mockResolvedValue(undefined),
    watch: vi.fn().mockResolvedValue(undefined),
    pollHD: vi.fn().mockResolvedValue(undefined),
    startJob: vi.fn(),
    newJob: vi.fn(),
    ...overrides,
  } as Studio;
}

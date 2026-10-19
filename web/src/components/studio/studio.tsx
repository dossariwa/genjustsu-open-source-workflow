"use client";

import { useEffect, useRef, useState } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { STEPS, type StepId } from "@/lib/studio/constants";
import { useStudio } from "@/lib/studio/use-studio";
import { useHeroBanner } from "@/lib/studio/use-hero";
import { useTelemetry } from "@/lib/studio/use-telemetry";
import { TopBar } from "./top-bar";
import { StudioHero } from "./studio-hero";
import { StepTabs } from "./step-tabs";
import { PreparePanel } from "./prepare-panel";
import { InspectPanel } from "./inspect-panel";
import { SubstitutePanel } from "./substitute-panel";
import { RestorePanel } from "./restore-panel";

const ORDER: StepId[] = STEPS.map((s) => s.id);

/**
 * Desktop (≥1024px): fixed 100dvh shell, no page scroll — panel columns
 * scroll internally (Figma 1440×900 frames). Mobile: natural page scroll
 * with a sticky Back/Continue footer (Figma 390px frames).
 */
export function Studio() {
  const studio = useStudio();
  const hero = useHeroBanner();
  const { telemetry, refreshTelemetry } = useTelemetry(studio.capabilities, studio.capabilitiesError);
  const [active, setActive] = useState<StepId>("prepare");
  const lastFurthest = useRef<StepId>("prepare");
  const lastJob = useRef<string | null>(null);

  // Advance to the furthest reachable step when a job loads or a gate opens.
  // Users can always step back; going forward stays behind the server gates.
  useEffect(() => {
    if (!studio.loaded) return;
    const jobChanged = lastJob.current !== studio.jobId;
    const advanced = ORDER.indexOf(studio.furthest) > ORDER.indexOf(lastFurthest.current);
    if (jobChanged || advanced) setActive(studio.furthest);
    lastFurthest.current = studio.furthest;
    lastJob.current = studio.jobId;
  }, [studio.loaded, studio.furthest, studio.jobId]);

  useEffect(() => {
    // A locked step can never stay active (e.g. a review was revoked).
    if (!studio.unlocked[active]) setActive(ORDER.filter((s) => studio.unlocked[s]).pop() ?? "prepare"); // eslint-disable-line react-hooks/set-state-in-effect -- keeps the active tab within the gates
  }, [active, studio.unlocked]);

  const go = (step: StepId) => {
    if (!studio.unlocked[step]) return;
    setActive(step);
    if (typeof window !== "undefined" && window.innerWidth < 1024) window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <TooltipProvider delayDuration={150}>
      <a
        href="#workspace"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Skip to workflow
      </a>
      <div className="flex min-h-dvh flex-col bg-canvas lg:h-dvh lg:overflow-hidden">
        <TopBar telemetry={telemetry} onRefresh={refreshTelemetry} hero={hero} />
        <StudioHero hero={hero} />
        <StepTabs active={active} onChange={go} unlocked={studio.unlocked} complete={studio.complete} />
        <main id="workspace" className="flex min-h-0 flex-1 flex-col bg-app">
          <div className="mx-auto flex min-h-0 w-full max-w-[1440px] flex-1 flex-col px-0 pb-0 pt-1 lg:px-10 lg:pb-6 lg:pt-4">
            {active === "prepare" && <PreparePanel studio={studio} />}
            {active === "inspect" && <InspectPanel studio={studio} go={go} />}
            {active === "substitute" && <SubstitutePanel studio={studio} go={go} />}
            {active === "restore" && <RestorePanel studio={studio} go={go} />}
          </div>
        </main>
      </div>
    </TooltipProvider>
  );
}

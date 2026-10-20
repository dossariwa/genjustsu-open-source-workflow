"use client";

import { useEffect, useRef, useState } from "react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
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

/** Keep visited panels and their DOM state, but never play hidden media. */
function RetainedPanel({ active, children }: { active: boolean; children: React.ReactNode }) {
  const [visited, setVisited] = useState(false);
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (active) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- remember a visited panel without mounting unopened workflow steps
      setVisited(true);
    } else {
      container.current?.querySelectorAll<HTMLMediaElement>("video, audio").forEach((media) => {
        if (!media.paused) media.pause();
      });
    }
  }, [active]);

  return (
    <div ref={container} hidden={!active} inert={!active} className={cn("min-h-0 flex-1 flex-col", active ? "flex" : "hidden")}>
      {(active || visited) && children}
    </div>
  );
}

/** A new job session remounts this workspace so references cannot cross jobs. */
function Workflow({ studio }: { studio: ReturnType<typeof useStudio> }) {
  const [active, setActive] = useState<StepId>("prepare");
  const lastFurthest = useRef<StepId>("prepare");

  useEffect(() => {
    if (!studio.loaded) return;
    const advanced = ORDER.indexOf(studio.furthest) > ORDER.indexOf(lastFurthest.current);
    if (advanced) setActive(studio.furthest);
    lastFurthest.current = studio.furthest;
  }, [studio.loaded, studio.furthest]);

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
    <>
      <StepTabs active={active} onChange={go} unlocked={studio.unlocked} complete={studio.complete} />
      <main id="workspace" className="flex min-h-0 flex-1 flex-col bg-app">
        <div className="mx-auto flex min-h-0 w-full max-w-[1440px] flex-1 flex-col px-0 pb-0 pt-1 lg:px-10 lg:pb-6 lg:pt-4">
          <RetainedPanel active={active === "prepare"}><PreparePanel studio={studio} /></RetainedPanel>
          <RetainedPanel active={active === "inspect"}><InspectPanel studio={studio} go={go} /></RetainedPanel>
          <RetainedPanel active={active === "substitute"}><SubstitutePanel studio={studio} go={go} /></RetainedPanel>
          <RetainedPanel active={active === "restore"}><RestorePanel studio={studio} go={go} /></RetainedPanel>
        </div>
      </main>
    </>
  );
}

/**
 * Desktop (≥1024px): fixed 100dvh shell, no page scroll — panel columns
 * scroll internally (Figma 1440×900 frames). Mobile: natural page scroll
 * with a sticky Back/Continue footer (Figma 390px frames).
 */
export function Studio() {
  const studio = useStudio();
  const hero = useHeroBanner();
  const { telemetry, refreshTelemetry } = useTelemetry(studio.capabilities, studio.capabilitiesError);

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
        <Workflow key={studio.jobVersion} studio={studio} />
      </div>
    </TooltipProvider>
  );
}

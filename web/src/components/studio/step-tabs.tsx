"use client";

import { Check, Lock } from "lucide-react";
import { cn } from "@/lib/utils";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { STEPS, type StepId } from "@/lib/studio/constants";

/**
 * Figma "StepTabs" (shadcn Tabs · TabsList). A tab is locked until the
 * previous gate is satisfied; locked tabs explain the prerequisite.
 */
export function StepTabs({
  active,
  onChange,
  unlocked,
  complete,
}: {
  active: StepId;
  onChange: (step: StepId) => void;
  unlocked: Record<StepId, boolean>;
  complete: Record<StepId, boolean>;
}) {
  const current = STEPS.findIndex((s) => s.id === active);
  return (
    <nav aria-label="Workflow" className="border-b bg-canvas">
      <Tabs value={active} onValueChange={(value) => onChange(value as StepId)} className="mx-auto w-full max-w-[1440px] px-3 py-2 lg:px-10">
        <TabsList variant="line" className="grid h-auto! w-full grid-cols-4 gap-1 p-0 lg:gap-2">
          {STEPS.map((step) => {
            const locked = !unlocked[step.id];
            const done = complete[step.id] && step.id !== active;
            const trigger = (
              <TabsTrigger
                key={step.id}
                value={step.id}
                disabled={locked}
                aria-disabled={locked}
                data-locked={locked || undefined}
                className={cn(
                  "h-auto! flex-col items-center gap-1 rounded-lg px-1 py-2 text-left after:bottom-[-1px]! after:h-0.5! after:bg-crimson! lg:flex-row lg:justify-start lg:gap-3 lg:px-3 lg:py-3",
                  "data-active:bg-elevated! w-full data-locked:pointer-events-none data-locked:opacity-100",
                )}
              >
                <span
                  className={cn(
                    "grid size-8 shrink-0 place-items-center rounded-full border font-mono text-[11px]",
                    active === step.id && "border-crimson bg-crimson text-white",
                    done && "border-success/60 bg-success/10 text-success-text",
                    locked && "border-border bg-muted text-disabled",
                    !locked && !done && active !== step.id && "border-strong text-muted-foreground",
                  )}
                  aria-hidden
                >
                  {done ? <Check className="size-4" /> : locked ? <Lock className="size-3.5" /> : step.index}
                </span>
                <span className="flex min-w-0 flex-col items-center lg:items-start">
                  <span className={cn("text-[11px] font-medium lg:text-sm", locked ? "text-disabled" : "text-foreground")}>
                    <span className="lg:hidden">{step.short}</span>
                    <span className="hidden lg:inline">{step.title}</span>
                  </span>
                  <span className="label-mono-sm hidden text-muted-foreground lg:block">
                    <span className="text-crimson-text">{step.kanji}</span> {locked ? "LOCKED" : step.tag}
                  </span>
                </span>
                <span className="sr-only">{locked ? ` — ${step.lockedHint}` : done ? " — complete" : ""}</span>
              </TabsTrigger>
            );
            if (!locked) return trigger;
            return (
              <Tooltip key={step.id}>
                <TooltipTrigger asChild>
                  <span className="block cursor-not-allowed rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring" tabIndex={0}>
                    {trigger}
                  </span>
                </TooltipTrigger>
                <TooltipContent side="bottom" sideOffset={6} className="bg-foreground text-background">
                  {step.lockedHint}
                </TooltipContent>
              </Tooltip>
            );
          })}
        </TabsList>
      </Tabs>
      <p className="label-mono-sm px-4 pb-2 text-muted-foreground lg:hidden" aria-live="polite">
        Step {current + 1} of 4 · {STEPS[current].title}
      </p>
    </nav>
  );
}

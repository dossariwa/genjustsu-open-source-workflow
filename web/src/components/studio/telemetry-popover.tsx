"use client";

import { useState } from "react";
import { Activity, ExternalLink, ImageIcon, RefreshCw, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import type { TelemetryView } from "@/lib/studio/use-telemetry";
import type { HeroBanner } from "@/lib/studio/use-hero";
import { API_MODE } from "@/lib/api";
import { readScenarios, resetMock, writeScenarios, type MockScenarios } from "@/lib/mock/api";

function Item({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="rounded-md bg-inset px-3 py-2.5">
      <span className="label-mono-sm block text-muted-foreground">{label}</span>
      <strong className="block truncate text-sm font-medium" title={value}>
        {value}
      </strong>
      <small className="block text-xs text-muted-foreground">{detail}</small>
    </div>
  );
}

function MockControls() {
  const [scenarios, setScenarios] = useState<MockScenarios>(() => readScenarios());
  const toggle = (key: keyof MockScenarios, value: boolean) => {
    const next = { ...scenarios, [key]: value };
    setScenarios(next);
    writeScenarios(next);
  };
  return (
    <div className="space-y-2 rounded-md border border-dashed border-info/50 p-3">
      <span className="label-mono-sm block text-info-text">MOCK API · PREVIEW SCENARIOS</span>
      <div className="flex items-start gap-2">
        <Checkbox id="mock-reject" checked={scenarios.rejectNextUpload} onCheckedChange={(v) => toggle("rejectNextUpload", v === true)} />
        <Label htmlFor="mock-reject" className="text-xs font-normal leading-4">
          Server rejects the next depth upload (400 · over the limit)
        </Label>
      </div>
      <div className="flex items-start gap-2">
        <Checkbox id="mock-fail" checked={scenarios.failNextCollection} onCheckedChange={(v) => toggle("failNextCollection", v === true)} />
        <Label htmlFor="mock-fail" className="text-xs font-normal leading-4">
          Next result collection fails (shows “Resume result collection”)
        </Label>
      </div>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => {
          resetMock();
          window.location.href = window.location.pathname;
        }}
      >
        <RotateCcw /> Reset mock jobs
      </Button>
    </div>
  );
}

/** Figma "TelemetryPopover": provider telemetry + hero banner controls. */
export function TelemetryPopover({
  telemetry,
  onRefresh,
  hero,
}: {
  telemetry: TelemetryView;
  onRefresh: () => void;
  hero: HeroBanner;
}) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="lg" aria-label="Studio status" className="gap-2">
          <Activity />
          <span className="hidden sm:inline">Studio status</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={8} className="max-h-[calc(100dvh-80px)] w-[min(380px,calc(100vw-24px))] overflow-y-auto p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">Studio status</h2>
          <Button variant="ghost" size="sm" onClick={onRefresh} disabled={telemetry.checking}>
            Refresh status <RefreshCw className={telemetry.checking ? "animate-spin" : ""} />
          </Button>
        </div>
        <section aria-label="Provider telemetry" className="space-y-2">
          <Item label="OPENART / MCP" value={telemetry.account} detail={telemetry.accountDetail} />
          <Item label="DRAFT ENGINE" value={telemetry.model} detail={telemetry.modelDetail} />
          <Item label="RAW MASKS / HUGGING FACE" value={telemetry.sam} detail={telemetry.samDetail} />
          <Item label="ELEVENLABS / GUIDANCE" value={telemetry.voice} detail={telemetry.voiceDetail} />
        </section>
        <p className="mt-3 text-[13px] leading-[18px] text-muted-foreground">
          Account access and configured adapters do not establish live generation readiness. Each draft requires review and a fresh
          credit quote.
        </p>
        <Separator className="my-3" />
        <span className="label-mono-sm block text-muted-foreground">HERO BANNER</span>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Button variant="outline" size="lg" asChild>
            <label>
              <ImageIcon /> Customize banner
              <input
                type="file"
                className="sr-only"
                accept="image/png,image/jpeg,image/webp,image/gif"
                aria-label="Custom hero banner or GIF"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file) hero.upload(file);
                }}
              />
            </label>
          </Button>
          <Button variant="ghost" size="lg" onClick={hero.reset}>
            <RotateCcw /> Reset
          </Button>
          <Button variant="link" size="lg" asChild className="text-muted-foreground">
            <a href="https://www.pinterest.com/pin/1100215383975104972/" target="_blank" rel="noopener noreferrer">
              Pinterest <ExternalLink />
            </a>
          </Button>
        </div>
        <p role="status" className="mt-2 text-xs text-muted-foreground">
          {hero.statusText}
        </p>
        {API_MODE === "mock" && (
          <>
            <Separator className="my-3" />
            <MockControls />
          </>
        )}
      </PopoverContent>
    </Popover>
  );
}

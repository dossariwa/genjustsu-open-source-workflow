"use client";

import { useState } from "react";
import { ArrowLeft, ArrowRight, Download, Lock, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import type { Studio } from "@/lib/studio/use-studio";
import type { StepId } from "@/lib/studio/constants";
import { FooterHint, Panel, PanelColumns } from "./panel";
import { MaskReviewGate } from "./mask-review-gate";

export function InspectPanel({ studio, go }: { studio: Studio; go: (step: StepId) => void }) {
  const { api, jobId, previews, audioLinks, status, unlocked, maskApproved } = studio;
  const [selected, setSelected] = useState<string>("");
  const active = previews.find((p) => p.file === selected) ?? previews[0];

  return (
    <Panel
      id="review"
      number="02"
      eyebrow="眼 / FULL-CLIP VISUAL GATE"
      title="Inspect every frame"
      badge="SHA-256 BOUND"
      badgeTone="info"
      status={status}
      footer={
        <>
          <Button variant="outline" size="lg" className="h-10" onClick={() => go("prepare")}>
            <ArrowLeft /> <span className="hidden sm:inline">Back to Prepare</span>
            <span className="sm:hidden">Back</span>
          </Button>
          <FooterHint>Progress is saved to this job (?job=). You can go back without losing the prepared artifacts.</FooterHint>
          <Button size="lg" className="ml-auto h-10" disabled={!unlocked.substitute} onClick={() => go("substitute")}>
            <span className="hidden sm:inline">Continue to Substitute</span>
            <span className="sm:hidden">Continue</span>
            {maskApproved ? <ArrowRight /> : <Lock />}
          </Button>
        </>
      }
    >
      <PanelColumns
        main={
          !active ? (
            <div className="grid min-h-[260px] flex-1 place-items-center rounded-xl border border-dashed bg-inset p-6 text-center">
              <div>
                <span className="label-mono-sm text-muted-foreground">02 / 眼</span>
                <strong className="mt-1 block">Your prepared input belongs here.</strong>
                <span className="text-[13px] text-muted-foreground">Original, depth, raw mask and guidance previews appear after preparation.</span>
              </div>
            </div>
          ) : (
            <>
              <Tabs value={active.file} onValueChange={setSelected}>
                <TabsList aria-label="Preview selection" className="h-auto! min-h-9 max-w-full flex-wrap bg-inset sm:h-9! sm:flex-nowrap">
                  {previews.map((item) => (
                    <TabsTrigger key={item.file} value={item.file} className="px-3">
                      {item.label}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>
              <div className="overflow-hidden rounded-xl border bg-canvas">
                <video
                  key={active.file}
                  id="input-video"
                  className="aspect-video w-full bg-canvas"
                  src={jobId ? api.runUrl(jobId, active.file) : undefined}
                  controls
                  playsInline
                  preload="metadata"
                />
              </div>
              <div className="flex items-center justify-between gap-3 text-[13px]">
                <span id="input-caption" className="text-muted-foreground">
                  {active.caption}
                </span>
                <a
                  id="input-download"
                  className="inline-flex items-center gap-1 text-crimson-text hover:underline"
                  href={jobId ? api.runUrl(jobId, active.file) : undefined}
                  download
                >
                  Download video <Download className="size-3.5" />
                </a>
              </div>
            </>
          )
        }
        aside={
          <>
            <MaskReviewGate studio={studio} />
            <Accordion type="single" collapsible className="rounded-lg border px-3">
              <AccordionItem value="audio" className="border-none">
                <AccordionTrigger className="py-3 hover:no-underline">
                  <span className="flex items-center gap-2">
                    <SlidersHorizontal className="size-4 text-muted-foreground" aria-hidden />
                    Audio & transcript downloads
                    <span className="font-normal text-muted-foreground">Guidance vocals · transcript</span>
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  <div id="audio-links" className="flex flex-wrap gap-2">
                    {audioLinks.length === 0 && <span className="text-[13px] text-muted-foreground">No audio artifacts yet.</span>}
                    {jobId &&
                      audioLinks.map((item) => (
                        <Button key={item.file} variant="outline" size="sm" asChild>
                          <a href={api.runUrl(jobId, item.file)} download={item.file}>
                            {item.title} <Download />
                          </a>
                        </Button>
                      ))}
                  </div>
                </AccordionContent>
              </AccordionItem>
            </Accordion>
          </>
        }
      />
    </Panel>
  );
}

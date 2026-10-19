"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowRight, FileVideo, Info, LoaderCircle, SlidersHorizontal, Upload, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import type { PreparationMode } from "@/lib/api";
import { MODE_OPTIONS } from "@/lib/studio/constants";
import { checkDuration, clipLimit, depthLimitMessage, describeLimit, isDepthMode } from "@/lib/studio/limits";
import type { Studio } from "@/lib/studio/use-studio";
import { FooterHint, Hint, Panel, PanelColumns } from "./panel";
import { IndeterminateProgress } from "./indeterminate-progress";
import { ToneBadge } from "./tone-badge";

export function PreparePanel({ studio }: { studio: Studio }) {
  const { api, capabilities, busy, preparing, status, setStatus, startJob } = studio;
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<PreparationMode>("depth");
  const [subject, setSubject] = useState("person");
  const [duration, setDuration] = useState<number | null>(null);
  const [durationNote, setDurationNote] = useState("Choose a clip to check its duration locally.");
  const [serverError, setServerError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const metadataVersion = useRef(0);
  const input = useRef<HTMLInputElement>(null);

  const check = useMemo(() => checkDuration(duration, mode, capabilities), [duration, mode, capabilities]);
  const limit = clipLimit(capabilities, mode);
  const modeInfo = MODE_OPTIONS.find((m) => m.value === mode)!;

  // Local duration feedback only; FastAPI re-validates with PyAV.
  useEffect(() => {
    input.current?.setCustomValidity(check?.invalid ? depthLimitMessage(capabilities) : "");
  }, [check, capabilities]);

  function choose(next: File | null) {
    const version = ++metadataVersion.current;
    setFile(next);
    setDuration(null);
    setServerError(null);
    setDurationNote(next ? "Reading clip duration locally…" : "Choose a clip to check its duration locally.");
    if (!next) return;
    const media = document.createElement("video");
    const url = URL.createObjectURL(next);
    media.preload = "metadata";
    const clean = () => {
      URL.revokeObjectURL(url);
      media.removeAttribute("src");
      media.load();
    };
    media.onloadedmetadata = () => {
      if (version === metadataVersion.current) {
        const seconds = Number.isFinite(media.duration) ? media.duration : null;
        setDuration(seconds);
        if (seconds === null) setDurationNote("Duration unavailable locally; the backend will validate the source.");
      }
      clean();
    };
    media.onerror = () => {
      if (version === metadataVersion.current) setDurationNote("Duration unavailable locally; the backend will validate the source.");
      clean();
    };
    media.src = url;
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || check?.invalid) return;
    setSubmitting(true);
    setServerError(null);
    try {
      setStatus("Uploading and preparing your video…", "busy");
      const form = new FormData();
      form.set("video", file);
      form.set("mode", mode);
      form.set("prompt", subject);
      form.set("provider", "huggingface");
      const job = await api.createJob(form);
      startJob(job.id);
    } catch (error) {
      const message = (error as Error).message;
      setServerError(message);
      setStatus(message, "error");
    } finally {
      setSubmitting(false);
    }
  }

  const working = submitting || preparing;
  const durationText = check?.message ?? durationNote;
  const durationTone = check?.invalid ? "error" : check?.warning ? "warning" : check ? "success" : "neutral";

  return (
    <form id="form" onSubmit={submit} className="contents">
      <Panel
        id="source"
        number="01"
        eyebrow="源 / SOURCE VESSEL"
        title="Upload clip & choose your jutsu"
        badge="PREPARATION"
        status={status}
        footer={
          <>
            <FooterHint>
              ElevenLabs isolation + Scribe · embedded +3 semitone guidance by default. Optional configured voice conversion. No
              standalone audio references.
            </FooterHint>
            <Button id="go" type="submit" size="lg" className="ml-auto h-10 px-4" disabled={!file || busy || working || !!check?.invalid}>
              {working ? (
                <>
                  <LoaderCircle className="animate-spin" /> Preparing…
                </>
              ) : (
                <>
                  Prepare video <ArrowRight />
                </>
              )}
            </Button>
          </>
        }
      >
        <PanelColumns
          main={
            <>
              <label
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragging(false);
                  const dropped = e.dataTransfer.files[0];
                  if (dropped && input.current) {
                    const transfer = new DataTransfer();
                    transfer.items.add(dropped);
                    input.current.files = transfer.files;
                    choose(dropped);
                  }
                }}
                className={cn(
                  "relative flex min-h-[220px] flex-1 cursor-pointer flex-col items-center justify-center gap-2 overflow-hidden rounded-xl border border-dashed border-strong bg-inset p-6 text-center transition-colors lg:min-h-[300px]",
                  dragging && "border-crimson bg-crimson/5",
                  check?.invalid && "border-danger-text/70",
                  serverError && "border-danger-text/70",
                  file && !check?.invalid && !serverError && "border-solid",
                  working && "pointer-events-none",
                )}
              >
                {working ? (
                  <div className="flex w-full max-w-[320px] flex-col items-center gap-3">
                    <LoaderCircle className="size-6 animate-spin text-info" aria-hidden />
                    <strong className="text-sm font-medium">{submitting ? "Uploading and preparing your video…" : status.text}</strong>
                    <IndeterminateProgress label="Preparation in progress" />
                  </div>
                ) : (
                  <>
                    <span className="grid size-10 place-items-center rounded-full border bg-elevated" aria-hidden>
                      <Upload className="size-4" />
                    </span>
                    <strong className="text-sm font-medium">{file ? "Replace original video" : "Choose original video"}</strong>
                    <small className="text-[13px] text-muted-foreground">MP4 or MOV · your source stays intact</small>
                    <span className="mt-1 inline-flex h-9 items-center rounded-lg border bg-elevated px-3 text-sm font-medium">
                      Choose file
                    </span>
                  </>
                )}
                <input
                  ref={input}
                  aria-label="Original video"
                  required
                  type="file"
                  name="video"
                  accept="video/*"
                  className="absolute inset-0 cursor-pointer opacity-0"
                  disabled={working}
                  onChange={(e) => choose(e.target.files?.[0] ?? null)}
                />
                {file && (
                  <div className="absolute inset-x-3 bottom-3 flex items-center gap-2 rounded-lg border bg-elevated px-3 py-2 text-left text-sm">
                    <FileVideo className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="min-w-0 flex-1 truncate" data-filename>
                      {file.name}
                    </span>
                    {duration !== null && (
                      <ToneBadge tone={check?.invalid ? "danger" : check?.warning ? "warning" : "success"}>{duration.toFixed(2)}S</ToneBadge>
                    )}
                  </div>
                )}
              </label>
              <Hint>The full soundtrack is preserved for the final export. Preparation uploads media to the configured cloud providers.</Hint>
            </>
          }
          aside={
            <>
              <div className="space-y-2">
                <Label htmlFor="mode">Preparation mode</Label>
                <Select value={mode} onValueChange={(v) => setMode(v as PreparationMode)} disabled={working} name="mode">
                  <SelectTrigger id="mode" className="h-10! w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {MODE_OPTIONS.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Hint id="mode-description">{modeInfo.description}</Hint>
              {isDepthMode(mode) ? (
                <Alert id="duration-warning" className="border-warning/70 bg-warning-subtle text-warning-text">
                  <AlertTriangle />
                  <AlertTitle className="label-mono text-warning-text">DEPTH MODE LIMIT</AlertTitle>
                  <AlertDescription className="text-[13px] text-foreground/90">
                    {limit && describeLimit(limit)} · Applies to Depth + SAM and Combined Depth + Mesh (SAM3).{" "}
                    {capabilities?.clip_limits ? "Value read from /capabilities." : "Default value; /capabilities did not report a limit."}
                  </AlertDescription>
                </Alert>
              ) : (
                <Alert className="border-info/60 bg-info/5 text-info-text">
                  <Info />
                  <AlertTitle className="label-mono text-info-text">FAST · FACE MESH</AlertTitle>
                  <AlertDescription className="text-[13px] text-foreground/90">
                    No depth frame limit. {limit ? `Seedance drafts accept up to ${limit.max_seconds.toFixed(0)} seconds.` : ""} Provider
                    duration limits still apply.
                  </AlertDescription>
                </Alert>
              )}
              {serverError && (
                <Alert className="border-danger-text/60 bg-danger-text/5 text-danger-text">
                  <XCircle />
                  <AlertTitle>Rejected by the server</AlertTitle>
                  <AlertDescription className="text-[13px] text-foreground/90">{serverError}</AlertDescription>
                </Alert>
              )}
              <p
                id="duration-status"
                role="status"
                data-invalid={String(!!check?.invalid)}
                className={cn(
                  "flex items-center gap-2 text-[13px]",
                  durationTone === "error" && "text-danger-text",
                  durationTone === "warning" && "text-warning-text",
                  durationTone === "success" && "text-muted-foreground",
                  durationTone === "neutral" && "text-muted-foreground",
                )}
              >
                <span
                  className={cn(
                    "size-1.5 rounded-full",
                    durationTone === "error" ? "bg-danger-text" : durationTone === "warning" ? "bg-warning" : durationTone === "success" ? "bg-success" : "bg-muted-foreground",
                  )}
                  aria-hidden
                />
                {durationText}
              </p>
              <Accordion type="single" collapsible className="rounded-lg border px-3">
                <AccordionItem value="settings" className="border-none">
                  <AccordionTrigger className="py-3 hover:no-underline">
                    <span className="flex items-center gap-2">
                      <SlidersHorizontal className="size-4 text-muted-foreground" aria-hidden />
                      Preparation settings <span className="font-normal text-muted-foreground">Subject & depth provider</span>
                    </span>
                  </AccordionTrigger>
                  <AccordionContent className="grid gap-4 sm:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label htmlFor="subject">Subject to replace</Label>
                      <Input id="subject" name="prompt" required value={subject} onChange={(e) => setSubject(e.target.value)} disabled={working} />
                      <Hint>“Person” includes all detected people. Describe the actual target: person, creature, or object.</Hint>
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="provider">Depth provider</Label>
                      <Select value="huggingface" name="provider" disabled={working}>
                        <SelectTrigger id="provider" className="w-full">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="huggingface">Hugging Face · Video Depth Anything</SelectItem>
                        </SelectContent>
                      </Select>
                      <Hint>Preparation runs at 24fps, up to 960px. Depth colors remain unchanged.</Hint>
                    </div>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            </>
          }
        />
      </Panel>
    </form>
  );
}

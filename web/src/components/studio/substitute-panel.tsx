"use client";
/* eslint-disable @next/next/no-img-element -- local blob: previews and run artifacts in a static export */

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, ImageIcon, Lock, LoaderCircle, RefreshCw, RotateCcw, SlidersHorizontal, Sparkles, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { DEFAULT_PROMPT, type StepId } from "@/lib/studio/constants";
import type { SavedReference, Studio } from "@/lib/studio/use-studio";
import { FooterHint, Hint, Panel, PanelColumns } from "./panel";
import { CreditGate } from "./credit-gate";
import { IndeterminateProgress } from "./indeterminate-progress";
import { ManualImport } from "./manual-import";
import { ToneBadge } from "./tone-badge";

type Slot = "sirio" | "tein";

function ReferenceCard({
  slot,
  file,
  saved,
  omitted,
  disabled,
  onSelect,
}: {
  slot: Slot;
  file: File | null;
  saved?: SavedReference;
  omitted: boolean;
  disabled: boolean;
  onSelect: (file: File | null) => void;
}) {
  const [preview, setPreview] = useState<string | null>(null);
  useEffect(() => {
    if (!file || file.type.startsWith("video/")) {
      setPreview(null); // eslint-disable-line react-hooks/set-state-in-effect -- object URL lifecycle follows the selected file
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  const image = preview ?? (saved && !saved.isVideo && !file ? saved.url : null);
  const primary = slot === "sirio";
  const detail = file
    ? `${file.name} · appearance only`
    : saved
      ? "Saved reference · click to replace"
      : omitted
        ? "No second character"
        : primary
          ? "Image or identity video · appearance only"
          : "Image reference · only for a second subject";
  return (
    <label
      className={cn(
        "relative flex min-h-[150px] cursor-pointer flex-col overflow-hidden rounded-xl border bg-inset lg:min-h-[138px]",
        !image && "border-dashed border-strong",
        disabled && "cursor-not-allowed opacity-80",
      )}
    >
      {image ? (
        <img src={image} alt={`Character ${primary ? 1 : 2} reference`} className="h-24 w-full object-cover" />
      ) : (
        <span className="grid flex-1 place-items-center pt-4" aria-hidden>
          <ImageIcon className="size-4 text-muted-foreground" />
        </span>
      )}
      <span className={cn("flex flex-col gap-0.5 p-3", !image && "items-center text-center")}>
        <span className="label-mono-sm text-crimson-text">TARGET / 0{primary ? 1 : 2}</span>
        <strong className="text-sm font-medium">{primary ? "Character 1 · required" : "Character 2 · optional"}</strong>
        <small className="truncate text-xs text-muted-foreground" data-filename>
          {detail}
        </small>
      </span>
      <input
        type="file"
        name={slot}
        aria-label={`Character ${primary ? 1 : 2} reference`}
        accept={primary ? "image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm" : "image/png,image/jpeg,image/webp"}
        className="absolute inset-0 cursor-pointer opacity-0 disabled:cursor-not-allowed"
        disabled={disabled}
        onChange={(e) => onSelect(e.target.files?.[0] ?? null)}
      />
    </label>
  );
}

export function SubstitutePanel({ studio, go }: { studio: Studio; go: (step: StepId) => void }) {
  const {
    api,
    jobId,
    job,
    busy,
    collecting,
    previews,
    capabilities,
    generation,
    generationSaved,
    maskApproved,
    awaitingQuote,
    savedRefs,
    omitSecondary,
    finalPreview,
    status,
    setStatus,
    refresh,
    watch,
  } = studio;
  const [files, setFiles] = useState<Record<Slot, File | null>>({ sirio: null, tein: null });
  const [omitted, setOmitted] = useState(false);
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [promptTouched, setPromptTouched] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [resuming, setResuming] = useState<"prep" | "gen" | null>(null);
  const referenceVersion = useRef(0);
  const loadedPrompt = useRef(false);
  const touchedRef = useRef(false);
  const latest = useRef({ files, omitted, savedRefs });
  useEffect(() => {
    latest.current = { files, omitted, savedRefs };
  }, [files, omitted, savedRefs]);

  // A saved generation freezes its prompt; show what was sent.
  useEffect(() => {
    if (generation?.prompt && !loadedPrompt.current && !touchedRef.current) {
      loadedPrompt.current = true;
      setPrompt(generation.prompt);
    }
  }, [generation]);

  const legacyProvider = generation?.provider === "dreamina-canvas" || generation?.mode === "m2v";
  const providerLabel = generationSaved ? (legacyProvider ? "Dreamina Canvas · saved job" : "OpenArt") : "OpenArt";
  const modeLabel = generationSaved
    ? generation?.mode_label || (legacyProvider ? "Seedance · Omni (m2v)" : "Seedance 2.5 Draft · Reference video (element2video)")
    : files.sirio
      ? "Seedance 2.5 Draft · Reference video"
      : "Seedance 2.5 Draft · Reference video (element2video)";
  const resolution = generationSaved ? `Quality · ${generation?.resolution || "unverified"} draft` : "Quality · 480p draft";
  const gen = capabilities?.generation ?? {};
  const providerStatus =
    gen.detail ||
    (gen.available === true
      ? "OpenArt connection configured. Generation requires your approved credit quote."
      : capabilities
        ? "OpenArt reference-video contract configured. Check the account telemetry; each submission validates the live model schema."
        : "Checking the configured OpenArt connection…");

  async function referenceData(): Promise<FormData> {
    const { files: current, omitted: skip, savedRefs: saved } = latest.current;
    const data = new FormData();
    for (const name of ["sirio", "tein"] as const) {
      if (name === "tein" && skip) continue;
      const file = current[name];
      if (file) data.set(name, file);
      else if (saved[name] && jobId) data.set(name, new File([await api.runBlob(jobId, saved[name]!.file)], saved[name]!.file));
      else if (name === "sirio") throw Error("Choose Character 1 reference first.");
    }
    return data;
  }

  async function suggestPrompt(explicit: boolean) {
    if (!jobId || suggesting || generationSaved) return;
    const previous = prompt;
    const version = referenceVersion.current;
    try {
      setSuggesting(true);
      const data = await referenceData();
      const result = await api.suggestPrompt(jobId, data);
      if (referenceVersion.current === version && (explicit || !touchedRef.current)) {
        setPrompt((value) => (value === previous ? result.prompt : value));
        touchedRef.current = false;
        setPromptTouched(false);
        setStatus("Prompt suggested. Verify the transcript, mapping and exact wording before submission.");
      }
    } catch (error) {
      setStatus((error as Error).message, "error");
    } finally {
      setSuggesting(false);
    }
  }

  function select(slot: Slot, file: File | null) {
    referenceVersion.current++;
    if (slot === "tein") setOmitted(false);
    setFiles((current) => ({ ...current, [slot]: file }));
    latest.current = { ...latest.current, files: { ...latest.current.files, [slot]: file }, omitted: slot === "tein" ? false : latest.current.omitted };
    if (file && jobId && !touchedRef.current && !file.type.startsWith("video/")) void suggestPrompt(false);
  }

  function removeSecondary() {
    setOmitted(true);
    omitSecondary();
    referenceVersion.current++;
    setFiles((current) => ({ ...current, tein: null }));
    latest.current = { ...latest.current, omitted: true, files: { ...latest.current.files, tein: null }, savedRefs: { sirio: latest.current.savedRefs.sirio } };
    if (!touchedRef.current) void suggestPrompt(false);
  }

  async function submitDraft() {
    if (!jobId) return;
    if (!maskApproved) {
      setStatus("Review and approve the mask first.", "error");
      return;
    }
    setSubmitting(true);
    try {
      const data = await referenceData();
      data.set("prompt", prompt);
      setStatus("Preparing your OpenArt Seedance 2.5 Draft and credit quote…", "busy");
      await api.seedance(jobId, data);
      await watch();
    } catch (error) {
      await refresh().catch(() => {});
      setStatus((error as Error).message, "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function resumePreparation() {
    if (!jobId) return;
    setResuming("prep");
    try {
      await api.resumePreparation(jobId);
      await watch();
    } catch (error) {
      setStatus((error as Error).message, "error");
    } finally {
      setResuming(null);
    }
  }

  async function resumeGeneration() {
    if (!jobId) return;
    setResuming("gen");
    try {
      await api.resume(jobId);
      await watch();
    } catch (error) {
      setStatus((error as Error).message, "error");
    } finally {
      setResuming(null);
    }
  }

  const draftDisabled = generationSaved || busy || previews.length === 0 || !maskApproved || submitting;
  const showResumePrep = generationSaved && !legacyProvider && generation?.status === "preparing";
  const showResumeGen = job?.state === "error";
  const locked = generationSaved;
  const ceiling = generation?.approved_credit_ceiling;

  const footerAction = finalPreview ? (
    <Button size="lg" className="ml-auto h-10" onClick={() => go("restore")}>
      <span className="hidden sm:inline">Continue to Restore & Export</span>
      <span className="sm:hidden">Continue</span> <ArrowRight />
    </Button>
  ) : collecting ? (
    <Button size="lg" className="ml-auto h-10" disabled>
      <LoaderCircle className="animate-spin" /> Waiting for draft…
    </Button>
  ) : awaitingQuote || generationSaved ? (
    <Button size="lg" variant="outline" className="ml-auto h-10" disabled>
      <span className="hidden sm:inline">Continue to Restore & Export</span>
      <span className="sm:hidden">Continue</span> <Lock />
    </Button>
  ) : (
    <Button id="draft-button" size="lg" className="ml-auto h-10" disabled={draftDisabled} onClick={submitDraft}>
      {submitting ? <LoaderCircle className="animate-spin" /> : null}
      <span className="hidden sm:inline">Prepare draft & get quote</span>
      <span className="sm:hidden">Get quote</span> <ArrowRight />
    </Button>
  );

  const promptField = (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3">
        <Label htmlFor="prompt">Exact creative prompt</Label>
        <ToneBadge tone="warning">{locked ? "FROZEN · SAVED REQUEST" : "REVIEW BEFORE SUBMITTING"}</ToneBadge>
      </div>
      <Textarea
        id="prompt"
        name="prompt"
        required
        rows={8}
        value={prompt}
        readOnly={locked}
        onChange={(e) => {
          touchedRef.current = true;
          setPromptTouched(true);
          setPrompt(e.target.value);
        }}
        className="min-h-[150px] resize-y bg-inset text-[13px] leading-5 lg:min-h-[148px]"
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="outline"
          size="lg"
          id="suggest-prompt"
          disabled={suggesting || generationSaved || !jobId}
          onClick={() => suggestPrompt(true)}
        >
          {suggesting ? <LoaderCircle className="animate-spin" /> : <Sparkles />} Suggest prompt with OpenAI
        </Button>
        <Hint className="min-w-0 basis-full sm:flex-1">
          Image references only. Verify Scribe dialogue and identity mapping.{promptTouched ? " Edited by you." : ""}
        </Hint>
      </div>
    </div>
  );

  return (
    <Panel
      id="draft"
      number="03"
      eyebrow="術 / KAWARIMI TARGETS"
      title="Choose the replacement identity"
      badge="480P DRAFT"
      status={status}
      footer={
        <>
          <Button variant="outline" size="lg" className="h-10" onClick={() => go("inspect")}>
            <ArrowLeft /> <span className="hidden sm:inline">Back to Inspect</span>
            <span className="sm:hidden">Back</span>
          </Button>
          <FooterHint>
            {finalPreview
              ? "Draft ready · compare and download it in Restore & Export."
              : collecting
                ? "Restore & Export unlocks automatically when the draft is ready."
                : awaitingQuote
                  ? "Nothing is generated until you approve the quoted credits."
                  : "The current artifact review must be approved. Generation waits for your explicit credit quote approval."}
          </FooterHint>
          {footerAction}
        </>
      }
    >
      <PanelColumns
        main={
          <>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
              <ToneBadge>{providerLabel.toUpperCase()}</ToneBadge>
              <span id="mode-label">{modeLabel}</span>
              <span id="draft-resolution" className="text-muted-foreground">
                · {resolution}
              </span>
            </div>
            <Hint id="provider-status">{providerStatus}</Hint>
            <div className="grid gap-3 sm:grid-cols-2">
              <ReferenceCard slot="sirio" file={files.sirio} saved={savedRefs.sirio} omitted={false} disabled={locked} onSelect={(f) => select("sirio", f)} />
              <ReferenceCard
                slot="tein"
                file={files.tein}
                saved={omitted ? undefined : savedRefs.tein}
                omitted={omitted}
                disabled={locked}
                onSelect={(f) => select("tein", f)}
              />
            </div>
            <div className="flex items-start justify-between gap-3">
              <Hint>
                Match references to actual subjects. Prepared source goes first; identity references follow. Video identity stays a video
                and supplies appearance only.
              </Hint>
              <Button type="button" variant="ghost" size="sm" id="remove-secondary" disabled={locked} onClick={removeSecondary}>
                <X /> Remove Character 2
              </Button>
            </div>
            <div className="flex items-start gap-2 rounded-lg border border-info/30 bg-info/10 px-3 py-2.5 text-[13px] text-info-text">
              <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-info" aria-hidden />
              Request + artifact hashes + account/project identity are saved before submission. A durable attempted marker protects uncertain
              submissions from automatic retries.
            </div>
          </>
        }
        aside={
          <>
            {awaitingQuote && <CreditGate studio={studio} />}
            {collecting && (
              <div className="space-y-3 rounded-xl border p-4">
                <h3 className="flex items-center gap-2 text-base font-semibold">
                  <LoaderCircle className="size-4 animate-spin text-info" aria-hidden /> Generating your 480p draft
                </h3>
                <p className="text-[13px] text-muted-foreground">{job?.status}</p>
                <IndeterminateProgress label="Draft generation in progress" />
                <Hint>
                  {typeof ceiling === "number" ? `Approved ceiling: ${ceiling} credits. ` : ""}You can leave this page; the job resumes from
                  ?job={jobId?.slice(0, 6)}….
                </Hint>
              </div>
            )}
            {(showResumePrep || showResumeGen) && (
              <div className="space-y-3 rounded-xl border bg-inset p-4">
                <div className="flex items-center gap-2">
                  <RotateCcw className="size-4 text-muted-foreground" aria-hidden />
                  <span className="label-mono-sm text-muted-foreground">RECOVERY</span>
                  <ToneBadge>SHOWN ONLY WHEN RESUMABLE</ToneBadge>
                </div>
                <Hint>
                  Resume without a new submission. Preparation resume appears while the saved generation is still “preparing”; result
                  collection appears after an error.
                </Hint>
                <div className="flex flex-wrap gap-2">
                  {showResumePrep && (
                    <Button variant="outline" size="lg" id="resume-preparation" disabled={!!resuming} onClick={resumePreparation}>
                      {resuming === "prep" ? <LoaderCircle className="animate-spin" /> : <RotateCcw />} Resume saved preparation & obtain quote
                    </Button>
                  )}
                  {showResumeGen && (
                    <Button variant="outline" size="lg" id="resume-generation" disabled={!!resuming || !generationSaved} onClick={resumeGeneration}>
                      {resuming === "gen" ? <LoaderCircle className="animate-spin" /> : <RefreshCw />} Resume result collection
                    </Button>
                  )}
                </div>
              </div>
            )}
            {awaitingQuote || collecting ? (
              <Accordion type="single" collapsible className="rounded-lg border px-3">
                <AccordionItem value="prompt" className="border-none">
                  <AccordionTrigger className="py-3 hover:no-underline">
                    <span className="flex items-center gap-2">
                      <SlidersHorizontal className="size-4 text-muted-foreground" aria-hidden />
                      Exact creative prompt <span className="font-normal text-muted-foreground">Locked while this request is saved</span>
                    </span>
                  </AccordionTrigger>
                  <AccordionContent>{promptField}</AccordionContent>
                </AccordionItem>
              </Accordion>
            ) : (
              promptField
            )}
            {!generationSaved && jobId && <ManualImport studio={studio} />}
          </>
        }
      />
    </Panel>
  );
}

"use client";

import { ArrowLeft, Download, ExternalLink, Lock, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import type { StepId } from "@/lib/studio/constants";
import { audioRestoration } from "@/lib/studio/audio-restoration";
import type { Studio } from "@/lib/studio/use-studio";
import { FooterHint, Hint, Panel, PanelColumns } from "./panel";
import { ManualImport } from "./manual-import";
import { VideoCompare } from "./video-compare";

export function RestorePanel({ studio, go }: { studio: Studio; go: (step: StepId) => void }) {
  const { api, jobId, busy, maskApproved, capabilities, generation, savedRefs, finalPreview, hd, upgradeStatus, setUpgradeStatus, pollHD, status } =
    studio;
  const gen = capabilities?.generation ?? {};
  const hdSupported = gen.video_hd_supported === true;
  const audio = audioRestoration(finalPreview?.audioMode);
  const legacyProvider = generation?.provider === "dreamina-canvas" || generation?.mode === "m2v";
  const audioLabel = finalPreview ? `${finalPreview.hd ? "1080P" : "DRAFT"} · ${audio.quality}` : "DRAFT PREVIEW";
  // Same gate as static/app.js. With video_hd_supported=false (current backend) it stays disabled.
  const upgradeDisabled =
    !finalPreview || finalPreview.hd || busy || !maskApproved || generation?.provider !== "openart" || !hdSupported || hd?.state === "running";
  const generationId = generation ? generation.history_id || generation.submit_id || generation.request_id || generation.submitId || "saved" : "";
  const references = Array.isArray(generation?.reference_labels)
    ? generation.reference_labels
    : [
        "Prepared source video",
        ...(["sirio", "tein"] as const).filter((n) => savedRefs[n]).map((n, i) => `Character ${i + 1} · ${savedRefs[n]!.file}`),
      ];
  const webUrl = generation?.web_url && /^https:\/\//.test(generation.web_url) ? generation.web_url : null;

  async function upgrade() {
    if (!jobId) return;
    try {
      await api.createHd(jobId);
      setUpgradeStatus("Generating your approved draft in 1080p…");
      pollHD();
    } catch (error) {
      setUpgradeStatus((error as Error).message);
    }
  }

  return (
    <Panel
      id="final"
      number="04"
      eyebrow="音 / RESTORE & EXPORT"
      title={audio.title}
      badge="AUDIO RESTORATION"
      badgeTone="info"
      status={finalPreview && status.tone === "neutral" ? { text: audio.ready, tone: audio.verified ? "success" : "neutral" } : status}
      footer={
        <>
          <Button variant="outline" size="lg" className="h-10" onClick={() => go("substitute")}>
            <ArrowLeft /> <span className="hidden sm:inline">Back to Substitute</span>
            <span className="sm:hidden">Back</span>
          </Button>
          <FooterHint>Compare the original and restored draft before downloading.</FooterHint>
          {finalPreview ? (
            <Button size="lg" className="ml-auto h-10" asChild>
              <a href={finalPreview.url} download>
                <Download /> {finalPreview.hd ? "Download 1080p" : "Download preview"}
              </a>
            </Button>
          ) : (
            <Button size="lg" variant="outline" className="ml-auto h-10" disabled>
              Download preview <Lock />
            </Button>
          )}
        </>
      }
    >
      <PanelColumns
        className="lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]"
        main={
          <>
            {finalPreview ? (
              <VideoCompare
                originalUrl={finalPreview.originalUrl}
                resultUrl={finalPreview.url}
                qualityLabel={audioLabel}
                downloadLabel={finalPreview.hd ? "Download 1080p" : "Download draft"}
              />
            ) : (
              <div className="grid min-h-[220px] place-items-center rounded-xl border border-dashed bg-inset p-6 text-center">
                <div>
                  <span className="label-mono-sm text-muted-foreground">04 / 音</span>
                  <strong className="mt-1 block">Your 480p draft will appear here.</strong>
                  <span className="text-[13px] text-muted-foreground">Compare the original and restored draft before downloading.</span>
                </div>
              </div>
            )}
            <Hint id="audio-mode-note">
              {finalPreview
                ? audio.note
                : "The job's saved preparation determines the restored audio. Review the saved restoration metadata and soundtrack once the output is ready."}
            </Hint>
          </>
        }
        aside={
          <>
            <div className="space-y-2 rounded-xl border p-4">
              <span className="label-mono-sm text-muted-foreground">OPTIONAL / 1080P HD</span>
              <h3 className="text-base font-semibold">Preserve the draft. Upgrade only with approval.</h3>
              <Hint id="hd-detail">
                {gen.hd_detail ||
                  "HD is intentionally disabled until separate quote approval and draft lineage checks are implemented. Your draft is preserved; a new generation must never stand in for an upgrade."}
              </Hint>
              <Button id="upgrade" variant="secondary" size="lg" className="h-10" disabled={upgradeDisabled} onClick={upgrade}>
                {!hdSupported && <Lock />} {hdSupported ? "Approve 1080p completion" : "1080p upgrade unavailable"}
              </Button>
              {upgradeStatus && (
                <p id="upgrade-status" role="status" className="text-[13px] text-muted-foreground">
                  {upgradeStatus}
                </p>
              )}
            </div>
            {generation && jobId && (
              <Accordion type="single" collapsible defaultValue="sent" className="rounded-lg border px-3">
                <AccordionItem value="sent" className="border-none">
                  <AccordionTrigger className="py-3 hover:no-underline">
                    <span className="flex items-center gap-2">
                      <SlidersHorizontal className="size-4 text-muted-foreground" aria-hidden />
                      Submitted prompt & generation ID <span className="font-normal text-muted-foreground">What was sent</span>
                    </span>
                  </AccordionTrigger>
                  <AccordionContent className="space-y-2 text-[13px]">
                    <p id="generation-id" className="text-muted-foreground">
                      {(legacyProvider ? "Dreamina Canvas" : "OpenArt") + " · " + generationId}
                    </p>
                    <pre id="sent-prompt" className="max-h-40 overflow-auto whitespace-pre-wrap rounded-md bg-inset p-2 font-sans text-[13px]">
                      {generation.prompt}
                    </pre>
                    <p id="sent-references" className="text-muted-foreground">
                      Ordered references: {references.join(" → ")}
                    </p>
                    <div className="flex flex-wrap gap-x-4 gap-y-1">
                      {webUrl && (
                        <a id="canvas-link" href={webUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 hover:underline">
                          {legacyProvider ? "Open saved Dreamina canvas" : "Open saved OpenArt result"} <ExternalLink className="size-3.5" />
                        </a>
                      )}
                      <a id="raw-link" href={api.runUrl(jobId, "seedance-result.mp4")} className="inline-flex items-center gap-1 hover:underline">
                        Download raw Seedance result <Download className="size-3.5" />
                      </a>
                    </div>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            )}
            {jobId && <ManualImport studio={studio} />}
          </>
        }
      />
    </Panel>
  );
}

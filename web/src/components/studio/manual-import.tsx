"use client";

import { useId, useState } from "react";
import { LoaderCircle, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { audioRestoration } from "@/lib/studio/audio-restoration";
import type { Studio } from "@/lib/studio/use-studio";

/** Legacy "Import a generated result manually" (POST /jobs/{id}/finish). */
export function ManualImport({ studio }: { studio: Studio }) {
  const { api, jobId, refresh, setStatus } = studio;
  const formId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  // Saved job preparation can override current server configuration.
  const action = "Restore configured audio";

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!jobId) {
      setStatus("Prepare your original video first.", "error");
      return;
    }
    if (!file) return;
    setPending(true);
    try {
      setStatus("Restoring the configured source audio…", "busy");
      const data = new FormData();
      data.set("video", file);
      await api.finish(jobId, data);
      await refresh();
      // A job's saved preparation can differ from the server's current setting.
      const restoration = await api.runJson<{ mode?: unknown }>(jobId, "audio-restoration.json").catch(() => null);
      const completed = audioRestoration(restoration?.mode);
      setStatus(completed.ready, completed.verified ? "success" : "neutral");
    } catch (error) {
      setStatus((error as Error).message, "error");
    } finally {
      setPending(false);
    }
  }

  return (
    <Accordion type="single" collapsible className="rounded-lg border px-3">
      <AccordionItem value="import" className="border-none">
        <AccordionTrigger className="py-3 hover:no-underline">
          <span className="flex items-center gap-2">
            <Upload className="size-4 text-muted-foreground" aria-hidden />
            Import a generated result manually
            <span className="font-normal text-muted-foreground">{action}</span>
          </span>
        </AccordionTrigger>
        <AccordionContent>
          <form id={formId} onSubmit={submit} className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <label className="relative flex min-w-0 flex-1 cursor-pointer items-center gap-3 rounded-lg border border-dashed border-strong bg-inset px-3 py-2.5 text-sm">
              <Upload className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0">
                <strong className="block font-medium">Choose Seedance result</strong>
                <small className="block truncate text-xs text-muted-foreground" data-filename>
                  {file?.name ?? "Restore the complete configured source audio."}
                </small>
              </span>
              <input
                name="video"
                aria-label="Seedance result"
                type="file"
                accept="video/*"
                required
                className="absolute inset-0 cursor-pointer opacity-0"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <Button type="submit" variant="outline" size="lg" disabled={pending || !file}>
              {pending && <LoaderCircle data-icon="inline-start" className="animate-spin" />}
              {action}
            </Button>
          </form>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}

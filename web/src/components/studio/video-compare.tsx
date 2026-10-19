"use client";

import { useRef } from "react";
import { Download } from "lucide-react";
import { ToneBadge } from "./tone-badge";

/** Figma "VideoCompare": playing one video pauses the other to prevent overlapping audio. */
export function VideoCompare({
  originalUrl,
  resultUrl,
  qualityLabel,
  downloadLabel,
}: {
  originalUrl: string;
  resultUrl: string;
  qualityLabel: string;
  downloadLabel: string;
}) {
  const original = useRef<HTMLVideoElement>(null);
  const result = useRef<HTMLVideoElement>(null);
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="space-y-2">
        <h3 className="label-mono-sm text-muted-foreground">SOURCE / ORIGINAL</h3>
        <video
          ref={original}
          id="comparison-original"
          src={originalUrl}
          controls
          playsInline
          preload="metadata"
          aria-label="Original source comparison"
          onPlay={() => result.current?.pause()}
          className="aspect-video w-full rounded-xl border bg-canvas"
        />
        <p className="text-[13px] text-muted-foreground">Untouched source video & audio</p>
      </div>
      <div className="space-y-2">
        <h3 className="label-mono-sm text-muted-foreground">RESULT / SUBSTITUTION</h3>
        <video
          ref={result}
          id="final-video"
          src={resultUrl}
          controls
          playsInline
          preload="metadata"
          aria-label="Restored substitution result"
          onPlay={() => original.current?.pause()}
          className="aspect-video w-full rounded-xl border bg-canvas"
        />
        <div className="flex items-center justify-between gap-2 text-[13px]">
          <ToneBadge tone="accent" id="quality-label">
            {qualityLabel}
          </ToneBadge>
          <a id="final-download" href={resultUrl} download className="inline-flex items-center gap-1 text-crimson-text hover:underline">
            {downloadLabel} <Download className="size-3.5" />
          </a>
        </div>
      </div>
    </div>
  );
}

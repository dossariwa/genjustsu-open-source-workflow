import { cn } from "@/lib/utils";
import { API_MODE } from "@/lib/api";
import { BrandMark } from "./brand-mark";
import { TelemetryPopover } from "./telemetry-popover";
import type { TelemetryView } from "@/lib/studio/use-telemetry";
import type { HeroBanner } from "@/lib/studio/use-hero";

export function TopBar({ telemetry, onRefresh, hero }: { telemetry: TelemetryView; onRefresh: () => void; hero: HeroBanner }) {
  return (
    <header className="bg-canvas">
      <div className="mx-auto flex h-14 w-full max-w-[1440px] items-center gap-3 px-4 lg:px-10">
        <a href="./" className="flex items-center gap-3" aria-label="GENJUSTSU home">
          <BrandMark className="size-7 text-crimson" />
          <span className="flex flex-col leading-none">
            <span className="text-[15px] font-semibold tracking-tight">
              GENJUSTSU <span className="text-crimson-text">{"//"}</span> <span lang="ja">幻術</span>
            </span>
            <small className="label-mono-sm mt-0.5 hidden text-muted-foreground sm:block">KAWARIMI SUBSTITUTION STUDIO</small>
          </span>
        </a>
        <div className="ml-auto flex items-center gap-2">
          {API_MODE === "mock" && (
            <span className="label-mono-sm rounded-full border border-info/60 bg-info/10 px-2.5 py-1 text-info-text" title="UI preview with simulated responses. No provider is contacted.">
              MOCK API
            </span>
          )}
          <span
            className="label-mono-sm hidden items-center gap-2 rounded-full border px-3 py-1 text-muted-foreground md:inline-flex"
            role="status"
          >
            <i className={cn("size-1.5 rounded-full", telemetry.online ? "bg-success" : "bg-muted-foreground")} aria-hidden />
            {telemetry.loopback}
          </span>
          <TelemetryPopover telemetry={telemetry} onRefresh={onRefresh} hero={hero} />
        </div>
      </div>
    </header>
  );
}

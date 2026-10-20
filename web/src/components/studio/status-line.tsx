import { LoaderCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { StatusLine as Status } from "@/lib/studio/use-studio";

const DOT: Record<Status["tone"], string> = {
  neutral: "bg-muted-foreground",
  busy: "",
  error: "bg-danger-text",
  success: "bg-success",
};

/** Figma "StatusLine" — the legacy #status element. */
export function StatusLine({ status, className }: { status: Status; className?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex min-w-0 items-center gap-2 text-[13px] leading-[18px]",
        status.tone === "error" ? "text-danger-text" : status.tone === "success" ? "text-success-text" : "text-muted-foreground",
        className,
      )}
    >
      {status.tone === "busy" ? (
        <LoaderCircle className="size-3.5 shrink-0 animate-spin text-info" aria-hidden />
      ) : (
        <span className={cn("size-1.5 shrink-0 rounded-full", DOT[status.tone])} aria-hidden />
      )}
      <span className="truncate" title={status.text}>
        {status.text}
      </span>
    </div>
  );
}

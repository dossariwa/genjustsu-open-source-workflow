import { cn } from "@/lib/utils";

/**
 * Figma "Progress / Value=Indeterminate". The API reports stage text only,
 * never a percentage, so the bar never shows a fake value.
 */
export function IndeterminateProgress({ className, label }: { className?: string; label: string }) {
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-busy="true"
      className={cn("relative h-1 w-full overflow-hidden rounded-full bg-muted", className)}
    >
      <div className="absolute inset-y-0 left-0 w-2/5 animate-indeterminate rounded-full bg-gradient-to-r from-transparent via-crimson to-transparent" />
    </div>
  );
}

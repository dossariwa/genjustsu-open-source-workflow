import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

export type Tone = "neutral" | "accent" | "info" | "warning" | "success" | "danger";

const TONES: Record<Tone, string> = {
  neutral: "border-strong bg-elevated text-muted-foreground",
  accent: "border-crimson/60 bg-crimson/10 text-crimson-text",
  info: "border-info/60 bg-info/10 text-info-text",
  warning: "border-warning/60 bg-warning-subtle text-warning-text",
  success: "border-success/60 bg-success/10 text-success-text",
  danger: "border-danger-text/60 bg-danger-text/10 text-danger-text",
};

/** Figma "Badge" (Tone=Neutral/Accent/Info/Warning/Success) on top of shadcn Badge. */
export function ToneBadge({ tone = "neutral", className, ...props }: React.ComponentProps<typeof Badge> & { tone?: Tone }) {
  return <Badge variant="outline" className={cn("label-mono-sm h-[22px] rounded-sm px-2 font-medium", TONES[tone], className)} {...props} />;
}

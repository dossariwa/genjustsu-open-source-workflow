import { cn } from "@/lib/utils";
import { StatusLine } from "./status-line";
import { ToneBadge, type Tone } from "./tone-badge";
import type { StatusLine as Status } from "@/lib/studio/use-studio";

/**
 * One workspace step card (Figma "PreparePanel (Card)" etc.): header, body
 * whose columns scroll internally on desktop, and a Back/Next footer.
 */
export function Panel({
  id,
  number,
  eyebrow,
  title,
  badge,
  badgeTone = "neutral",
  status,
  children,
  footer,
}: {
  id: string;
  number: string;
  eyebrow: string;
  title: string;
  badge: string;
  badgeTone?: Tone;
  status: Status;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <section
      id={id}
      aria-labelledby={`${id}-title`}
      className="flex min-h-0 flex-1 flex-col lg:overflow-hidden lg:rounded-xl lg:border lg:bg-card"
    >
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 lg:h-[60px] lg:border-b lg:flex-nowrap lg:px-6 lg:py-0">
        <span className="font-heading text-[28px] font-semibold leading-none tracking-tight text-crimson-text" aria-hidden>
          {number}
        </span>
        <div className="min-w-0 flex-1">
          <span className="label-mono-sm block text-muted-foreground">{eyebrow}</span>
          <h2 id={`${id}-title`} className="text-lg font-semibold lg:truncate leading-6 tracking-tight lg:text-xl">
            {title}
          </h2>
        </div>
        <StatusLine status={status} className="order-last w-full lg:order-none lg:w-auto lg:max-w-[440px]" />
        <ToneBadge tone={badgeTone} className="hidden lg:inline-flex">
          {badge}
        </ToneBadge>
      </header>
      <div className="min-h-0 flex-1 lg:overflow-hidden">{children}</div>
      <footer className="sticky bottom-0 z-10 flex items-center gap-3 border-t bg-canvas/95 px-4 py-3 backdrop-blur lg:static lg:rounded-b-xl lg:bg-card lg:h-[69px] lg:px-6 lg:py-0">
        {footer}
      </footer>
    </section>
  );
}

/** Two-column body; each column scrolls on its own so the page never does (≥1024px). */
export function PanelColumns({ main, aside, className }: { main: React.ReactNode; aside: React.ReactNode; className?: string }) {
  return (
    <div className={cn("grid h-full grid-cols-1 gap-6 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-8 lg:px-6 lg:py-4", className)}>
      <div className="flex min-h-0 min-w-0 flex-col gap-3 lg:overflow-y-auto lg:pr-1">{main}</div>
      <div className="flex min-h-0 min-w-0 flex-col gap-3 lg:overflow-y-auto lg:pr-1">{aside}</div>
    </div>
  );
}

export function FooterHint({ children }: { children: React.ReactNode }) {
  return <p className="hidden min-w-0 flex-1 text-[13px] leading-[18px] text-muted-foreground sm:block">{children}</p>;
}

export function Hint({ children, className, ...props }: React.ComponentProps<"p">) {
  return (
    <p className={cn("text-[13px] leading-[18px] text-muted-foreground", className)} {...props}>
      {children}
    </p>
  );
}

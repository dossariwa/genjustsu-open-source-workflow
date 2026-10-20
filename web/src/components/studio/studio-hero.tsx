/* eslint-disable @next/next/no-img-element -- static export; the banner may be a local blob: URL or animated GIF */
import type { HeroBanner } from "@/lib/studio/use-hero";

/**
 * Figma "StudioHero". Per the open design decision, the PERSON / CREATURE /
 * OBJECT labels and the long description are omitted; the eye artwork is a
 * single swappable asset (HERO_DEFAULT_SRC) and can be customized locally.
 */
export function StudioHero({ hero }: { hero: HeroBanner }) {
  return (
    <section aria-labelledby="hero-title" className="bg-canvas">
      <div className="relative mx-auto flex w-full max-w-[1440px] flex-col-reverse gap-3 px-4 pb-3 lg:h-36 lg:flex-row lg:items-center lg:px-10 lg:pb-0">
        <div className="relative z-10 min-w-0 flex-1">
          <p className="label-mono-sm flex items-center gap-2 text-muted-foreground">
            <span className="h-px w-6 bg-crimson" aria-hidden />
            <span lang="ja" className="text-crimson-text">
              変わり身の術
            </span>
            THE ART OF SUBSTITUTION
          </p>
          <h1 id="hero-title" className="mt-1.5 text-[28px] font-semibold leading-8 tracking-[-0.02em] lg:text-[40px] lg:leading-[44px]">
            Same scene. <br className="lg:hidden" />
            <em className="not-italic text-crimson-text">Different reality.</em>
          </h1>
          <p className="mt-1.5 hidden text-[13px] text-muted-foreground sm:block">
            Swap a person, creature or object. Keep the motion and the original audio.
          </p>
        </div>
        <figure className="relative -mx-4 h-[112px] overflow-hidden lg:mx-0 lg:h-36 lg:w-[680px]" aria-label={`Visual reference / ${hero.origin}`}>
          {hero.failed ? (
            <div className="grid h-full place-items-center rounded-lg border border-dashed text-center text-xs text-muted-foreground">
              Drop your visual inspiration here.
              <br />
              Choose an image or animated GIF in Studio status.
            </div>
          ) : (
            <img src={hero.src} alt={hero.alt} onError={hero.onError} className="size-full object-cover" />
          )}
          <div
            className="pointer-events-none absolute inset-0"
            style={{ backgroundImage: "linear-gradient(90deg, #000 0%, transparent 25%, transparent 80%, #000 100%)" }}
            aria-hidden
          />
        </figure>
      </div>
    </section>
  );
}

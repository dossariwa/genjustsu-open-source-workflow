# GENJUSTSU studio UI (`web/`)

Next.js (App Router) + TypeScript + Tailwind CSS v4 + shadcn/ui implementation of the approved Figma design
(file `CoSysrjNYVuF7MLDkC6CLH`, desktop page `2:96`, mobile page `2:97`).

The UI contains **no business logic**: every gate (duration limit, mask review, credit quote approval, HD
upgrade) is decided by the FastAPI backend. The frontend only calls the existing endpoints exactly like
`static/app.js` does. The client-side duration check reads `/capabilities` → `clip_limits` (fallback 8 s) and is
UX only — the server stays authoritative.

## Commands

Requires Node.js **22.13+**; **Node 24 LTS is recommended** (`web/.nvmrc`). The minimum comes from the dependency tree (`engines` in the lockfile, e.g. `cn` needs 22+ and `eslint-visitor-keys` needs ^22.13) and is enforced by `engine-strict` in `web/.npmrc`; `package.json` `engines` is the single source of truth that `setup.sh` reads.

| Command | What it does |
| --- | --- |
| `npm ci` | Install dependencies |
| `npm run dev` | Dev server on :3000; proxies `/capabilities`, `/telemetry`, `/health`, `/jobs/*`, `/runs/*`, `/static/*` to FastAPI at `127.0.0.1:8770` (override with `GENJUSTSU_API_ORIGIN`). Start the backend with `bash start.command`. |
| `npm run dev:mock` | Dev server with the in-browser **mock API** (no backend needed) |
| `npm run build` | Static export to `web/out` — FastAPI serves it at `/` automatically |
| `npm run build:mock` | Static export using the mock API (used for Vercel previews only; `vercel.json` skips production builds via `ignoreCommand` when `VERCEL_ENV=production`) |
| `npm run lint` / `npm run typecheck` / `npm run check` | ESLint / `tsc --noEmit` / both |
| `npm test` / `npm run test:watch` | Vitest + React Testing Library regression suite / watch mode |

The regression suite exercises tab-state retention, stale job response isolation,
failed reference downloads, and audio-restoration messages with mocked APIs. It
does not contact providers or establish live video-generation readiness.
Run the suite and both builds on Node 24 before merging. The shadcn CLI and its
build-time CSS are development dependencies; install development dependencies
when building.

See [the dependency advisory assessment](../docs/SECURITY-ADVISORIES.md) for the
remaining tooling-only audit findings, and [production requirements](../docs/PRODUCTION.md)
for the planned private FastAPI host. Vercel Preview remains mock-only; production
build restrictions remain until real backend integration and validation are complete.

## How FastAPI serves it

* `GET /` returns `web/out/index.html` when it exists; `/_next/*` and `/ui/*` serve the export's assets.
* `UI=legacy` (env or `.env`) forces the previous `static/` interface. Without a build, the legacy UI is
  served automatically. `/runs`, `/static` and every API route are unchanged.
* `bash setup.sh` builds `web/out` when Node 22.13+ is present (24 recommended) and skips it otherwise
  (`SKIP_WEB_BUILD=1` to skip explicitly). A missing/old Node or a failed build prints a prominent warning that the
  legacy UI will be served and why; it never fails the Python setup.
* With no build, `/_next/*` and `/ui/*` return a plain 404 (no server error).

## Mock API mode (`NEXT_PUBLIC_API_MODE=mock`)

`src/lib/mock/api.ts` implements the same `StudioApi` interface as the HTTP client and simulates the whole job
lifecycle in the browser (state in `localStorage`): upload → preparation (≈7 s) → full-clip review gate with
artifact fingerprint → quote (120 credits) → credit approval → collection (≈9 s) → restored preview. It ships
small synthetic fixtures in `public/ui/mock/`. "Studio status" exposes scenario toggles (server-side duration
rejection, failed collection + resume) and a reset. A `MOCK API` pill is always shown in this mode.

Mock mode is opt-in at build time only; `npm run build` (what FastAPI serves) always uses the real HTTP API.

## Hero asset

The hero eyes are a single swappable placeholder: `public/ui/hero/eyes-placeholder.webp`
(`HERO_DEFAULT_SRC` in `src/lib/studio/constants.ts`). Users can still pick a local banner/GIF from
"Studio status → Customize banner" (stored in IndexedDB, never uploaded).

## Layout

* `src/lib/api` – typed endpoint client (`http.ts`) and mode switch (`index.ts`).
* `src/lib/studio` – `useStudio` (mirrors app.js refresh/poll logic), limits, hero and telemetry hooks.
* `src/components/studio` – StudioHero, StepTabs, MaskReviewGate, CreditGate, VideoCompare,
  TelemetryPopover and the four step panels.
* `src/components/ui` – generated shadcn/ui components.

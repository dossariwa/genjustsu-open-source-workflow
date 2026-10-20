# Private production deployment requirements

**Status: design only, reviewed 20 October 2026.** This document does not deploy
the application or enable production builds, authentication, upload limits, job
limits, or a paid-provider switch. Those controls still need implementation and
verification. No hosting purchase, account authorization, or paid inference is
authorized by this document.

Genjustsu is a private studio for one owner. Keep the existing Python/FastAPI
pipeline authoritative and the approved Next.js design intact. Use one backend
service and its persistent filesystem. A separate identity platform, database
service, queue service, or multiuser model is unnecessary for this deployment.

## Current implementation and release gates

The current backend was built for local use:

| Current code | Production consequence |
| --- | --- |
| `app.py:15–23`: `runs/`, in-memory registries and a process-local lock | A stable persistent data path and exactly one backend process/replica are required. |
| `app.py:125–176,191–207`: preparation and collection use daemon threads | Work needs bounded admission and controlled shutdown. A process exit can interrupt preparation. |
| `app.py:141–142,223–224,358–359`: uploads are copied without byte limits | Enforce request and file limits before accepting public traffic. |
| `app.py:232–365`: several handlers perform provider or media work before returning | Slow requests must not depend on Vercel's external rewrite timeout. |
| `app.py:416–442`: startup collects saved provider work and marks interrupted preparation | Retain this recovery behavior; startup must never approve or submit new inference. |
| `app.py:449`: the entire `runs/` tree is mounted as static files | Protect media and job metadata with owner authentication before deployment. |
| `app.py`: no owner authentication or CORS middleware | Add access control, explicit browser origins, and CSRF protection. |
| `openart_transport.py:69–114`: the official CLI owns renewable OAuth credentials | The CLI's private credential directory must persist separately from served media. |
| `launch.py`: binds `127.0.0.1` | Keep the local launcher; add an explicit production entrypoint. |
| `web/vercel.json`: mock build and production ignore gate | Keep production blocked until the real backend integration passes acceptance checks. |
| `web/src/lib/api/http.ts`: relative API/media URLs | Add one consistent environment-aware origin resolver for every request and media URL. |

Line numbers describe the audited revision and may move. Recheck code before
implementation. A frontend dependency audit failure paused release work; see
[the security advisory record](SECURITY-ADVISORIES.md) for its current disposition.
Follow the recorded check results and the user's stop-on-failure instruction.
This requirements document does not waive any failing check.

## Recommended deployment

Use the existing Vercel `genjustsu` project for the frontend and one persistent
FastAPI Docker service for the backend. Both use HTTPS custom subdomains of an
owner-controlled domain:

```text
Owner's browser
  ├─ https://studio.<owner-domain>  → Vercel: Next.js frontend
  └─ https://api.<owner-domain>     → FastAPI: login, API, private media
                                          └─ one persistent disk
```

These are placeholder hostnames, not configured URLs. The shared registrable
domain makes the two HTTPS origins same-site while keeping them cross-origin.
The browser contacts FastAPI directly for uploads, polling, JSON, previews, and
exports. This avoids passing large uploads or slow requests through Vercel
Functions or external rewrites.

The default `*.vercel.app` frontend and `*.onrender.com` backend are cross-site.
Do not make production owner sessions depend on third-party cookies between
them. Redirect the public production Vercel alias to the chosen custom frontend
domain. Mock previews do not need the production API or owner session.

Run one Uvicorn process, one replica, no autoscaling and no development reload.
The production entrypoint must bind `0.0.0.0` to the hosting platform's `PORT`;
retain the existing loopback launcher for local use. Use `/health` for liveness,
with no credentials, account information, paths, or generation-ready claim.
Authenticated capability responses should separately report configured
providers, locally checked adapters, disabled paid operations, and unverified
live generation.

### Hosting choice and cost approval

Prices below were checked against primary sources on 20 October 2026. They are
estimates before tax, provider inference charges, domain registration, and
additional usage. No plan has been purchased.

| Option | Initial configuration | Published baseline | Operational tradeoff |
| --- | --- | --- | --- |
| Render, recommended | One `1c-2g` web service, 1 CPU/2 GB RAM, 10 GB persistent disk | $25/month compute + $2.50/month disk = **$27.50/month** | Managed HTTPS and service operation; disk-backed deploys have brief downtime. |
| DigitalOcean Basic Droplet | Regular CPU, 1 vCPU/2 GiB RAM/50 GiB disk | **$12/month**, or **$15.60/month** including daily backups at 30% | Lower baseline; the owner must maintain the OS, TLS proxy, firewall, restart policy, and backups. |
| DigitalOcean with more headroom | Regular CPU, 2 vCPU/4 GiB RAM/80 GiB disk | **$24/month**, or **$31.20/month** with daily backups | More CPU/RAM for media work, with the same server maintenance responsibility. |

Render disk pricing is $0.25/GB/month; its Hobby workspace currently includes
5 GB bandwidth/month, then $0.15/GB. Existing workspace usage can consume that
allowance. [Render pricing](https://render.com/pricing).

The quoted DigitalOcean 2 GiB and 4 GiB bundled plans include 2,000 GiB and
4,000 GiB transfer respectively. Backup prices above use the published
percentage-based daily option. [DigitalOcean pricing](https://www.digitalocean.com/pricing/droplets).

Two GB RAM is an initial sizing proposal, not a verified workload requirement.
Measure the largest allowed synthetic clip with mocked providers and both mesh
modes before choosing the final size. Keep CPU-intensive processing serialized.
No local GPU is needed.

Render disks survive restarts/deploys, support daily snapshots retained for at
least seven days, and attach to one instance. A disk-backed service cannot scale
to multiple instances and loses zero-downtime deployment. Plan deployment only
after active local processing drains. [Render persistent disks](https://render.com/docs/disks).

Vercel Functions have a 4.5 MB request/response limit and bounded execution.
They do not fit this existing durable, threaded media pipeline. External
rewrites have a separate 120-second origin response timeout; the Function
payload limit should not be assumed to apply to those rewrites. These handlers
return JSON after completing work, so they do not stream an early response to
avoid that timeout. [Function limits](https://vercel.com/docs/functions/limitations),
[proxy timeout](https://vercel.com/docs/limits),
[Vercel timeout clarification](https://vercel.com/changelog/cdn-origin-timeout-increased-to-two-minutes).

### Alternative: one authenticated origin

If a shared custom domain is unavailable, or the owner wants the frontend HTML
itself private, one HTTPS reverse proxy on the backend host can expose the
entire studio at one origin. It would route API/media/login paths directly to
FastAPI and frontend assets to Vercel, or serve the existing Next.js static
export through FastAPI. Keep local API traffic out of a Vercel external rewrite.

This removes cross-origin session/CORS complexity but changes the public traffic
path and adds proxy configuration. Proxying Vercel assets must be verified for
host routing, redirects, caching, and asset paths; serving the static export
changes the role of the Vercel production deployment. Choose this alternative
explicitly before implementation. It is not an instruction to replace the
requested Vercel frontend.

## Owner authentication, HTTPS, and browser access

The proposed minimal login is a backend-owned password form. There is one
configured owner, no registration, no account switching, and no user database
service.

1. Store only a strong password hash, preferably Argon2id through a maintained
   password-hashing library, configured privately on the backend. Never put a password, hash,
   shared API key, or session secret in `NEXT_PUBLIC_*`, browser storage, Git,
   build artifacts, URLs, or logs.
2. Authenticate at `https://api.<owner-domain>/auth/login`. Rate-limit failures,
   use generic rejection messages, and protect the login form from CSRF.
   Return only to an exact allowlisted studio URL; do not accept open redirects.
3. Issue a cryptographically random opaque session. Store only its hash and
   expiry in a small backend-private session file with atomic writes, or another
   equally simple local session store. A proposed session policy is a 12-hour
   absolute lifetime and 30-minute inactivity expiry, renewed by authenticated
   activity. Logout and password rotation revoke sessions.
4. Use a host-only `__Host-genjustsu_session` cookie with `Secure`, `HttpOnly`,
   `Path=/`, `SameSite=Strict`, and no `Domain` attribute. It is sent to the API
   host, not the Vercel host. API fetches need `credentials: "include"`. Media
   elements that use a CORS mode need credentialed loading too.
5. Protect every API response containing job/account information and every
   `/runs` GET/HEAD/Range response with that session. Authenticate before
   accepting upload bodies. Return an explicit 401 when a session expires;
   preserve `?job=` so login can recover the selected job.
6. For each unsafe method, require an exact allowed `Origin` and a
   session-bound CSRF token in a custom header. CORS and same-site cookies alone
   are insufficient, including against compromised sibling subdomains.
   Backend-hosted login forms use their own CSRF token. Recheck legacy UI and
   CLI behavior deliberately; do not bypass CSRF merely because `Origin` is
   absent on a mutation.
7. Configure credentialed CORS for the exact production frontend origin and
   the exact API origin as appropriate. Allow only required methods/headers;
   expose only required media headers. Return `Vary: Origin`. Never use
   wildcard credentialed origins or allow all Vercel preview deployments.
8. Keep authenticated job/media responses out of shared caches. Preserve media
   seeking, `Range`, `Content-Range`, `Accept-Ranges`, HEAD, and downloads. Do
   not put session tokens in media query strings.

The Vercel HTML/JS shell contains no private data and may remain publicly
fetchable; all useful application operations and artifacts require the owner
session. If private HTML is also required, use the single-origin alternative.
Backend auth applies equally to the hosting provider's default hostname, so
that hostname cannot bypass the custom-domain protection.

See [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/),
[cookie attributes](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie),
and [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

## Persistent data, credentials, and jobs

Use one persistent mount, for example `/data`, with private subdirectories.
These paths are proposed deployment conventions, not current configuration:

```text
/data/runs/       original media, processing artifacts, job/review/provider state
/data/auth/       hashed owner sessions and authentication state
/data/openart/    official CLI OAuth files, accessible only to the service user
/data/tmp/        bounded temporary uploads and intermediate files
```

Only authenticated, explicitly permitted job files under `/data/runs` may be
served. Internal OAuth files, auth state, logs, and runtime configuration must
never fall under a static mount. Protect all other job metadata too; saved
provider state contains account/project identifiers and absolute local paths.
Use the existing safe public generation summary where appropriate.

The existing code fixes `RUNS` to the repository and OpenArt credentials to the
service user's home. Implementation needs a stable configurable run path and
a deliberate private CLI credential mount at that CLI's expected location.
Preserve the official CLI as the owner of sign-in and refresh; do not invent an
OpenArt API-key flow or overwrite system home variables in deployment scripts.
Complete OAuth privately on the selected host through the official supported
flow. A connector login on the owner's computer does not authenticate the host.

Backend-only provider settings remain `HF_ACCESS_TOKEN` (or `HF_TOKEN`),
configured depth/raw-mask Space IDs and API names, `ELEVENLABS_API_KEY`,
`ELEVENLABS_VOICE_ID`, `OPENAI_API_KEY`, and the existing nonsecret model/audio
settings. Keep `FINAL_AUDIO_SOURCE=original` by default. Never transfer another
project's credentials or print secret values during validation.

The container needs Python 3.12, pinned main dependencies, Rubber Band, and the
isolated `.venv-face` worker for mesh modes. Keep its small landmark model in a
known writable/cache location; no heavy local depth/SAM/audio weights.
Use a non-root application user and private permissions on credential files.

Retain originals, full source audio, masks, fingerprints, exact prompt/reference
mapping, attempted markers, provider history IDs, draft outputs and restored
exports. Do not automatically upload existing local runs during deployment.
If selected jobs are migrated later, validate their paths and hashes before any
resume operation; saved absolute paths must continue to identify the same files.

For initial capacity, propose one active CPU-intensive preparation/restoration
operation and one bounded collection loop. Serialize all mutations of a job,
including audit, prompt/reference changes and manual finish. Return a clear
busy response for additional work instead of creating unbounded daemon threads
or an unbounded queue. A separate queue service is unnecessary.

Persist an operation's accepted state before background work starts. On
shutdown, stop accepting mutations and wait a bounded interval for tracked
workers. On restart:

- Resume only collection for a saved, confirmed provider history ID.
- Preserve uncertain submission markers and never resubmit them.
- Mark interrupted preparation/restoration explicitly and retain artifacts.
- Require an explicit authorized retry for preparation; it can call paid
  providers. Do not silently restart it.
- Never count a client/proxy timeout as evidence that provider submission failed.

Use atomic writes for job state and review records. Keep the stronger durable
attempt marker in the OpenArt bridge, and validate status after restart. Avoid
deploying during local processing. Collection can resume from its saved identity.
Keep the previous application image available for rollback without replacing
the persistent data with an older snapshot.

Monitor free disk space and admission limits. A proposed starting policy is
256 MiB per HTTP request, 200 MiB per uploaded video, 20 MiB per reference image,
and at least 2 GiB free disk before admitting new processing. These are outer
resource limits to validate against intended files, not provider schema limits.
Count actual streamed bytes before multipart parsing, including chunked requests;
do not trust `Content-Length`. Bound temporary files and provider downloads too.
Reject malformed/oversized media with clear errors and clean only incomplete
temporary uploads. Preserve the existing 8-second/192-frame depth limit and
30-second mesh normalization limit, plus the live model's constraints.

Set bounded connection, request and subprocess timeouts. Existing ElevenLabs
requests can wait 600 seconds, OpenArt collection can wait 3,600 seconds, and
mesh subprocesses currently lack a timeout. Choose host/proxy timeouts after
measuring synthetic workloads; retain read-only recovery after any uncertainty.
Do not let one stalled request exhaust every worker.

Start with manual owner-controlled job cleanup and storage alerts. Do not delete
source media, active/uncertain jobs, drafts or approval records automatically to
make space. Keep encrypted backups and verify a restore to an isolated location
with inference disabled. Restoring an older disk must never re-enable a saved
submission or repeat a paid operation.

## Paid-provider policy

Add one backend-enforced, default-off policy at the provider-call boundary,
checked again immediately before a billable action. A UI-disabled button, a
missing credential, or a credit-approval form is not this policy. The proposed
name `GENJUSTSU_ALLOW_PAID_INFERENCE=0` is **not implemented**.

| Path or action | Required behavior while disabled |
| --- | --- |
| `/jobs` preparation, including both mesh modes | Do not call HF inference, ElevenLabs isolation/Scribe/STS, or other paid processing. Face mesh still uses the audio workflow. Return an honest disabled response before submission. |
| `/jobs/{id}/prompt` and `/audit` | Deny OpenAI inference. |
| `/seedance`, `/credit-approval`, `/resume-preparation`, direct bridge/CLI submission | Deny any new paid generation. Preparation/upload behavior must also remain explicit; a disabled production smoke test must not send user media to providers. |
| `/hd` | Keep the existing HD action disabled; no replacement generation. |
| `/resume`, saved-generation startup collection | Permit authenticated read-only collection and downloading of an already submitted operation, followed by local original-audio restoration. Never convert collection into submission. |
| `/health`, capabilities, account/catalog/quote checks | Permit non-spending checks when intentionally invoked; report unavailable credentials honestly. |
| Manual imported result and local review | Permit authenticated local validation/restoration without provider inference. |

When the owner later authorizes live testing, the switch does not replace
full-clip review, exact-prompt review, artifact hashes, reference mapping, a
fresh exact quote, or the existing explicit credit-ceiling approval. Keep all
those gates. Legacy Dreamina work remains collection-only.

Test the disabled policy at both HTTP and provider boundaries so alternate
entrypoints cannot bypass it. Use a test-only injected fake provider for
workflow tests. Do not give production a runtime mock-provider switch or make
fake results look like live completed jobs.

## Frontend environments and legacy compatibility

| Environment | Required behavior |
| --- | --- |
| Vercel Production | Existing `genjustsu` project; root `web`; branch `main`; Node.js 24.x; ordinary real-HTTP build; exact HTTPS API origin; no provider secrets. Fail the build if mock mode is requested or the production API origin is absent/invalid. |
| Vercel Preview | Explicit mock build with visible `MOCK API` indicator; isolated browser fixtures; no production API credentials, production CORS access or real media uploads. |
| Local development | Existing same-origin development proxy to loopback FastAPI, or explicitly selected mock mode. |
| Local/FastAPI export | Preserve `web/out` hosting and the same-origin HTTP client. |
| Legacy UI | Preserve `UI=legacy` fallback and all existing endpoint/DOM contracts; add the same owner session and CSRF behavior for hosted use. |

`GENJUSTSU_API_ORIGIN` currently affects the development rewrite only. A direct
browser API base needs an explicit public, nonsecret build-time origin, applied
consistently to fetches, HEAD probes, JSON, blobs, video/audio sources, references,
and downloads. Preserve every existing endpoint, polling behavior, `?job=`
recovery and server error message. Avoid mixed-content requests and stale
artifact caching.

Keep `web/vercel.json` production restrictions in place until the real backend,
authentication and integration acceptance checks pass. Do not silently fall back
to mock mode when the backend is unavailable. All four tabs must show actual
backend state, including intentionally disabled paid operations.

## Acceptance before release

Before a later release, complete these checks and stop that release if a
required check fails:

1. Pass the complete Python suite and required frontend checks under Node 24,
   including the dependency security gate.
2. Start the production container with an empty durable disk and no provider
   secrets; verify truthful health/capabilities and default-off inference.
3. Verify unauthorized API, media, HEAD/Range and upload requests fail before
   private content or body processing; verify login/logout/expiry, CSRF and
   disallowed-origin rejection in desktop and mobile browsers.
4. Exercise every workflow tab through the real FastAPI HTTP layer with
   test-only mocked providers: upload validation, preparation, review mismatch,
   exact prompt/quote gates, polling, interrupted work, saved collection,
   manual import, original-audio restoration, preview and export.
5. Verify oversized/chunked uploads, malformed files, concurrency limits,
   timeouts, low disk space, container restart and backup recovery.
6. Verify `?job=` recovery, preview selection/playback, media seeking/downloads,
   legacy fallback and the approved responsive design.
7. Verify the actual Vercel production build points to the deployed HTTPS API;
   inspect real network responses and authentication. Preview mock builds must
   remain isolated. Remove production restrictions only after these checks.
8. Report separately: UI available, backend healthy, safe mocked-provider
   workflow verified, configured accounts, and live video generation unverified.
   No paid generation or full video delivery claim is part of this preparation.

## Decisions still required

- Select Render or DigitalOcean and approve its actual recurring charges before
  provisioning; authorize access to that hosting account privately.
- Choose an owner-controlled domain and the frontend/API subdomains, or choose
  the single-origin alternative. No domain purchase is assumed.
- Confirm the proposed one-owner backend login and whether protecting private
  operations/artifacts is sufficient, or the frontend HTML must also be private.

Host credentials and the owner's password must be entered through private
settings or an approved local secret mechanism. Do not send them in chat.

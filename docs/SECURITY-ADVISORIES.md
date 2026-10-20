# Frontend dependency assessment

Reviewed on 20 October 2026 for PR #2.

## Remaining development-tool advisory

[GHSA-vfj7-8cjw-p6xm / CVE-2026-93687](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)
affects `braces <=3.0.3`. Deeply nested brace patterns can exhaust its recursive
parser/compiler and terminate a Node process. The advisory currently lists no
patched version.

The lockfile has nine high-severity audit entries representing this one root
advisory and its dependents:

```text
eslint-config-next → @next/eslint-plugin-next → fast-glob
shadcn → fast-glob
shadcn → @shadcn/registry → fast-glob
shadcn → ts-morph → @ts-morph/common → fast-glob
fast-glob → micromatch → braces
```

No forced update, major framework downgrade, dependency override, or audit
suppression has been applied. `shadcn` remains at the existing version and is
classified as a development dependency: its CLI runs during component
development, and its `tailwind.css` import is processed at build time.

## Production impact in this application

- `npm audit --omit=dev --audit-level=high` reports **zero vulnerabilities**.
  `braces`, `micromatch`, `fast-glob`, and the shadcn CLI are absent from the
  production dependency graph.
- The application imports generated `src/components/ui` components, Radix, and
  shadcn's CSS; it does not import the shadcn CLI, registry API, or vulnerable glob
  parser as runtime JavaScript.
- Both current builds are static exports. Vercel Preview serves a mock API in
  the browser; FastAPI can serve the real HTTP export. Neither path runs ESLint
  or the shadcn CLI in response to an upload, prompt, job request, or media fetch.
- The Python media pipeline does not execute these Node development tools.

These observations indicate **no identified application-request path to this
advisory** in the present deployment model. They do not constitute a universal
claim that the dependency is safe, or an exemption for future architecture
changes. Moving a package to `devDependencies` is correct classification, not a
patch. The vulnerable code is still installed on development/build machines.

## Residual risk and maintenance

An attacker-controlled glob passed to the affected tooling could interrupt a
developer or build process. Keep component registry inputs, scripts, and build
configuration under review. Do not expose these tools as an API, pass user
filenames/prompts to glob evaluation, or run unreviewed repository code with
production credentials. Frontend builds do not need AI-provider secrets.

Run both audit scopes when refreshing dependencies:

```bash
cd web
npm audit --omit=dev --audit-level=high
npm audit
npm explain braces
```

The full audit still exits nonzero for the documented development-tool advisory;
report it explicitly. Review any changed advisory count or dependency path.
Reassess when a compatible upstream fix becomes available or when deployment
changes from static export to runtime Node tooling.

This assessment supports reviewing the frontend PR independently of the
remaining backend deployment blockers. It does **not** authorize production
release. See [the private deployment requirements](PRODUCTION.md).

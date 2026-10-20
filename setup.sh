#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Install Python 3.12+ first. See docs/SETUP-AGENT.md."; exit 1
fi
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else "Python 3.12+ required. Set PYTHON to a compatible interpreter.")'
if ! command -v rubberband >/dev/null 2>&1; then
  echo "Rubber Band CLI is missing. macOS: brew install rubberband; Ubuntu/WSL: sudo apt install rubberband-cli"
  echo "See docs/SETUP-AGENT.md for agent-led installation."; exit 1
fi
if [ ! -d .venv ]; then "$PYTHON" -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; chmod 600 .env; fi
# Optional: build the Next.js studio UI (web/). The minimum Node version is read
# from web/package.json "engines" (currently >=22.13; Node 24 LTS recommended, see
# web/.nvmrc). Never fatal: without a build FastAPI serves the legacy UI from static/.
web_ui_warning() {
  {
    echo ""
    echo "======================================================================"
    echo " WARNING: the new web UI was NOT built - the legacy UI will be served."
    echo " Reason: $1"
    echo " Fix: install Node.js 24 LTS (or >= ${WEB_NODE_MIN:-22.13}), then run:"
    echo "      cd web && npm ci && npm run build"
    echo "======================================================================"
    echo ""
  } >&2
}
build_web_ui() {
  if [ "${SKIP_WEB_BUILD:-}" = "1" ]; then echo "Skipping web UI build (SKIP_WEB_BUILD=1); the legacy UI will be served."; return 0; fi
  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    web_ui_warning "Node.js/npm not found."; return 0
  fi
  local check
  if ! check=$(node -e '
    const range = require("./web/package.json").engines.node;
    const m = /^>=\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?/.exec(range);
    if (!m) { console.log("?"); process.exit(0); }
    const need = [m[1], m[2] || 0, m[3] || 0].map(Number);
    const have = process.versions.node.split(".").map(Number);
    let ok = true;
    for (let i = 0; i < 3; i++) { if (have[i] !== need[i]) { ok = have[i] > need[i]; break; } }
    console.log(need.join("."));
    process.exit(ok ? 0 : 1);
  ' 2>/dev/null); then
    WEB_NODE_MIN="$check"
    web_ui_warning "Node.js $(node -v) is older than the required >= $check (web/package.json engines)."; return 0
  fi
  WEB_NODE_MIN="$check"
  case "$(node -p 'process.versions.node.split(".")[0]')" in
    24|2[5-9]|[3-9][0-9]) ;;
    *) echo "Note: Node.js $(node -v) is supported; Node 24 LTS is recommended (web/.nvmrc).";;
  esac
  echo "Building the web UI (web/out) with Node.js $(node -v)..."
  local log
  log="$(mktemp "${TMPDIR:-/tmp}/genjustsu-web-build.XXXXXX")"
  if (cd web && npm ci --no-audit --no-fund && npm run build) >"$log" 2>&1; then
    rm -f "$log"
    echo "Web UI built. Set UI=legacy in .env to use the previous interface."
  else
    tail -n 25 "$log" >&2
    web_ui_warning "the web build failed (last lines above; full log: $log)."
  fi
}
build_web_ui || true
.venv/bin/python doctor.py
printf '\nNext: fill .env with your own keys, run bash start.command, then .venv/bin/python doctor.py --require-keys in another terminal\n'

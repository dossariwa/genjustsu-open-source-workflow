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
# Optional: build the Next.js studio UI (web/) when Node 20.9+ is available.
# Never fatal: without it FastAPI keeps serving the legacy UI from static/.
build_web_ui() {
  if [ "${SKIP_WEB_BUILD:-}" = "1" ]; then echo "Skipping web UI build (SKIP_WEB_BUILD=1); the legacy UI will be served."; return 0; fi
  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo "Node.js 20.9+ not found; skipping the optional web UI build. The legacy UI will be served."; return 0
  fi
  if ! node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>20||(a===20&&b>=9)?0:1)'; then
    echo "Node.js $(node -v) is older than 20.9; skipping the optional web UI build. The legacy UI will be served."; return 0
  fi
  echo "Building the web UI (web/out)..."
  if (cd web && npm ci --no-audit --no-fund && npm run build); then
    echo "Web UI built. Set UI=legacy in .env to use the previous interface."
  else
    echo "Web UI build failed; continuing with the legacy UI. Retry later: cd web && npm ci && npm run build"
  fi
}
build_web_ui || true
.venv/bin/python doctor.py
printf '\nNext: fill .env with your own keys, run bash start.command, then .venv/bin/python doctor.py --require-keys in another terminal\n'

#!/usr/bin/env bash
# Run ONE keyless headless turn of the real deepseek-harness agent loop against the CETACEA MCP server.
#   usage: harness/run_headless.sh <mock-script.json> "<task text>"
# env:   CETACEA_HARNESS_DIR  pinned deepseek-harness checkout with `pnpm install` done (default third_party-review/deepseek-harness)
#        CETACEA_HOME         CETACEA state dir (required)
#        CETACEA_PYTHON       python with cetacea installed (default .venv/bin/python)
# Needs Node >= 24.9 (uses nvm 24 in this shell only if the current node is older; system default untouched).
# stdout: session events as JSONL (same format as Harness' own headless driver). MOCK model — no API key, no network model call.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
H="${CETACEA_HARNESS_DIR:-$ROOT/third_party-review/deepseek-harness}"
: "${CETACEA_HOME:?CETACEA_HOME required}"
export CETACEA_PYTHON="${CETACEA_PYTHON:-$ROOT/.venv/bin/python}"
abs() { case "$1" in /*) printf %s "$1";; *) printf %s "$PWD/$1";; esac; }
export CETACEA_MOCK_SCRIPT="$(abs "$1")"; TASK="$2"
export CETACEA_HOME="$(abs "$CETACEA_HOME")" CETACEA_PYTHON="$(abs "$CETACEA_PYTHON")"; H="$(abs "$H")"
node_ok() { node -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>24||(a==24&&b>=9)?0:1)' 2>/dev/null; }
if ! node_ok; then
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"; unset NPM_CONFIG_PREFIX
  # shellcheck disable=SC1091
  if [ -s "$NVM_DIR/nvm.sh" ]; then . "$NVM_DIR/nvm.sh" && nvm use 24 >/dev/null || true; fi
fi
node_ok || { echo "need Node >= 24.9 for deepseek-harness" >&2; exit 3; }
# Overlay must live inside the Harness workspace so bare @deepseek-ai/* imports resolve through its tsconfig paths.
FX="$H/packages/test-support/loader-smoke/tests/fixtures/cetacea-run-$$"   # per-run dir: parallel runs do not race
trap 'rm -rf "$FX"; [ -n "${OWN_WORK:-}" ] && rm -rf "$OWN_WORK"' EXIT
mkdir -p "$FX"; cp "$ROOT"/harness/overlay/* "$FX/"
# restricted tool surface first, then the keyless model + CETACEA MCP entry
cat "$ROOT/harness/cetacea-restricted.patch.yml" "$FX/cetacea-headless.patch.yml" > "$FX/cetacea-combined.patch.yml"
if [ -n "${CETACEA_AGENT_CWD:-}" ]; then WORK="$(abs "$CETACEA_AGENT_CWD")"; else WORK="$(mktemp -d)"; OWN_WORK="$WORK"; fi
export DSH_HOME="$WORK/.dsh" DSH_AGENTS_HOME="$WORK/.agents"
export TSX_TSCONFIG_PATH="$H/tsconfig.json"
cd "$WORK"
TSX="$(cd "$H" && node --input-type=module -e 'console.log(import.meta.resolve("tsx"))')"
node --import "$TSX" \
  "$H/packages/test-support/loader-smoke/tests/fixtures/headless-driver.ts" "$FX/cetacea-combined.patch.yml" "$TASK"

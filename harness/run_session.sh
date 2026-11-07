#!/usr/bin/env bash
# Long-lived JSONL session against the restricted CETACEA MCP tool surface.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-}"
case "$mode" in
  mock) overlay=cetacea-headless.patch.yml ;;
  deepseek) overlay=cetacea-deepseek.patch.yml
    [ -n "${DEEPSEEK_API_KEY:-}" ] || { echo 'DEEPSEEK_API_KEY is required for deepseek mode' >&2; exit 5; } ;;
  *) echo 'usage: harness/run_session.sh <mock|deepseek>' >&2; exit 2 ;;
esac
H="${CETACEA_HARNESS_DIR:-$ROOT/third_party-review/deepseek-harness}"
: "${CETACEA_HOME:?CETACEA_HOME required}"
abs() { case "$1" in /*) printf %s "$1";; *) printf %s "$PWD/$1";; esac; }
CETACEA_HOME="$(abs "$CETACEA_HOME")"
CETACEA_PYTHON="$(abs "${CETACEA_PYTHON:-$ROOT/.venv/bin/python}")"
H="$(abs "$H")"
if [ -n "${CETACEA_MOCK_SCRIPT:-}" ]; then CETACEA_MOCK_SCRIPT="$(abs "$CETACEA_MOCK_SCRIPT")"; fi
if [ -n "${CETACEA_MOCK_LOG:-}" ]; then CETACEA_MOCK_LOG="$(abs "$CETACEA_MOCK_LOG")"; fi
if [ -n "${CETACEA_REQUEST_LEDGER:-}" ]; then CETACEA_REQUEST_LEDGER="$(abs "$CETACEA_REQUEST_LEDGER")"; fi
node_ok() { node -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>24||(a==24&&b>=9)?0:1)' 2>/dev/null; }
if ! node_ok; then
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"; unset NPM_CONFIG_PREFIX
  # shellcheck disable=SC1091
  if [ -s "$NVM_DIR/nvm.sh" ]; then . "$NVM_DIR/nvm.sh" && nvm use 24 >/dev/null || true; fi
fi
node_ok || { echo 'need Node >= 24.9 for deepseek-harness' >&2; exit 3; }
FX="$H/packages/test-support/loader-smoke/tests/fixtures/cetacea-run-$$"
trap 'rm -rf "$FX"; [ -n "${OWN_WORK:-}" ] && rm -rf "$OWN_WORK"' EXIT
mkdir -p "$FX"; cp "$ROOT"/harness/overlay/* "$FX/"
cat "$ROOT/harness/cetacea-restricted.patch.yml" "$FX/$overlay" > "$FX/cetacea-combined.patch.yml"
if [ -n "${CETACEA_AGENT_CWD:-}" ]; then WORK="$(abs "$CETACEA_AGENT_CWD")"; else WORK="$(mktemp -d)"; OWN_WORK="$WORK"; fi
# Capture the operator home before HOME is replaced. The Lightroom bridge
# reads its token from that home; the value is a directory, never the token.
if [ -z "${CETACEA_BRIDGE_HOME:-}" ]; then CETACEA_BRIDGE_HOME="$HOME"; fi
case "$CETACEA_BRIDGE_HOME" in
  /*) ;;
  *) echo 'CETACEA_BRIDGE_HOME must be an absolute directory' >&2; exit 2 ;;
esac
TSX="$(cd "$H" && node --input-type=module -e 'console.log(import.meta.resolve("tsx"))')"
cd "$WORK"
# Only explicit configuration reaches the child; unrelated credentials are excluded.
# HOME is the empty session workspace. CETACEA_BRIDGE_HOME keeps the operator
# account home for the Lightroom bridge only.
child_env=("PATH=$PATH" "HOME=$WORK" "DSH_HOME=$WORK/.dsh" "DSH_AGENTS_HOME=$WORK/.agents" "DSH_TELEMETRY_DISABLED=1" "TSX_TSCONFIG_PATH=$H/tsconfig.json" "CETACEA_HOME=$CETACEA_HOME" "CETACEA_PYTHON=$CETACEA_PYTHON" "CETACEA_BRIDGE_HOME=$CETACEA_BRIDGE_HOME")
for name in CETACEA_MOCK_SCRIPT CETACEA_MOCK_LOG CETACEA_REQUEST_LEDGER CETACEA_MAX_MODEL_REQUESTS CETACEA_MODEL CETACEA_THINKING; do
  if [ -n "${!name+x}" ]; then child_env+=("$name=${!name}"); fi
done
if [ "$mode" = deepseek ]; then child_env+=("DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY"); fi
# Filter before output: no raw stderr file, request headers or credential values.
# A pipe works where sandboxed macOS rejects process-substitution /dev/fd paths.
# fd 3 preserves JSONL stdout; pipefail retains the runner's exit status.
{
  env -i "${child_env[@]}" node --import "$TSX" "$FX/cetacea-session-driver.ts" "$FX/cetacea-combined.patch.yml" \
    2>&1 1>&3 3>&- | "$CETACEA_PYTHON" -m cetacea.harness_guard filter-stderr >&2
} 3>&1

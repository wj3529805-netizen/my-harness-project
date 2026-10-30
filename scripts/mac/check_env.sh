#!/usr/bin/env bash
# CETACEA macOS 环境检查：只读，不安装、不修改任何东西。
# 用法：bash scripts/mac/check_env.sh
set -u
ok(){ printf '  [OK]   %s\n' "$1"; }
bad(){ printf '  [FAIL] %s\n' "$1"; FAIL=1; }
FAIL=0
echo "== CETACEA macOS 环境检查（只读）=="
[ "$(uname -s)" = "Darwin" ] && ok "macOS $(sw_vers -productVersion 2>/dev/null)" || bad "不是 macOS（当前 $(uname -s)）——此脚本用于 Mac 验收"
[ "$(uname -m)" = "arm64" ] && ok "Apple Silicon (arm64)" || bad "非 arm64（$(uname -m)）"
if command -v python3 >/dev/null; then v=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])'); python3 -c 'import sys;sys.exit(0 if sys.version_info>=(3,12) else 1)' && ok "python3 $v" || bad "python3 $v 过低（需要 >= 3.12，推荐 3.13）"; else bad "找不到 python3"; fi
if command -v node >/dev/null; then n=$(node -v); node -e 'process.exit(parseInt(process.versions.node)>=20?0:1)' && ok "node $n（lightroom-mcp 需要 >= 20）" || bad "node $n 过低"; else bad "找不到 node（lightroom-mcp 需要 >= 20；Harness 需要 >= 24.9）"; fi
[ -d "/Applications/Adobe Lightroom Classic" ] && ok "找到 Adobe Lightroom Classic" || bad "未在 /Applications/Adobe Lightroom Classic 找到 Lightroom Classic"
[ -d "$HOME/Library/Application Support/Adobe/Lightroom/Modules/LightroomMCP.lrplugin" ] && ok "Lightroom MCP 插件目录已存在" || echo "  [INFO] 尚未安装 Lightroom MCP 插件（见 docs/MACOS_HANDOFF.md 第 3 节）"
exit $FAIL

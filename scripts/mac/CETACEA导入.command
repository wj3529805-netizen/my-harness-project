#!/bin/bash
# Double-click launcher. It only starts the loopback import desk.
set -euo pipefail
cd "$(dirname "$0")/../.."
if [[ ! -x .venv/bin/python ]]; then
  echo "缺少 .venv。请先在这个仓库用 Python 3.13 创建虚拟环境并安装 CETACEA。"
  read -r _
  exit 1
fi
exec .venv/bin/python -m cetacea.import_desk

#!/usr/bin/env bash
# Linux / 树莓派 Kiosk 打包；产物为单目录 dist/CaosBioGuardKiosk/
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
if ! "$PY" -c "import PyInstaller" >/dev/null 2>&1; then
  echo "缺少 PyInstaller：$PY -m pip install -r requirements-build.txt" >&2
  exit 1
fi

"$PY" -m PyInstaller packaging/edge_kiosk.spec --noconfirm --clean
echo "构建完成：$ROOT/dist/CaosBioGuardKiosk/"

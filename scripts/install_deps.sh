#!/usr/bin/env bash
# CaosBioGuard 一键依赖安装脚本（Linux / macOS）
# 用法: bash scripts/install_deps.sh [edge|web|build|all] [--system]
set -euo pipefail

ROLE="${1:-edge}"
USE_SYSTEM="false"
[ "${2:-}" = "--system" ] && USE_SYSTEM="true"

case "$ROLE" in
  edge|web|build|all) ;;
  *) echo "未知角色: $ROLE（可选: edge / web / build / all）" >&2; exit 1 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- 操作系统与架构识别 ---
OS_NAME="$(uname -s)"
case "$(uname -m)" in
  x86_64|amd64)  ARCH_NAME="x86_64 (64位)" ;;
  aarch64|arm64) ARCH_NAME="ARM64 (64位)" ;;
  armv7l|armv6l) ARCH_NAME="ARM (32位)" ;;
  *)             ARCH_NAME="$(uname -m)" ;;
esac
echo "==> 运行平台: $OS_NAME / CPU 架构: $ARCH_NAME"

# --- 选择基础 Python ---
BASE_PY=""
for c in python3.13 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then BASE_PY="$c"; break; fi
done
if [ -z "$BASE_PY" ]; then
  echo "未找到 Python，请先安装 Python 3.13（Debian/Ubuntu: sudo apt install python3 python3-venv）。" >&2
  exit 1
fi

# --- 创建或复用虚拟环境 ---
VENV_DIR="$ROOT/.venv"
if [ "$USE_SYSTEM" = "true" ]; then
  PY_EXE="$BASE_PY"
  echo "==> 使用系统 Python，不创建 .venv"
else
  if [ ! -d "$VENV_DIR" ]; then
    echo "==> 创建虚拟环境: $VENV_DIR"
    if ! "$BASE_PY" -m venv "$VENV_DIR"; then
      echo "创建虚拟环境失败，请安装 venv 模块（Debian/Ubuntu: sudo apt install python3-venv）。" >&2
      exit 1
    fi
  else
    echo "==> 复用已有虚拟环境: $VENV_DIR"
  fi
  PY_EXE="$VENV_DIR/bin/python"
  if [ ! -x "$PY_EXE" ]; then
    echo "虚拟环境不完整，缺少: $PY_EXE" >&2
    exit 1
  fi
fi

# --- 解析角色对应的依赖文件 ---
req_file() {
  case "$1" in
    edge)  echo "requirements-edge.txt" ;;
    web)   echo "requirements-web.txt" ;;
    build) echo "requirements-build.txt" ;;
  esac
}
if [ "$ROLE" = "all" ]; then
  FILES=(requirements-edge.txt requirements-web.txt requirements-build.txt)
else
  FILES=("$(req_file "$ROLE")")
fi

echo "==> 升级 pip / setuptools / wheel"
"$PY_EXE" -m pip install --upgrade pip setuptools wheel

for f in "${FILES[@]}"; do
  full="requirements/$f"
  if [ ! -f "$full" ]; then
    echo "缺少依赖文件: $full" >&2
    exit 1
  fi
  echo "==> 安装依赖: $full"
  "$PY_EXE" -m pip install -r "$full"
done

echo "==> 依赖安装完成（角色: $ROLE）。建议执行: $PY_EXE -m pytest -q"

#!/bin/bash
# 用法:
#   run_cryoatom.sh <PROJECT> <JOB> <FASTA> <GPU> [EXTRA_ARGS...]
#
# 示例:
#   ./run_cryoatom.sh P164 J243 /home/spuser/sequences/WT_GLP-1R.fasta 0
#   ./run_cryoatom.sh P164 J243 seq.fasta 0 --row-index 2 --map-field map_sharp/path

set -euo pipefail

if [ $# -lt 4 ]; then
  echo "用法: $0 <PROJECT> <JOB> <FASTA> <GPU> [EXTRA_ARGS...]"
  echo "  示例: $0 P164 J243 /home/spuser/sequences/WT_GLP-1R.fasta 0"
  exit 1
fi

PROJECT="$1"
JOB="$2"
FASTA="$3"
GPU="$4"
# 从第 5 个参数开始的都当作额外参数传给 run_cryoatom.py
EXTRA_ARGS=("${@:5}")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_SCRIPT="${SCRIPT_DIR}/run_cryoatom.py"

# 检查 Python 脚本是否存在
if [ ! -f "$PY_SCRIPT" ]; then
  echo "[ERROR] 找不到 Python 脚本: $PY_SCRIPT"
  exit 1
fi

# 检查 FASTA 是否存在
if [ ! -f "$FASTA" ]; then
  echo "[ERROR] 找不到 FASTA 文件: $FASTA"
  exit 1
fi

echo "[DEBUG] 使用 Python 脚本: $PY_SCRIPT"
echo "[DEBUG] PROJECT=$PROJECT JOB=$JOB FASTA=$FASTA GPU=$GPU"
if [ "${#EXTRA_ARGS[@]}" -gt 0 ]; then
  echo "[DEBUG] 追加参数: ${EXTRA_ARGS[*]}"
fi

python "$PY_SCRIPT" \
  --project "$PROJECT" \
  --job "$JOB" \
  --volume-output "volume" \
  --fasta "$FASTA" \
  --gpu "$GPU" \
  "${EXTRA_ARGS[@]}"

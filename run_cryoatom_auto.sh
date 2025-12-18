#!/bin/bash
# 自动调度版：
#   1) 自动选择最空闲 GPU（除非你手动指定）
#   2) 调用 run_cryoatom_auto.py 运行 CryoAtom
#   3) 把 out.cif 拷回 CryoSPARC 原 job 目录，并写日志
#
# 用法：
#   run_cryoatom_auto.sh <PROJECT> <JOB> <FASTA> [GPU] [EXTRA_ARGS...]
#
# 示例：
#   ./run_cryoatom_auto.sh P164 J44 /home/spuser/sequences/WT_GLP-1R.fasta
#   ./run_cryoatom_auto.sh P164 J44 /home/spuser/sequences/WT_GLP-1R.fasta 1
#   ./run_cryoatom_auto.sh P164 J44 seq.fasta "" --row-index 2 --no-copy-map

set -euo pipefail

if [ $# -lt 3 ]; then
  echo "用法: $0 <PROJECT> <JOB> <FASTA> [GPU] [EXTRA_ARGS...]"
  echo "  示例: $0 P164 J44 /home/spuser/sequences/WT_GLP-1R.fasta"
  echo "  示例: $0 P164 J44 seq.fasta \"\" --row-index 2 --no-copy-map"
  exit 1
fi

PROJECT="$1"
JOB="$2"
FASTA="$3"
GPU="${4:-}"                 # 第 4 个参数可选：GPU
EXTRA_ARGS=("${@:5}")        # 第 5 个及其之后的参数全部透传给 Python

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_SCRIPT="${SCRIPT_DIR}/run_cryoatom_auto.py"

# 允许通过环境变量指定 Python，可选：
PYTHON_BIN="${PYTHON:-python}"

echo "[DEBUG] 使用 Python 脚本: $PY_SCRIPT"
echo "[DEBUG] PROJECT=$PROJECT JOB=$JOB FASTA=$FASTA GPU=${GPU:-auto}"
if [ "${#EXTRA_ARGS[@]}" -gt 0 ]; then
  echo "[DEBUG] 追加参数: ${EXTRA_ARGS[*]}"
fi

if [ ! -f "$PY_SCRIPT" ]; then
  echo "[ERROR] 找不到 Python 调度脚本: $PY_SCRIPT"
  exit 1
fi

if [ ! -f "$FASTA" ]; then
  echo "[ERROR] 找不到 FASTA 文件: $FASTA"
  exit 1
fi

# 注意：这里不在脚本里激活 conda，防止静默失败
# 请在命令行手动: conda activate CryoAtom

if [ -z "$GPU" ]; then
  # 不指定 GPU -> 让 Python 脚本自动选择
  "$PYTHON_BIN" "$PY_SCRIPT" \
    --project "$PROJECT" \
    --job "$JOB" \
    --fasta "$FASTA" \
    "${EXTRA_ARGS[@]}"
else
  # 手动指定 GPU
  "$PYTHON_BIN" "$PY_SCRIPT" \
    --project "$PROJECT" \
    --job "$JOB" \
    --fasta "$FASTA" \
    --gpu "$GPU" \
    "${EXTRA_ARGS[@]}"
fi

#!/usr/bin/env bash
set -Eeuo pipefail
TASK_ROOT=/fact_data/xinyaowang/PIM_for_VLA/experiments/2026-11-18-gr00t-power
TASK_SCRATCH=/scratch/xinyaowang/gr00t-power-20261118
TASK_PYTHON=/var/tmp/vla-venv/bin/python
TASK_RUNTIME=/var/tmp/xinyao-gr00t16
TASK_SHARED_LOCK="$TASK_RUNTIME/capture-local.lock"
if [[ "$(hostname -s)" != fact-thor ]]; then
  echo 'This measurement requires fact-thor' >&2
  exit 1
fi
mkdir -p "$TASK_SCRATCH/tmp" "$TASK_SCRATCH/hfmodules" "$TASK_SCRATCH/inductor" "$TASK_SCRATCH/triton"
trap 'printf "%s\n" "$?" > "$TASK_ROOT/results/thor-exit-code.txt"' EXIT
# Coordinate with the existing Thor benchmark lock without rewriting its file.
exec 9<"$TASK_SHARED_LOCK"
flock -n 9 || { echo 'Thor benchmark lock is busy' >&2; exit 73; }
export PYTHONPATH="$TASK_RUNTIME/profile-640x480-20261118/deps:$TASK_RUNTIME/deps"
export HF_HOME="$TASK_SCRATCH/hf" HF_MODULES_CACHE="$TASK_SCRATCH/hfmodules"
export HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false PYTHONDONTWRITEBYTECODE=1 NO_ALBUMENTATIONS_UPDATE=1
export TORCHINDUCTOR_CACHE_DIR="$TASK_SCRATCH/inductor" TRITON_CACHE_DIR="$TASK_SCRATCH/triton"
export TMPDIR="$TASK_SCRATCH/tmp" TORCHINDUCTOR_COMPILE_THREADS=4 OPENBLAS_NUM_THREADS=1
cd "$TASK_ROOT"
{
  date -Is
  hostname
  nvidia-smi
  nvpmodel -q
  "$TASK_PYTHON" -V
  sha256sum source/thor/tools/*.py source/thor/workloads/*.py
} > evidence/thor-environment.txt
"$TASK_PYTHON" -u source/thor/tools/bench_gr00t_power.py \
  --source "$TASK_RUNTIME/source" \
  --checkpoint '/fact_data/xinyaowang/PIM_for_VLA/GR00T N1.6/thor/checkpoint' \
  --output "$TASK_ROOT/results/thor" --rounds 3 --seconds 30 --warmup 4

#!/usr/bin/env bash
#SBATCH --job-name=gr00t-g-power
#SBATCH --partition=cpu-scavenger
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH --no-requeue
#SBATCH --output=/fact_data/xinyaowang/PIM_for_VLA/experiments/2026-11-18-gr00t-power/logs/g-power_%j.log
set -euo pipefail
TASK_ROOT=/fact_data/xinyaowang/PIM_for_VLA/experiments/2026-11-18-gr00t-power
TASK_PYTHON=/fact_data/xinyaowang/conda/envs/chia_env/bin/python
export PYTHONDONTWRITEBYTECODE=1
export TMPDIR=/scratch/xinyaowang/gr00t-g-power-${SLURM_JOB_ID}
export LD_LIBRARY_PATH="$TASK_ROOT/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
mkdir -p "$TMPDIR"
cd "$TASK_ROOT"
"$TASK_PYTHON" - <<'PY'
import hashlib,json
from pathlib import Path
manifest=json.loads(Path('manifest-native.json').read_text())
for name,expected in manifest['sha256'].items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==expected,name
print('Frozen native simulator and inputs verified',flush=True)
PY
for TASK_SMOKE in off on; do
  test ! -e "results/smoke-$TASK_SMOKE"
  mkdir "results/smoke-$TASK_SMOKE"
  bin/pim_vla_sim --config "configs/smoke-$TASK_SMOKE.json" --output "results/smoke-$TASK_SMOKE" \
    > "results/smoke-$TASK_SMOKE/native.log" 2>&1
done
cmp results/smoke-off/raw.json results/smoke-on/raw.json
"$TASK_PYTHON" source/g_power_report.py --stats results/smoke-on/dram-power-stats.json \
  --raw results/smoke-on/raw.json --spec configs/spec-k2.json \
  --model configs/micron-8533-aat-proxy.json --baseline-raw results/smoke-off/raw.json \
  --output results/smoke-on/power-report.json > results/smoke-on/power-summary.json
printf 'Smoke raw results are byte-identical; native counters reconcile\n'
test ! -e results/combined-g
mkdir results/combined-g
cp configs/combined-g.json results/combined-g/input-config.json
/usr/bin/time -v -o results/combined-g/resource.log bin/pim_vla_sim \
  --config configs/combined-g.json --output results/combined-g \
  > results/combined-g/native.log 2>&1
"$TASK_PYTHON" source/g_power_report.py --stats results/combined-g/dram-power-stats.json \
  --raw results/combined-g/raw.json --spec configs/spec-k2.json \
  --model configs/micron-8533-aat-proxy.json --baseline-raw evidence/original-raw.json \
  --output results/combined-g/power-report.json > results/combined-g/power-summary.json
cat results/combined-g/power-summary.json
"$TASK_PYTHON" source/report_and_plot.py

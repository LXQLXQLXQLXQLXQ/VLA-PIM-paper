#!/usr/bin/env python3
"""Combine measured Thor rails and native DRAM counters; plot power/energy ratios."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    repository = Path(__file__).resolve().parents[1]
    parser.add_argument('--data', type=Path, default=repository / 'notes/power-energy-2026-11-18')
    parser.add_argument('--output-root', type=Path, default=repository,
                        help='Write figures/ and figures/data/ below this directory.')
    parser.add_argument('--no-plot', action='store_true', help='Recompute tables using only the standard library.')
    args = parser.parse_args()
    root = args.data.resolve()
    output_root = args.output_root.resolve()
    thor_path = root / 'models/gr00t/thor/measurements.json'
    dram_path = root / 'models/gr00t/power-report.json'
    logic_path = root / 'configs/pim-logic-power-533mhz.json'
    pi_path = root / 'models/pi05/energy-summary-with-pim-logic.json'
    thor, dram, logic, pi = (load(p) for p in (thor_path, dram_path, logic_path, pi_path))
    assert thor.get('finished') and thor['horizon'] == 15 and thor['vl_tokens'] == 371
    assert dram['statistics_validation']['native_raw_byte_identical_to_baseline']
    assert abs(dram['duration_ms'] - 74.409591774) < 1e-8
    blocks = [b for b in thor['blocks'] if b['mode'] == 'fresh_cache']
    assert len(blocks) == 3 and sorted(b['round'] for b in blocks) == [1, 2, 3]
    for b in blocks:
        assert b['seconds'] == 30 and b['ae_count'] > 0
        assert b['own_fresh_cache_dependency_checked'] and b['repeated_output_exact']
        for rail in ('VIN', 'VDD_GPU'):
            p = b['power'][rail]
            assert abs(p['energy_j'] - p['mean_w'] * b['seconds']) < 1e-8
    measured_seconds = sum(b['seconds'] for b in blocks)
    count = sum(b['ae_count'] for b in blocks)
    baseline_w = sum(b['power']['VIN']['energy_j'] for b in blocks) / measured_seconds
    gpu_w = sum(b['power']['VDD_GPU']['energy_j'] for b in blocks) / measured_seconds
    baseline_s = measured_seconds / count
    logic_w = logic['image_reported_total_mW_per_bank'] * logic['PIM_banks'] / 1000
    assert logic['PIM_banks'] == 256
    g_s = dram['duration_ms'] / 1000
    g_w = gpu_w + dram['reference_average_power_W'] + logic_w
    base_j, g_j = baseline_w * baseline_s, g_w * g_s

    def row(name, b, g, ebase, eg, extra):
        result = dict(model=name, baseline_board_average_W=b,
                      estimated_g_average_W=g, baseline_energy_J=ebase,
                      estimated_g_energy_J=eg, power_ratio=b / g,
                      energy_ratio=ebase / eg, estimated_energy_reduction_percent=100 * (1 - eg / ebase))
        result.update(extra)
        return result

    rows = [row('pi0.5', pi['baseline']['board_average_power_W'],
                pi['method_g']['combined_reference_average_power_W'],
                pi['baseline']['board_energy_J_per_completed_AE_chunk'],
                pi['method_g']['combined_reference_energy_J'],
                dict(GPU_average_power_proxy_W=pi['method_g']['GPU_average_power_proxy_W'],
                     DRAM_reference_average_power_W=pi['method_g']['DRAM_reference_average_power_W'],
                     PIM_logic_full_active_reference_W=pi['method_g']['PIM_logic_full_active_reference_W'],
                     baseline_completion_period_ms=pi['baseline']['average_AE_completion_period_ms'],
                     g_pair_duration_ms=pi['method_g']['duration_ms'])),
            row('GR00T N1.6', baseline_w, g_w, base_j, g_j,
                dict(GPU_average_power_proxy_W=gpu_w,
                     DRAM_reference_average_power_W=dram['reference_average_power_W'],
                     PIM_logic_full_active_reference_W=logic_w,
                     baseline_completion_period_ms=baseline_s * 1000, g_pair_duration_ms=g_s * 1000))]
    for r in rows:
        assert abs(r['estimated_g_average_W'] * r['g_pair_duration_ms'] / 1000 - r['estimated_g_energy_J']) < 1e-10
        assert abs(r['baseline_board_average_W'] * r['baseline_completion_period_ms'] / 1000 - r['baseline_energy_J']) < 1e-10

    assumptions = [
        'Numerator: measured whole-board VIN. Denominator: baseline VDD_GPU proxy + modeled DRAM + supplied PIM logic reference; other board/CPU/SoC power is omitted.',
        'Baseline time is measured steady AE completion period. Proposed time is a single simulated combined pair, not a multi-frame steady-state simulation.',
        'Both models use the same Micron IDD proxy (16-Gbit current data with unchanged 8-Gbit simulated dies), rho=0.5, and uncalibrated PIM internal-column energies.',
        'PIM logic is the same 5.40928-W, 256-bank full-active ASAP7 reference for both models, not trace-weighted logic power. GR00T has no RoPE operations; the fixed hardware-reference scenario still includes its RoPE allocation.',
        'pi0.5 reuses its prior frozen measurement/simulation; GR00T uses this newly measured fresh-cache baseline and a byte-identical instrumented rerun of n16-f.'
    ]
    report = dict(schema_version=1, metric='simplified power and per-AE-chunk energy ratios',
                  formula='R_energy = (P_VIN_baseline * T_baseline) / ((P_GPU_baseline + P_DRAM_g + P_PIM_logic) * T_g)',
                  physical_power_calibrated=False, valid_as_matched_full_board_efficiency=False,
                  models=rows, GR00T_measurement_seconds=measured_seconds,
                  GR00T_completed_AE_chunks=count, assumptions=assumptions,
                  input_path_base='notes/power-energy-2026-11-18',
                  inputs_sha256={p.relative_to(root).as_posix(): sha(p) for p in (thor_path, dram_path, logic_path, pi_path)},
                  validation=dict(three_power_rounds_complete=True, native_raw_byte_identical=True,
                                  power_energy_identities_hold=True, same_logic_reference=True))
    output = output_root / 'figures/data'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'power-energy-comparison.json').write_text(json.dumps(report, indent=2) + '\n')
    with (output / 'power-energy-comparison.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    power_lines = ['| 模型 | 基线板上功耗/W | GPU代理/W | DRAM/W | PIM逻辑/W | g合计/W |',
                   '|---|---:|---:|---:|---:|---:|']
    energy_lines = ['| 模型 | 基线周期/ms | g单pair/ms | 基线能耗/J | g能耗/J | 功耗比 | 能耗比 |',
                    '|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        power_lines.append(f"| {r['model']} | {r['baseline_board_average_W']:.3f} | {r['GPU_average_power_proxy_W']:.3f} | {r['DRAM_reference_average_power_W']:.3f} | {r['PIM_logic_full_active_reference_W']:.3f} | {r['estimated_g_average_W']:.3f} |")
        energy_lines.append(f"| {r['model']} | {r['baseline_completion_period_ms']:.3f} | {r['g_pair_duration_ms']:.3f} | {r['baseline_energy_J']:.4f} | {r['estimated_g_energy_J']:.4f} | {r['power_ratio']:.3f} | {r['energy_ratio']:.3f} |")
    text = '# pi0.5 与 GR00T 功耗、能耗对比\n\n' + '\n'.join(power_lines) + '\n\n' + '\n'.join(energy_lines)
    text += '\n\n比值为基线除以估算方案；大于 1 表示该估算下方案功耗或能耗更低。两图分别给出功耗比和用户此前定义的能耗比。\n\n'
    text += f'GR00T：3 轮各 30 秒，共完成 {count} 个 AE chunk。完整仿真 raw.json 与原 640×480 n16-f 结果逐字节一致。\n\n'
    text += '**此结果为此前约定的简化估算，不是统一范围的整板能效测量。**\n\n'
    text += '\n'.join('- ' + x for x in assumptions) + '\n'
    (output / 'power-energy-comparison.zh-CN.md').write_text(text)

    if args.no_plot:
        print(json.dumps(rows, indent=2))
        return
    cache = Path(os.environ.get('MPLCONFIGDIR', str(output_root / 'figures/.cache/power-energy-ratios')))
    cache.mkdir(parents=True, exist_ok=True)
    os.environ['MPLCONFIGDIR'] = str(cache)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'pdf.fonttype': 42,
                         'ps.fonttype': 42, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.9))
    labels = [r'$\pi_{0.5}$', 'GR00T N1.6']
    colors = ['#365B83', '#B97850']
    for ax, key, title in zip(axes, ('power_ratio', 'energy_ratio'),
                              ('(a) Average power ratio', '(b) Energy per AE chunk ratio')):
        values = [r[key] for r in rows]
        ax.bar(np.arange(2), values, width=0.48, color=colors, edgecolor='white', zorder=3)
        ax.axhline(1, color='#6E7378', linewidth=1, linestyle='--', zorder=2)
        ax.set_xticks(np.arange(2), labels)
        ax.set_ylim(0, max(1.5, max(values) * 1.22))
        ax.set_title(title, fontsize=11, pad=13)
        ax.set_ylabel('Baseline / proposed estimate')
        ax.yaxis.grid(True, color='#E7E9EC', linewidth=0.7)
        ax.set_axisbelow(True)
        for i, value in enumerate(values):
            ax.text(i, value + ax.get_ylim()[1] * 0.025, f'{value:.2f}'+r'$\times$',
                    ha='center', va='bottom', fontsize=12, fontweight='bold')
    fig.subplots_adjust(left=0.08, right=0.98, wspace=0.35, top=0.84, bottom=0.24)
    fig.text(0.5, 0.10, 'Baseline: measured board VIN. Proposed: GPU proxy + DRAM model + PIM logic.',
             ha='center', fontsize=8.3, color='#454C54')
    fig.text(0.5, 0.045, 'Simplified estimate; board scope and steady-period / single-pair timing differ.',
             ha='center', fontsize=8.1, color='#454C54')
    figure_dir = output_root / 'figures'
    figure_dir.mkdir(exist_ok=True)
    for ext in ('png', 'pdf', 'svg'):
        fig.savefig(figure_dir / ('power-energy-ratios.' + ext), dpi=300, bbox_inches='tight')
    plt.close(fig)
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()

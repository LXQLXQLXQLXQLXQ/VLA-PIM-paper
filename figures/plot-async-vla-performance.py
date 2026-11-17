#!/usr/bin/env python3
"""Plot the retained asynchronous VLA configurations from existing paper values.

The two a baselines and b/c/former-e/former-g are shown as a/a/b/c/d/e.
Only T_async VLA is plotted; the rate gain is its inverse ratio, annotated
with one arrow from the a baseline group to the final VLA-PIM bar.
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=here/'data/async-vla-performance.json')
    parser.add_argument('--out', type=Path, default=here)
    args = parser.parse_args()
    configurations = json.loads(args.data.read_text())['configurations']
    cycles = [entry['cycle_ms'] for entry in configurations]
    rate_gains = [baseline/cycles[-1] for baseline in cycles[:2]]
    plt.rcParams.update({
        'font.size': 8, 'axes.labelsize': 8.5,
        'axes.spines.top': False, 'axes.spines.right': False,
        'axes.edgecolor': '#52514e', 'xtick.color': '#52514e',
        'ytick.color': '#52514e', 'axes.axisbelow': True,
        'pdf.fonttype': 42, 'ps.fonttype': 42,
    })
    fig, ax = plt.subplots(figsize=(3.5, 2.35))
    positions = list(range(len(configurations)))
    colors = ['#a8adb4', '#808892', '#78a8da', '#4a8dce', '#3272b1', '#eb6834']
    ax.bar(positions, cycles, width=0.42, color=colors, zorder=3)
    for x, value in zip(positions, cycles):
        ax.text(x, value+2.0, f'{value:.2f}', ha='center', va='bottom', fontsize=6.8)

    # The arrow spans the two a references as a group and points to e.
    # Rates are not a second plotted metric: f_e/f_a = T_a/T_e.
    baseline_center = (positions[0]+positions[1])/2
    ax.annotate('', xy=(positions[-1], cycles[-1]+10), xytext=(baseline_center, 159),
                arrowprops={'arrowstyle': '-|>', 'color': '#b44f26', 'lw': 1.15,
                            'connectionstyle': 'angle,angleA=0,angleB=-90,rad=3'})
    ax.text((baseline_center+positions[-1])/2, 164,
            f'AE rate: {rate_gains[0]:.2f}× (serial), {rate_gains[1]:.2f}× (dual)',
            ha='center', va='bottom', fontsize=7.0, color='#a54823')
    ax.set_ylabel(r'$T_{\mathrm{async\ VLA}}$ (ms)')
    ax.set_ylim(0, 185)
    ax.set_xlim(-0.55, len(configurations)-0.45)
    ax.set_yticks([0, 50, 100, 150])
    ax.set_xticks(positions)
    ax.set_xticklabels(['a\nserial', 'a\ndual', 'b', 'c', 'd', 'e'], fontsize=7.5)
    ax.tick_params(axis='x', length=0, pad=5)
    ax.tick_params(axis='y', length=3, labelsize=7.5)
    ax.grid(axis='y', color='#e6e5e1', linewidth=0.6)
    fig.subplots_adjust(left=0.17, right=0.99, bottom=0.19, top=0.98)
    args.out.mkdir(parents=True, exist_ok=True)
    for suffix in ['pdf', 'png']:
        fig.savefig(args.out/f'fig_async_vla_performance.{suffix}', dpi=600,
                    bbox_inches='tight', pad_inches=0.04)
    plt.close(fig)
    print('Rendered T_async VLA for a-serial, a-dual, b, c, d, e; '
          f'AE rate gains: {rate_gains[0]:.2f}x / {rate_gains[1]:.2f}x.')


if __name__ == '__main__':
    main()

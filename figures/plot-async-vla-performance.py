#!/usr/bin/env python3
"""Plot pi0.5 and archived GR00T N1.6 in two side-by-side panels.

Both panels together fit one paper column. GR00T a-serial is marked as a
sum of measured solo-phase means; its unavailable a-dual is never a zero bar.
GR00T native n16-b/c/d/f map to displayed b/c/d/e, with no RoPE stage.
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def rate_arrow(ax, start, end, cycle, y, label, color):
    ax.annotate('', xy=(end, cycle+9), xytext=(start, y),
                arrowprops={'arrowstyle': '-|>', 'color': color, 'lw': 1.0,
                            'connectionstyle': 'angle,angleA=0,angleB=-90,rad=2'})
    ax.text((start+end)/2, y+4, label, ha='center', va='bottom',
            fontsize=5.9, color=color)


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=here/'data/async-vla-performance.json')
    parser.add_argument('--out', type=Path, default=here)
    args = parser.parse_args()
    data = json.loads(args.data.read_text())
    models = data['models']
    plt.rcParams.update({
        'font.size': 8, 'axes.labelsize': 8.5,
        'axes.spines.top': False, 'axes.spines.right': False,
        'axes.edgecolor': '#52514e', 'xtick.color': '#52514e',
        'ytick.color': '#52514e', 'axes.axisbelow': True,
        'pdf.fonttype': 42, 'ps.fonttype': 42,
    })
    fig, axes = plt.subplots(1, 2, figsize=(3.5, 2.3), sharey=True)
    positions = list(range(6))
    colors = ['#a8adb4', '#808892', '#78a8da', '#4a8dce', '#3272b1', '#eb6834']
    titles = [r'(a) $\pi_{0.5}$', '(b) GR00T N1.6']
    for ax, model, title in zip(axes, models, titles):
        for index, entry in enumerate(model['configurations']):
            x = index
            value = entry['cycle_ms']
            if value is None:
                ax.text(x, 4, 'N/A', ha='center', va='bottom',
                        color='#606060', fontsize=5.2)
                continue
            ax.bar(x, value, width=0.44, color=colors[index], zorder=3)
            derived = entry.get('kind') == 'sum_of_measured_standalone_phase_means'
            label = f'{value:.2f}' + ('†' if derived else '')
            ax.text(x, value+2.5, label, rotation=90, ha='center', va='bottom',
                    fontsize=5.7, color='#303030')

        # Inverse cycle ratios are within-model AE output-rate gains.
        cycles = [e['cycle_ms'] for e in model['configurations']]
        label = f'AE rate: {cycles[0]/cycles[-1]:.2f}×'
        if cycles[1] is not None:
            label += f' / {cycles[1]/cycles[-1]:.2f}×'
        rate_arrow(ax, 0.30, 5.43, cycles[-1], 194, label, '#a54823')
        ax.set_title(title, fontsize=7.2, pad=4)
        ax.set_ylim(0, 220)
        ax.set_xlim(-0.55, 5.70)
        ax.set_yticks([0, 50, 100, 150])
        ax.set_xticks(positions)
        ax.set_xticklabels(['a-s', 'a-d', 'b', 'c', 'd', 'e'], fontsize=6.0)
        ax.tick_params(axis='x', length=0, pad=4)
        ax.tick_params(axis='y', length=2.5, labelsize=6.5)
        ax.grid(axis='y', color='#e6e5e1', linewidth=0.6)
    axes[0].set_ylabel(r'$T_{\mathrm{async\ VLA}}$ (ms)', fontsize=8)
    axes[1].tick_params(axis='y', left=False)
    axes[1].spines['left'].set_visible(False)
    fig.subplots_adjust(left=0.145, right=0.99, bottom=0.15, top=0.86, wspace=0.15)
    args.out.mkdir(parents=True, exist_ok=True)
    for suffix in ['pdf', 'png']:
        fig.savefig(args.out/f'fig_async_vla_performance.{suffix}', dpi=600,
                    bbox_inches='tight', pad_inches=0.04)
    plt.close(fig)
    print('Rendered pi0.5 left panel and GR00T N1.6 right panel in one column; '
          'GR00T serial is derived and dual-stream is N/A.')


if __name__ == '__main__':
    main()

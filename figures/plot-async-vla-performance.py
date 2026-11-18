#!/usr/bin/env python3
"""Plot pi0.5 and archived GR00T N1.6 in two side-by-side panels.

Both panels together fit one paper column. GR00T a-serial is marked as a
sum of measured solo-phase means; a-dual uses the supplied compiled AE p50.
GR00T native n16-b/c/d/f map to displayed b/c/d/e, with no RoPE stage.
"""
import argparse
import json
import shutil
from pathlib import Path
from figure_style import use_arial, export_tiff

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BAR_WIDTH = 0.68


def rate_arrow(ax, baseline, cycle, label, color):
    # Span the full bar group, from a-s's left edge to e's right edge.
    ax.plot([-BAR_WIDTH/2, 5+BAR_WIDTH/2], [baseline, baseline], color=color, lw=0.75,
            linestyle=(0, (3, 2)), zorder=4)
    # Meet e's upper-right corner and clear the value label with the full head.
    ax.arrow(5+BAR_WIDTH/2, baseline, 0, cycle-baseline, width=0,
             head_width=0.18, head_length=6, length_includes_head=True,
             facecolor=color, edgecolor=color, lw=0.9, zorder=5)
    ax.annotate(label, xy=(5+BAR_WIDTH/2, (baseline+cycle)/2+3),
            xytext=(-1.2, 0), textcoords='offset points', ha='right', va='center',
            fontsize=7, color=color, zorder=6,
            bbox={'facecolor': 'white', 'edgecolor': 'none', 'pad': 0.4})


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=here/'data/async-vla-performance.json')
    parser.add_argument('--out', type=Path, default=here)
    args = parser.parse_args()
    data = json.loads(args.data.read_text())
    models = data['models']
    use_arial()
    plt.rcParams.update({
        'font.size': 8, 'axes.labelsize': 8,
        'axes.spines.top': False, 'axes.spines.right': False,
        'axes.edgecolor': '#52514e', 'xtick.color': '#52514e',
        'ytick.color': '#52514e', 'axes.axisbelow': True,
        'pdf.fonttype': 42, 'ps.fonttype': 42,
    })
    fig, axes = plt.subplots(1, 2, figsize=(3.5, 1.95), sharey=True)
    positions = list(range(6))
    colors = ['#a8adb4', '#808892', '#78a8da', '#4a8dce', '#3272b1', '#eb6834']
    titles = [r'(a) $\pi_{0.5}$', '(b) GR00T N1.6']
    for ax, model, title in zip(axes, models, titles):
        cycles = [e.get('plot_ms', e['cycle_ms']) for e in model['configurations']]
        # The shorter gain arrow needs room for both the gain and bar values.
        tight_gain_window = cycles[0]-cycles[-1] < 40
        for index, entry in enumerate(model['configurations']):
            x = index
            value = cycles[index]
            if value is None:
                ax.text(x, 4, 'N/A', ha='center', va='bottom',
                        color='#606060', fontsize=7)
                continue
            ax.bar(x, value, width=BAR_WIDTH, color=colors[index], zorder=3)
            derived = entry.get('kind') == 'sum_of_measured_standalone_phase_means'
            label = f'{value:.0f}' + ('†' if derived else '')
            label_x = x
            if index == 5:
                label_x -= 0.05
            elif tight_gain_window and index == 4:
                label_x -= 0.30
            label_y = value if tight_gain_window and index == 5 else value+2.5
            ax.text(label_x, label_y, label, ha='center', va='bottom',
                    fontsize=7, color='#303030', zorder=6,
                    bbox={'facecolor': 'white', 'edgecolor': 'none', 'pad': 0.2})

        # Inverse cycle ratios are within-model AE output-rate gains.
        label = f'{cycles[0]/cycles[-1]:.2f}×'
        rate_arrow(ax, cycles[0], cycles[-1], label, '#a54823')
        ax.set_title(title, fontsize=8, pad=4)
        ax.set_ylim(0, 164)
        ax.set_xlim(-0.47, 5.47)
        ax.set_yticks([0, 50, 100, 150])
        ax.set_xticks(positions)
        ax.set_xticklabels(['a-s', 'a-d', 'b', 'c', 'd', 'e'], fontsize=7)
        ax.tick_params(axis='x', length=0, pad=4)
        ax.tick_params(axis='y', length=2, pad=2, labelsize=8)
        ax.grid(axis='y', color='#e6e5e1', linewidth=0.6)
    axes[0].set_ylabel(r'$T_{\mathrm{Async}}$ (ms)', fontsize=8, labelpad=2)
    axes[1].tick_params(axis='y', left=False)
    axes[1].spines['left'].set_visible(False)
    fig.subplots_adjust(left=0.13, right=0.995, bottom=0.14, top=0.87, wspace=0.12)
    args.out.mkdir(parents=True, exist_ok=True)
    for suffix in ['pdf', 'png']:
        fig.savefig(args.out/f'fig_async_vla_performance.{suffix}', dpi=600,
                    bbox_inches='tight', pad_inches=0.025)
    shutil.copyfile(args.out/'fig_async_vla_performance.png',
                    args.out/'fig7_async_vla_performance.png')
    export_tiff(args.out/'fig7_async_vla_performance.png',
                args.out/'fig7_async_vla_performance.tif')
    plt.close(fig)
    print('Rendered pi0.5 left panel and GR00T N1.6 right panel in one column; '
          'GR00T serial is derived and compiled dual-stream AE p50 is included.')


if __name__ == '__main__':
    main()

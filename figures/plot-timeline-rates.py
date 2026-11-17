#!/usr/bin/env python3
"""Render Figures 7 and 10 from the committed native-result snapshot.

PDFs are vector graphics; PNG previews use 600 dpi. No simulation is rerun.
Figure 7 pairs two compact overviews without x axes with a native down-input
zoom and an illustration of the minimum DQ window for a GPU read request.
"""
import argparse
import json
from pathlib import Path
from runpy import run_path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

BLUE, ORANGE = '#2a78d6', '#eb6834'
GREENS = ('#1baf7a', '#12734f')
INK, GRID = '#52514e', '#e6e5e1'


def save(fig, out, name):
    fig.savefig(out / (name + '.pdf'), bbox_inches='tight', pad_inches=0.04)
    fig.savefig(out / (name + '.png'), dpi=600, bbox_inches='tight', pad_inches=0.04)
    plt.close(fig)


# Figure 7 has one canonical implementation in its classified source bundle.
timeline = run_path(str(Path(__file__).resolve().parent/'fig7/scripts/plot_figure.py'))['timeline']


def rates(data, out):
    fig, ax = plt.subplots(figsize=(3.5, 2.65))
    width = 0.36
    for index, group in enumerate(data['rates']):
        for offset, key, color in [(-width/2, 'ae_hz', ORANGE), (width/2, 'vlm_hz', GREENS[0])]:
            value = group[key]
            ax.bar(index+offset, value, width*0.92, color=color)
            ax.text(index+offset, value+0.22, f'{value:.2f}', ha='center',
                    va='bottom', fontsize=6.3, color='black')
    ax.set_xticks(range(len(data['rates'])))
    ax.set_xticklabels([g['label'] for g in data['rates']], fontsize=6.6)
    ax.set_ylabel('Frequency (Hz)')
    ax.set_ylim(0, 20.3)
    ax.set_yticks([0, 5, 10, 15, 20])
    ax.grid(axis='x', visible=False)
    fig.legend(handles=[Patch(facecolor=ORANGE, label='AE action chunks'),
                        Patch(facecolor=GREENS[0], label='VLM KV refreshes')],
               loc='upper center', ncol=2, bbox_to_anchor=(0.54, 1.02),
               fontsize=6.6, handlelength=1.3, columnspacing=1.0)
    fig.subplots_adjust(left=0.13, right=0.99, top=0.86, bottom=0.18)
    save(fig, out, 'fig_decoupled_rate')


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=here/'data/timeline-rates-20261117.json')
    parser.add_argument('--out', type=Path, default=here)
    parser.add_argument('--detail-data', type=Path, default=here/'data/streaming-input-gap-20261117.json')
    parser.add_argument('--figure', choices=['timeline', 'rates', 'both'], default='both')
    args = parser.parse_args()
    data = json.loads(args.data.read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({'font.size':7.5, 'axes.titlesize':8.2,
        'axes.labelsize':7.5, 'axes.spines.top':False, 'axes.spines.right':False,
        'axes.edgecolor':INK, 'xtick.color':INK, 'ytick.color':INK,
        'axes.grid':True, 'grid.color':GRID, 'grid.linewidth':0.6,
        'axes.axisbelow':True, 'legend.frameon':False,
        'pdf.fonttype':42, 'ps.fonttype':42})
    if args.figure in ['timeline', 'both']:
        timeline(data, args.out, json.loads(args.detail_data.read_text()))
    if args.figure in ['rates', 'both']:
        rates(data, args.out)
    print(f'Rendered vector PDF and 600 dpi PNG: {args.figure}.')


if __name__ == '__main__':
    main()

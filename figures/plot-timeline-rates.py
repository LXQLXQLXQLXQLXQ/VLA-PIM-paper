#!/usr/bin/env python3
"""Render Figures 7 and 10 from the committed native-result snapshot.

PDFs are vector graphics; PNG previews use 600 dpi. No simulation is rerun.
Figure 7 shows PIM phases and DQ burst starts in two panels without x axes.
A native streaming-input gap is identified using its DQ timing constraints.
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Ellipse

BLUE, ORANGE = '#2a78d6', '#eb6834'
GREENS = ('#1baf7a', '#12734f')
INK, GRID, EPOCH = '#52514e', '#e6e5e1', '#deddd9'


def save(fig, out, name):
    fig.savefig(out / (name + '.pdf'), bbox_inches='tight', pad_inches=0.04)
    fig.savefig(out / (name + '.png'), dpi=600, bbox_inches='tight', pad_inches=0.04)
    plt.close(fig)


def timeline(data, out, detail):
    tick = data['clock_ps'] / 1e6
    fig = plt.figure(figsize=(7.2, 2.25))
    grid = fig.add_gridspec(2, 1, hspace=0.46)
    example = detail['read_excluded_example']
    selected_start = example['left']['end_ck']
    selected_end = example['right']['start_ck']
    assert selected_end-selected_start == example['gap_ck']
    assert example['gap_ck'] < detail['required_vlm_window_ck']['R']
    for index, case in enumerate(data['timeline_cases']):
        ax = fig.add_subplot(grid[index])
        us = lambda ck: (ck-case['lo_ck']) * tick
        for start, end in case['io_epochs_ck']:
            ax.axvspan(us(start), us(end), color=EPOCH, lw=0, zorder=0)
        for e in case['events']:
            if e['kind'] != 'pim':
                continue
            lo, hi = us(e['start_ck']), us(e['end_ck'])
            ax.broken_barh([(lo, hi-lo)], (0.70, 0.60),
                           facecolor=BLUE, edgecolor='white', linewidth=0.5, zorder=3)
            if hi-lo > 14:
                ax.text((lo+hi)/2, 1, e['name'].replace('_', '/'),
                        ha='center', va='center', fontsize=6.8, color='white', zorder=4)
        ax.vlines([us(s) for s, e in case['pim_dq_bursts_ck']], -0.30, 0.30,
                  colors=INK, linewidth=0.22, zorder=3)
        if index == 0:
            middle = us((selected_start+selected_end)/2)
            # Locator circle; the 14 CK interval is too short to resolve here.
            ax.add_patch(Ellipse((middle, 0), 6.3, 0.85, fill=False,
                                 edgecolor=ORANGE, linewidth=1.1, zorder=5))
            ax.annotate(f'Streaming input: {example["gap_ck"]} CK gaps; VLM RD needs '
                        f'{detail["required_vlm_window_ck"]["R"]} CK',
                        xy=(middle+2.8, 0.23),
                        xytext=(21, 0.50), fontsize=6.6, color=ORANGE,
                        arrowprops={'arrowstyle':'->', 'color':ORANGE, 'lw':0.8},
                        ha='left', va='center', zorder=6)
        else:
            ax.add_patch(Ellipse((4, 0), 6.3, 0.85, fill=False,
                                 edgecolor=ORANGE, linewidth=1.1, zorder=5))
            ax.annotate('Bulk input load', xy=(6.3, 0.23),
                        xytext=(27, 0.50), fontsize=6.8, color=ORANGE,
                        arrowprops={'arrowstyle':'->', 'color':ORANGE, 'lw':0.8},
                        ha='left', va='center', zorder=6)
            start, end = us(case['io_epochs_ck'][0][1]), us(case['io_epochs_ck'][1][0])
            assert not any(s < case['io_epochs_ck'][1][0] and e > case['io_epochs_ck'][0][1]
                           for s, e in case['pim_dq_bursts_ck'])
            ax.annotate('', xy=(start+0.7, -0.02), xytext=(end-0.7, -0.02),
                        arrowprops={'arrowstyle':'<->', 'color':GREENS[1], 'lw':0.9}, zorder=5)
            ax.text((start+end)/2, -0.36, f'VLM DQ window: {end-start:.1f} µs',
                    ha='center', va='center', fontsize=6.4, color=GREENS[1], zorder=5)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(['PIM DQ bursts (ch 0)', 'PIM stages'])
        ax.set_ylim(-0.57, 1.40)
        ax.set_xlim(0, us(case['hi_ck']))
        ax.set_xticks([])
        ax.spines['bottom'].set_visible(False)
        ax.grid(axis='y', visible=False)
        ax.set_title(case['title'], loc='left', pad=4)
    fig.legend(handles=[Patch(facecolor=EPOCH, label='I/O epoch (DQ owned by PIM)')],
               loc='upper right', bbox_to_anchor=(0.99, 1.01), fontsize=7)
    fig.subplots_adjust(left=0.165, right=0.99, top=0.86, bottom=0.04)
    save(fig, out, 'fig7_step_timeline')


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

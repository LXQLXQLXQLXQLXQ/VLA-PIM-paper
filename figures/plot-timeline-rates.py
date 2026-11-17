#!/usr/bin/env python3
"""Render Figures 7 and 10 from the committed native-result snapshot.

PDFs are vector graphics; PNG previews use 600 dpi. No simulation is rerun.
VLM kernel intervals are cut at recorded AE GPU events, rather than painting
each kernel's start-to-end envelope across its pauses.
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


def subtract_intervals(start, end, excluded):
    """Keep the exact parts of [start, end) outside the excluded intervals."""
    result = []
    cursor = start
    for lo, hi in sorted(excluded):
        if hi <= cursor:
            continue
        if lo >= end:
            break
        if lo > cursor:
            result.append((cursor, min(lo, end)))
        cursor = max(cursor, hi)
        if cursor >= end:
            break
    if cursor < end:
        result.append((cursor, end))
    return result


def kernel_segments(case, tick):
    origin = case['lo_ck'] * tick
    end = case['hi_ck'] * tick
    excluded = [(e['start_ck'] * tick, e['end_ck'] * tick)
                for e in case['events'] if e['kind'] == 'gpu']
    spans = []
    for kernel in case['vlm_kernels']:
        lo = max(origin, kernel['start_us'])
        hi = min(end, kernel['end_us'])
        for start, finish in subtract_intervals(lo, hi, excluded):
            assert finish > start
            assert all(min(finish, b) - max(start, a) <= 1e-8 for a, b in excluded)
            spans.append((start - origin, finish - origin, kernel['ordinal']))
    return spans


def save(fig, out, name):
    fig.savefig(out / (name + '.pdf'), bbox_inches='tight', pad_inches=0.04)
    fig.savefig(out / (name + '.png'), dpi=600, bbox_inches='tight', pad_inches=0.04)
    plt.close(fig)


def draw_kernels(ax, spans, y, height=0.62):
    for start, end, ordinal in spans:
        lo, hi = start, end
        if hi <= lo:
            continue
        # Alternating shades identify consecutive kernels. Gaps preserve time.
        ax.broken_barh([(lo, hi-lo)], (y-height/2, height),
                       facecolor=GREENS[ordinal % 2], linewidth=0, zorder=3)


def timeline(data, out):
    tick = data['clock_ps'] / 1e6
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 3.25))
    for index, case in enumerate(data['timeline_cases']):
        ax = axes[index]
        us = lambda ck: (ck-case['lo_ck']) * tick
        spans = kernel_segments(case, tick)
        for start, end in case['io_epochs_ck']:
            ax.axvspan(us(start), us(end), color=EPOCH, lw=0, zorder=0)
        for e in case['events']:
            if e['kind'] != 'pim':
                continue
            lo, hi = us(e['start_ck']), us(e['end_ck'])
            ax.broken_barh([(lo, hi-lo)], (1.69, 0.62),
                           facecolor=BLUE, edgecolor='white', linewidth=0.5, zorder=3)
            if hi-lo > 14:
                ax.text((lo+hi)/2, 2, e['name'].replace('_', '/'),
                        ha='center', va='center', fontsize=6.8, color='white', zorder=4)
        # Mark event timestamps so nanosecond bursts remain visible at paper
        # scale without widening their physical durations in the source data.
        ax.vlines([us(s) for s, e in case['pim_dq_bursts_ck']], 0.69, 1.31,
                  colors=INK, linewidth=0.22, zorder=3)
        draw_kernels(ax, spans, 0)
        if index == 0:
            # QKV input WR bursts verified from the native direction/stage trace.
            ax.add_patch(Ellipse((17, 1), 25, 0.95, fill=False,
                                 edgecolor=ORANGE, linewidth=1.25, zorder=5))
            ax.annotate('Repeated streaming inputs', xy=(25, 1.27),
                        xytext=(52, 1.50), fontsize=7.0, color=ORANGE,
                        arrowprops={'arrowstyle':'->', 'color':ORANGE, 'lw':0.8},
                        ha='left', va='center', zorder=6)
        else:
            ax.add_patch(Ellipse((4.0, 1), 6.3, 0.95, fill=False,
                                 edgecolor=ORANGE, linewidth=1.25, zorder=5))
            ax.annotate('Bulk input load', xy=(6.3, 1.25),
                        xytext=(27, 1.50), fontsize=7.0, color=ORANGE,
                        arrowprops={'arrowstyle':'->', 'color':ORANGE, 'lw':0.8},
                        ha='left', va='center', zorder=6)
            # The interval after the first I/O epoch and before the next is
            # PIM-DQ-free. It is an opportunity for VLM service, not an SM trace.
            epochs = case['io_epochs_ck']
            start, end = us(epochs[0][1]), us(epochs[1][0])
            assert not any(s < epochs[1][0] and e > epochs[0][1]
                           for s, e in case['pim_dq_bursts_ck'])
            ax.annotate('', xy=(start+0.7, 0.98), xytext=(end-0.7, 0.98),
                        arrowprops={'arrowstyle':'<->', 'color':GREENS[1], 'lw':1.0},
                        zorder=5)
            ax.text((start+end)/2, 0.64, f'VLM DQ window: {end-start:.1f} µs',
                    ha='center', va='center', fontsize=6.7, color=GREENS[1], zorder=5)
        ax.set_yticks([0, 1, 2])
        ax.set_yticklabels(['VLM kernels', 'PIM DQ bursts (ch 0)', 'PIM stages'])
        ax.set_ylim(-0.5, 2.5)
        ax.set_xlim(0, us(case['hi_ck']))
        ax.grid(axis='y', visible=False)
        ax.set_title(case['title'], loc='left', pad=4)
        if index == 1:
            ax.set_xlabel('Time since layer 0 of denoising step 0 starts (µs)', labelpad=2)

    fig.legend(handles=[Patch(facecolor=EPOCH, label='I/O epoch (DQ owned by PIM)')],
               loc='upper right', bbox_to_anchor=(0.99, 1.01), fontsize=7)
    fig.subplots_adjust(left=0.165, right=0.995, top=0.92, bottom=0.13, hspace=0.62)
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
        timeline(data, args.out)
    if args.figure in ['rates', 'both']:
        rates(data, args.out)
    print(f'Rendered vector PDF and 600 dpi PNG: {args.figure}.')


if __name__ == '__main__':
    main()

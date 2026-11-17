#!/usr/bin/env python3
"""Render Figures 7 and 10 from the committed native-result snapshot.

PDFs are vector graphics; PNG previews use 600 dpi. No simulation is rerun.
Figure 7 pairs two compact overviews without x axes with a native down-input
zoom and an illustration of the minimum DQ window for a GPU read request.
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle, ConnectionPatch

BLUE, ORANGE = '#2a78d6', '#eb6834'
GREENS = ('#1baf7a', '#12734f')
INK, GRID, EPOCH = '#52514e', '#e6e5e1', '#deddd9'


def save(fig, out, name):
    fig.savefig(out / (name + '.pdf'), bbox_inches='tight', pad_inches=0.04)
    fig.savefig(out / (name + '.png'), dpi=600, bbox_inches='tight', pad_inches=0.04)
    plt.close(fig)


def timeline(data, out, detail):
    tick = data['clock_ps'] / 1e6
    fig = plt.figure(figsize=(7.2, 2.50))
    grid = fig.add_gridspec(2, 2, width_ratios=(1.65, 1), hspace=0.52, wspace=0.27)
    example = detail['zoom']
    selected_start = example['left']['end_ck']
    selected_end = example['right']['start_ck']
    assert selected_end-selected_start == example['gap_ck']
    assert example['gap_ck'] < detail['required_vlm_window_ck']['R']
    overview = []
    for index, case in enumerate(data['timeline_cases']):
        ax = fig.add_subplot(grid[index, 0])
        overview.append(ax)
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
                        ha='center', va='center', fontsize=6.1, color='white', zorder=4)
        ax.vlines([us(s) for s, e in case['pim_dq_bursts_ck']], -0.30, 0.30,
                  colors=INK, linewidth=0.22, zorder=3)
        if index == 0:
            middle = us((selected_start+selected_end)/2)
            # Overview locator only: native burst positions are preserved in the zoom.
            ax.add_patch(Rectangle((middle-5, -0.41), 10, 0.82, fill=False,
                                   edgecolor=ORANGE, linewidth=1.1, zorder=5))
            ax.annotate('Boxed down input', xy=(middle-5, 0.23),
                        xytext=(165, 0.48), fontsize=6.4, color=ORANGE,
                        arrowprops={'arrowstyle':'->', 'color':ORANGE, 'lw':0.8},
                        ha='left', va='center', zorder=6)
        else:
            ax.annotate('Bulk input load', xy=(6.3, 0.23),
                        xytext=(27, 0.50), fontsize=6.4, color=ORANGE,
                        arrowprops={'arrowstyle':'->', 'color':ORANGE, 'lw':0.8},
                        ha='left', va='center', zorder=6)
            start, end = us(case['io_epochs_ck'][0][1]), us(case['io_epochs_ck'][1][0])
            assert not any(s < case['io_epochs_ck'][1][0] and e > case['io_epochs_ck'][0][1]
                           for s, e in case['pim_dq_bursts_ck'])
            ax.annotate('', xy=(start+0.7, -0.02), xytext=(end-0.7, -0.02),
                        arrowprops={'arrowstyle':'<->', 'color':GREENS[1], 'lw':0.9}, zorder=5)
            ax.text(start, -0.41, f'VLM DQ window: {end-start:.1f} µs',
                    ha='left', va='center', fontsize=6.0, color=GREENS[1], zorder=5)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(['PIM DQ (ch 0)', 'PIM stages'], fontsize=6.6)
        ax.set_ylim(-0.57, 1.40)
        ax.set_xlim(0, us(case['hi_ck']))
        ax.set_xticks([])
        ax.spines['bottom'].set_visible(False)
        ax.grid(axis='y', visible=False)
        ax.set_title(case['title'], loc='left', pad=4)

    zoom = fig.add_subplot(grid[:, 1])
    origin = example['bursts'][0]['start_ck']
    length = example['bursts'][-1]['end_ck']-origin
    gap_start, gap_end = selected_start-origin, selected_end-origin
    guard_wr_rd = detail['cross_rank_dq_edges_ck']['WR']
    burst = detail['gpu_burst_ck']
    guard_rd_wr = detail['cross_rank_dq_edges_ck']['RW']
    required_end = gap_start+guard_wr_rd+burst+guard_rd_wr
    assert required_end-gap_end == 1
    zoom.axvspan(gap_start, gap_end, color='#fff0e5', zorder=0)
    for b in example['bursts']:
        zoom.add_patch(Rectangle((b['start_ck']-origin, 1.01), b['end_ck']-b['start_ck'],
                                 0.34, facecolor=INK, edgecolor='white', linewidth=0.4))
        zoom.text((b['start_ck']+b['end_ck'])/2-origin, 1.18, 'WR',
                  fontsize=5.0, color='white', ha='center', va='center')
    zoom.text(0, 1.48, 'PIM DQ: down input', fontsize=6.8, color=INK)
    zoom.annotate('', xy=(gap_start, 1.69), xytext=(gap_end, 1.69),
                  arrowprops={'arrowstyle':'<->', 'color':ORANGE, 'lw':0.9})
    zoom.text((gap_start+gap_end)/2, 1.81,
              f'{example["gap_ck"]} CK = {example["gap_ck"]*data["clock_ps"]/1000:.1f} ns',
              ha='center', fontsize=6.7, color=ORANGE)
    zoom.text(0, 0.64, 'GPU RD request: minimum window', fontsize=6.6, color=INK)
    segments = [(gap_start, guard_wr_rd, '#f5ca9d', '11'),
                (gap_start+guard_wr_rd, burst, GREENS[0], '2'),
                (gap_start+guard_wr_rd+burst, guard_rd_wr, '#f5ca9d', '2')]
    for start, duration, color, label in segments:
        zoom.add_patch(Rectangle((start, 0.06), duration, 0.33,
                                 facecolor=color, edgecolor='white', linewidth=0.4))
        zoom.text(start+duration/2, -0.07, label, ha='center', va='top', fontsize=6.0)
    zoom.text(gap_start+guard_wr_rd/2, 0.225, 'WR → RD', ha='center', va='center', fontsize=6.0)
    zoom.text(gap_start+guard_wr_rd+burst/2, 0.225, 'RD', ha='center', va='center', fontsize=5.0, color='white')
    zoom.add_patch(Rectangle((gap_start, 0.06), required_end-gap_start, 0.33,
                             fill=False, edgecolor=ORANGE, linestyle='--', linewidth=0.8))
    zoom.add_patch(Rectangle((gap_end, 0.06), required_end-gap_end, 0.33,
                             facecolor='#e34a33', edgecolor='#e34a33', hatch='///', alpha=0.65))
    zoom.axvline(gap_end, ymin=0.17, ymax=0.75, color=ORANGE, ls=':', lw=0.8)
    zoom.annotate('1 CK too long', xy=(required_end-0.5, 0.26),
                  xytext=(length, 0.86), ha='right', fontsize=6.2, color='#b33722',
                  arrowprops={'arrowstyle':'->', 'color':'#b33722', 'lw':0.8})
    zoom.text((gap_start+required_end)/2, -0.36, '11 + 2 + 2 = 15 CK > 14 CK',
              fontsize=6.5, ha='center', color='#b33722')
    zoom.set_xlim(-0.7, length+0.7)
    zoom.set_ylim(-0.56, 2.03)
    zoom.set_xticks([0, 8, 16, 24, 32])
    zoom.tick_params(axis='x', labelsize=6.0, length=2)
    zoom.set_xlabel('Relative time (CK)', fontsize=6.5, labelpad=2)
    zoom.set_yticks([])
    zoom.spines['left'].set_visible(False)
    zoom.grid(visible=False)
    zoom.set_title('Boxed input segment (enlarged)', loc='left', pad=4, fontsize=7.4)
    fig.add_artist(ConnectionPatch(
        xyA=(((selected_start+selected_end)/2-data['timeline_cases'][0]['lo_ck'])*tick+5, 0.23),
        xyB=(0, 0.69), coordsA=overview[0].transData, coordsB=zoom.transAxes,
        axesA=overview[0], axesB=zoom, color=ORANGE, lw=0.8,
        arrowstyle='->', shrinkA=2, shrinkB=2))
    fig.legend(handles=[Patch(facecolor=EPOCH, label='I/O epoch (DQ owned by PIM)')],
               loc='upper left', bbox_to_anchor=(0.12, 1.01), fontsize=6.6)
    fig.subplots_adjust(left=0.12, right=0.99, top=0.83, bottom=0.16)
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

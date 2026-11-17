#!/usr/bin/env python3
"""Render Figure 7 from the repository-contained native-data snapshots."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, ConnectionPatch

BLUE, ORANGE = '#2a78d6', '#eb6834'
GREENS = ('#1baf7a', '#12734f')
INK, GRID = '#52514e', '#e6e5e1'


def save(fig, out, name):
    fig.savefig(out / (name + '.pdf'), bbox_inches='tight', pad_inches=0.04)
    fig.savefig(out / (name + '.png'), dpi=600, bbox_inches='tight', pad_inches=0.04)
    plt.close(fig)


def timeline(data, out, detail):
    tick = data['clock_ps'] / 1e6
    fig = plt.figure(figsize=(7.2, 2.15))
    grid = fig.add_gridspec(2, 2, width_ratios=(1.85, 1), hspace=0.40, wspace=0.18)
    fig.subplots_adjust(left=0.08, right=0.99, top=0.88, bottom=0.08)
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
        ax.set_ylim(-0.45, 1.55)
        ax.set_xlim(0, us(case['hi_ck']))
        for e in case['events']:
            if e['kind'] != 'pim':
                continue
            lo, hi = us(e['start_ck']), us(e['end_ck'])
            ax.broken_barh([(lo, hi-lo)], (0.55, 0.90),
                           facecolor=BLUE, edgecolor='white', linewidth=0.5, zorder=3)
            if hi-lo > 14:
                label = e['name'].replace('_', '/')
                text = ax.text((lo+hi)/2, 1, label, ha='center', va='center',
                               fontsize=7.5, linespacing=0.95, color='white', zorder=4)
                renderer = fig.canvas.get_renderer()
                available = ax.transData.transform((hi, 0))[0]-ax.transData.transform((lo, 0))[0]
                if text.get_window_extent(renderer).width > available-1:
                    text.set_rotation(90)
        ax.vlines([us(s) for s, e in case['pim_dq_bursts_ck']], -0.225, 0.225,
                  colors=INK, linewidth=0.18, zorder=3)
        if index == 0:
            middle = us((selected_start+selected_end)/2)
            # Overview locator only: native burst positions are preserved in the zoom.
            ax.add_patch(Rectangle((middle-5, -0.31), 10, 0.62, fill=False,
                                   edgecolor=ORANGE, linewidth=0.9, zorder=5))
        ax.set_yticks([0, 1])
        ax.set_yticklabels(['PIM DQ', 'PIM stages'], fontsize=6.2)
        ax.set_xticks([])
        ax.spines['bottom'].set_visible(False)
        ax.grid(axis='y', visible=False)
        title = case['title'].replace(' (d)', '').replace(' (VLA-PIM, e)', '')
        ax.set_title(title, loc='left', pad=3, fontsize=6.8)

    zoom = fig.add_subplot(grid[:, 1])
    zoom.set_ylim(0, 1)
    # Derive lane centers/heights from the overview positions in figure space.
    # Native DQ aligns with (a)'s DQ; the request aligns with (b)'s PIM stages.
    def aligned_y(ax, y):
        return zoom.transAxes.inverted().transform(ax.transData.transform((0, y)))[1]
    dq_y, request_y = aligned_y(overview[0], 0), aligned_y(overview[1], 1)
    dq_height = aligned_y(overview[0], 0.225)-aligned_y(overview[0], -0.225)
    request_height = aligned_y(overview[1], 1.45)-aligned_y(overview[1], 0.55)
    dq_bottom, request_bottom = dq_y-dq_height/2, request_y-request_height/2
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
        zoom.add_patch(Rectangle((b['start_ck']-origin, dq_bottom), b['end_ck']-b['start_ck'],
                                 dq_height, facecolor=INK, edgecolor='white', linewidth=0.3))
    zoom.text(0, dq_y+dq_height/2+0.035, 'DQ (WR)', fontsize=6.3, color=INK)
    dimension_y = dq_y+dq_height/2+0.13
    zoom.annotate('', xy=(gap_start, dimension_y), xytext=(gap_end, dimension_y),
                  arrowprops={'arrowstyle':'<->', 'color':INK, 'lw':0.9})
    zoom.text((gap_start+gap_end)/2, dimension_y+0.045,
              f'{example["gap_ck"]} CK', ha='center', fontsize=6.3, color=INK)
    zoom.text(0, request_y+request_height/2+0.05, 'VLM Request', fontsize=6.3, color=INK)
    segments = [(gap_start, guard_wr_rd, '#f5ca9d'),
                (gap_start+guard_wr_rd, burst, GREENS[0]),
                (gap_start+guard_wr_rd+burst, guard_rd_wr, '#f5ca9d')]
    for start, duration, color in segments:
        zoom.add_patch(Rectangle((start, request_bottom), duration, request_height,
                                 facecolor=color, edgecolor='white', linewidth=0.4))
    zoom.add_patch(Rectangle((gap_start, request_bottom), required_end-gap_start, request_height,
                             fill=False, edgecolor=ORANGE, linestyle='--', linewidth=0.8))
    zoom.add_patch(Rectangle((gap_end, request_bottom), required_end-gap_end, request_height,
                             facecolor='#e34a33', edgecolor='#e34a33', hatch='///', alpha=0.65))
    zoom.vlines(gap_end, request_bottom-0.10, dq_y+dq_height/2,
                color=INK, ls=':', lw=0.8)
    zoom.annotate('2CK Data Burst',
                  xy=(gap_start+guard_wr_rd+burst/2, request_y+request_height/2),
                  xytext=(gap_start+2, request_y+0.20), ha='center', va='bottom',
                  fontsize=6.0, color=INK,
                  bbox={'facecolor':'white', 'edgecolor':'none', 'pad':0.6},
                  arrowprops={'arrowstyle':'->', 'color':INK, 'lw':0.8, 'linestyle':'--'})
    zoom.annotate('1CK too short for\nrank switching', xy=(required_end-0.5, request_y),
                  xytext=(length, request_y+0.20), ha='right', va='bottom', fontsize=6.0, color=INK,
                  bbox={'facecolor':'white', 'edgecolor':'none', 'pad':0.6},
                  arrowprops={'arrowstyle':'->', 'color':INK, 'lw':0.8, 'linestyle':'--'})
    zoom.text((gap_start+required_end)/2, request_bottom-0.035,
              '11 + 2 + 2\n= 15 CK > 14 CK', fontsize=6.0,
              ha='center', va='top', linespacing=1.15, color=INK)
    zoom.set_xlim(-0.7, length+0.7)
    zoom.set_xticks([])
    zoom.set_yticks([])
    zoom.spines['left'].set_visible(False)
    zoom.spines['bottom'].set_visible(False)
    zoom.grid(visible=False)
    zoom.set_title('Down input zoom', loc='left', pad=3, fontsize=6.8)
    fig.add_artist(ConnectionPatch(
        xyA=(((selected_start+selected_end)/2-data['timeline_cases'][0]['lo_ck'])*tick+5, 0),
        xyB=(-0.6, dq_y), coordsA=overview[0].transData, coordsB=zoom.transData,
        axesA=overview[0], axesB=zoom, color=INK, lw=0.9, linestyle=(0, (4, 3)),
        arrowstyle='-|>', mutation_scale=10, shrinkA=1, shrinkB=1))
    save(fig, out, 'fig7_step_timeline')


def main():
    bundle = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=bundle/'data/processed/timeline.json')
    parser.add_argument('--detail-data', type=Path, default=bundle/'data/processed/streaming-input-gap.json')
    parser.add_argument('--out', type=Path, default=bundle.parent)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({'font.size':7.5, 'axes.titlesize':8.2,
        'axes.labelsize':7.5, 'axes.spines.top':False, 'axes.spines.right':False,
        'axes.edgecolor':INK, 'xtick.color':INK, 'ytick.color':INK,
        'axes.grid':True, 'grid.color':GRID, 'grid.linewidth':0.6,
        'axes.axisbelow':True, 'legend.frameon':False,
        'pdf.fonttype':42, 'ps.fonttype':42})
    timeline(json.loads(args.data.read_text()), args.out,
             json.loads(args.detail_data.read_text()))
    print('Rendered Figure 7: vector PDF and 600 dpi PNG.')


if __name__ == '__main__':
    main()

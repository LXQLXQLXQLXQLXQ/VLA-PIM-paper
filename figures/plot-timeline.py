#!/usr/bin/env python3
"""Draw two normalized AE-layer timelines with nonpreemptive VLM kernels.

An active VLM kernel finishes before pending AE GPU work starts. Each panel
spans step 0, layer 0, independently normalized to the same drawing width.
Narrow kernel blocks are widened for labels; kernels 2 and 16 use the same
initial compression in both panels. Kernel 2 retains its further 35%
shortening; its following AE interval is drawn compactly with an external
orange label. QK^T keeps its enlarged width. All lanes share a monotone
transform; native CK timestamps stay intact.
"""
import argparse
import json
import shutil
from pathlib import Path

from figure_style import use_arial, export_tiff

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

BLUE = '#2a78d6'
GREEN_EDGE, GREEN_FILL = '#c6e6d5', '#12734f'
INK = '#52514e'
AE_FILL = '#eb6834'
KERNEL_WIDTH_FACTOR = 0.65
COMPRESSED_KERNELS = {2, 16}
QKT_WIDTH_FACTOR = 1.5
KERNEL2_FURTHER_FACTOR = 0.65
FIRST_AE_WIDTH_FACTOR = 0.2
STAGE_LABELS = {
    'qkv': 'QKV\nProjection',
    'qkt': r'$\mathrm{QK}^{\mathrm{T}}$',
    'pv': 'PV',
    'o': 'O\nProjection',
    'gate_up': 'FFN Gate/Up',
    'down': 'FFN Down',
}


def display_transform(case):
    """Normalize AE extent and reserve enough width to label every kernel.

    This adjusts the schematic display, not the native times. Minimum
    widths are 6 pt / 9.5 pt in the 418 pt plotting area. Other intervals
    share the remaining drawing width proportionally.
    """
    origin, finish = case['lo_ck'], case['hi_ck']
    boundaries = {origin, finish}
    minima, numbers = {}, {}
    for kernel in case['vlm_kernels']:
        start, end = kernel['start_ck'], kernel['end_ck']
        assert origin <= start < end <= finish
        boundaries.update((start, end))
        minima[(start, end)] = 0.0145 if kernel['number'] < 10 else 0.023
        numbers[(start, end)] = kernel['number']
    native = np.array(sorted(boundaries), dtype=float)
    lengths = np.diff(native) / (finish - origin)
    minimum = np.array([minima.get((a, b), 0.0)
                        for a, b in zip(native[:-1], native[1:])])
    low, high = 0.0, 1.0
    for _ in range(60):
        scale = (low + high) / 2
        if np.maximum(scale * lengths, minimum).sum() > 1:
            high = scale
        else:
            low = scale
    widths = np.maximum(low * lengths, minimum)
    compressed = np.array([numbers.get((a, b)) in COMPRESSED_KERNELS
                           for a, b in zip(native[:-1], native[1:])])
    previous = widths.copy()
    widths[compressed] *= KERNEL_WIDTH_FACTOR
    released = (previous[compressed] - widths[compressed]).sum()
    widths[~compressed] *= 1 + released / previous[~compressed].sum()
    assert np.allclose(widths[compressed], previous[compressed]*KERNEL_WIDTH_FACTOR)
    assert np.all(widths >= minimum)
    display = np.r_[0, np.cumsum(widths)]
    display[-1] = 1.0
    # Widen QK^T locally inside its containing VLM kernel. Redistribute
    # display width only within that kernel so every VLM block keeps its
    # existing width and both panels use exactly the same QK^T multiplier.
    stage = next(e for e in case['events'] if e['kind'] == 'pim' and e['name'] == 'qkt')
    container = next(k for k in case['vlm_kernels']
                     if k['start_ck'] <= stage['start_ck'] < stage['end_ck'] <= k['end_ck'])
    knots = np.unique(np.r_[native, stage['start_ck'], stage['end_ck']])
    positions = np.interp(knots, native, display)
    widths = np.diff(positions)
    in_stage = (knots[:-1] >= stage['start_ck']) & (knots[1:] <= stage['end_ck'])
    in_container = (knots[:-1] >= container['start_ck']) & (knots[1:] <= container['end_ck'])
    rest = in_container & ~in_stage
    stage_width, rest_width = widths[in_stage].sum(), widths[rest].sum()
    extra = stage_width * (QKT_WIDTH_FACTOR - 1)
    assert rest_width > extra
    widths[in_stage] *= QKT_WIDTH_FACTOR
    widths[rest] *= 1 - extra / rest_width
    native = knots
    display = np.r_[0, np.cumsum(widths)]
    display[-1] = 1.0
    # Move display width from kernel 2 into its following AE interval.
    # Prefer its post-QK^T waiting portion, retaining 10% of that portion;
    # take any remainder before QK^T so the enlarged QK^T block stays intact.
    kernel2 = next(k for k in case['vlm_kernels'] if k['number'] == 2)
    kernel3 = next(k for k in case['vlm_kernels'] if k['number'] == 3)
    in_kernel2 = ((native[:-1] >= kernel2['start_ck']) &
                  (native[1:] <= kernel2['end_ck']))
    after_qkt = in_kernel2 & (native[:-1] >= stage['end_ck'])
    before_qkt = in_kernel2 & (native[1:] <= stage['start_ck'])
    ae_gap = ((native[:-1] >= kernel2['end_ck']) &
              (native[1:] <= kernel3['start_ck']))
    original_kernel2_width = widths[in_kernel2].sum()
    transferred = original_kernel2_width * (1 - KERNEL2_FURTHER_FACTOR)
    post_width = widths[after_qkt].sum()
    post_transfer = min(transferred, post_width * 0.9)
    widths[after_qkt] *= 1 - post_transfer / post_width
    remaining = transferred - post_transfer
    pre_width = widths[before_qkt].sum()
    assert pre_width > remaining
    widths[before_qkt] *= 1 - remaining / pre_width
    widths[ae_gap] *= 1 + transferred / widths[ae_gap].sum()
    assert np.isclose(widths[in_kernel2].sum(),
                      original_kernel2_width * KERNEL2_FURTHER_FACTOR)
    # Compact the first AE block without restoring the longer kernel 2.
    # Spread the released width over the other VLM blocks, retaining the
    # requested kernel-2/kernel-16 widths and the enlarged QK^T width.
    released = widths[ae_gap].sum() * (1 - FIRST_AE_WIDTH_FACTOR)
    widths[ae_gap] *= FIRST_AE_WIDTH_FACTOR
    receivers = np.zeros(len(widths), dtype=bool)
    for kernel in case['vlm_kernels']:
        if kernel['number'] in COMPRESSED_KERNELS:
            continue
        receivers |= ((native[:-1] >= kernel['start_ck']) &
                      (native[1:] <= kernel['end_ck']))
    widths[receivers] *= 1 + released / widths[receivers].sum()
    display = np.r_[0, np.cumsum(widths)]
    display[-1] = 1.0
    assert np.all(np.diff(display) > 0)
    return lambda ck: np.interp(ck, native, display)


def ae_gpu_intervals(case):
    """Merge adjacent native AE GPU operators into contiguous orange blocks."""
    intervals = []
    for event in case['events']:
        if event['kind'] != 'gpu':
            continue
        start, end = event['start_ck'], event['end_ck']
        if intervals and intervals[-1][1] == start:
            intervals[-1] = (intervals[-1][0], end)
        else:
            intervals.append((start, end))
    return intervals


def validate_case(case):
    kernels = case['vlm_kernels']
    assert [k['number'] for k in kernels] == list(range(1, len(kernels) + 1))
    assert len(kernels) == case['completed_vlm_kernels']
    assert all(a['end_ck'] <= b['start_ck']
               for a, b in zip(kernels, kernels[1:]))
    gpu = [e for e in case['events'] if e['kind'] == 'gpu']
    for kernel in kernels:
        assert kernel['end_ck'] <= case['hi_ck']
        assert not kernel.get('paused_us', 0)
        assert all(min(kernel['end_ck'], e['end_ck']) <=
                   max(kernel['start_ck'], e['start_ck']) for e in gpu)
    for previous, event in zip(case['events'], case['events'][1:]):
        if event['kind'] == 'gpu' and event['start_ck'] > previous['end_ck']:
            assert any(k['end_ck'] == event['start_ck'] for k in kernels)


def timeline(data):
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 3.15))
    fig.subplots_adjust(left=0.175, right=0.985, top=0.865, bottom=0.035, hspace=0.48)
    for ax, case in zip(axes, data['timeline_cases']):
        validate_case(case)
        x = display_transform(case)
        for event in case['events']:
            if event['kind'] != 'pim':
                continue
            start, end = x(event['start_ck']), x(event['end_ck'])
            ax.add_patch(Rectangle((start, 1.71), end-start, 0.58,
                                   facecolor=BLUE, edgecolor='white', lw=0.5, zorder=3))
            if event['name'] in STAGE_LABELS:
                label = STAGE_LABELS[event['name']]
                ax.text((start+end)/2, 2, label,
                        ha='center', va='center',
                        fontsize=7.2 if '\n' in label else 8,
                        linespacing=0.9, color='white', zorder=4)
        ax.vlines([x(start) for start, end in case['pim_dq_bursts_ck']],
                  0.71, 1.29, colors=INK, linewidth=0.06, zorder=3)
        kernel2 = next(k for k in case['vlm_kernels'] if k['number'] == 2)
        for start_ck, end_ck in ae_gpu_intervals(case):
            start, end = x(start_ck), x(end_ck)
            ax.add_patch(Rectangle((start, -0.29), end-start, 0.58,
                                   facecolor=AE_FILL, edgecolor='white',
                                   lw=0.7, zorder=4))
            if start_ck == kernel2['end_ck']:
                ax.text((start+end)/2, 1.5, 'AE Non-Linear',
                        ha='center', va='center', fontsize=7,
                        color=AE_FILL, zorder=5)
        for kernel in case['vlm_kernels']:
            start, end = x(kernel['start_ck']), x(kernel['end_ck'])
            ax.add_patch(Rectangle((start, -0.29), end-start, 0.58,
                                   facecolor=GREEN_FILL, edgecolor=GREEN_EDGE,
                                   lw=0.7, zorder=4, joinstyle='miter'))
            ax.text((start+end)/2, 0, str(kernel['number']), ha='center',
                    va='center', fontsize=6.7, color='white', zorder=5)
        ax.set(xlim=(0, 1), ylim=(-0.44, 2.45), xticks=[], xlabel='')
        ax.set_yticks([0, 1, 2])
        ax.set_yticklabels(['GPU Kernels', 'PIM DQ bursts', 'PIM stages'], fontsize=7.5)
        ax.tick_params(axis='y', length=3, width=0.7, pad=5)
        ax.spines['bottom'].set_visible(False)
        ax.spines['left'].set_linewidth(0.75)
        ax.grid(False)
        ax.set_title(case['title'], loc='left', fontsize=8.3, pad=6)
        ax.set_title(f"{case['completed_vlm_kernels']} VLM kernels completed",
                     loc='right', fontsize=7.6, color=GREEN_FILL, pad=6)
    assert len(fig.axes) == 2
    assert all(not ax.get_xticks().size and not ax.get_xlabel() and
               not ax.spines['bottom'].get_visible() for ax in axes)
    assert axes[0].get_position().x0 == axes[1].get_position().x0
    assert axes[0].get_position().x1 == axes[1].get_position().x1
    return fig


def save(fig, out):
    options = dict(bbox_inches='tight', pad_inches=0.04, facecolor='white')
    fig.savefig(out/'fig7_step_timeline.pdf', **options)
    fig.savefig(out/'fig7_step_timeline.svg', **options)
    fig.savefig(out/'fig7_step_timeline.png', dpi=600, **options)
    shutil.copyfile(out/'fig7_step_timeline.png', out/'fig6_timeline.png')
    export_tiff(out/'fig6_timeline.png', out/'fig6_timeline.tif')
    plt.close(fig)


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=here/'data/timeline-vlm-priority.json')
    parser.add_argument('--out', type=Path, default=here)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    use_arial()
    plt.rcParams.update({'font.size':7.5, 'axes.spines.top':False,
        'axes.spines.right':False, 'axes.edgecolor':INK, 'ytick.color':INK,
        'legend.frameon':False, 'pdf.fonttype':42, 'ps.fonttype':42,
        'svg.fonttype':'none'})
    data = json.loads(args.data.read_text())
    save(timeline(data), args.out)
    print('Rendered Figure 6: two panels, numbered kernels, no horizontal axes.')


if __name__ == '__main__':
    main()

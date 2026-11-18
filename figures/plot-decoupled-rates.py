#!/usr/bin/env python3
"""Plot AE action-chunk and VLM KV-refresh rates under decoupled execution (Fig. 8)."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

AE, VLM = '#eb6834', '#1baf7a'


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=here / 'data/decoupled-rates.json')
    parser.add_argument('--out', type=Path, default=here)
    args = parser.parse_args()
    configs = json.loads(args.data.read_text())['configurations']
    plt.rcParams.update({
        'font.size': 8, 'axes.spines.top': False, 'axes.spines.right': False,
        'axes.edgecolor': '#52514e', 'xtick.color': '#52514e', 'ytick.color': '#52514e',
        'axes.labelcolor': 'black', 'axes.axisbelow': True,
        'pdf.fonttype': 42, 'ps.fonttype': 42,
    })
    fig, ax = plt.subplots(figsize=(3.476, 2.549))
    w, gap = 0.33, 0.03
    xs = range(len(configs))
    for i, c in zip(xs, configs):
        for dx, val, color in ((-(w + gap) / 2, c['ae_hz'], AE), ((w + gap) / 2, c['vlm_hz'], VLM)):
            ax.bar(i + dx, val, w, color=color)
            ax.text(i + dx, val + 0.25, f'{val:.2f}', ha='center', va='bottom', fontsize=7)
    ax.set_xticks(list(xs), [c['label'] for c in configs], fontsize=7)
    ax.set_ylabel('Frequency (Hz)')
    ax.set_ylim(0, 20)
    ax.set_yticks([0, 5, 10, 15, 20])
    ax.yaxis.grid(True, color='#e5e5e5', lw=0.8)
    ax.bar(0, 0, color=AE, label='AE action chunks')
    ax.bar(0, 0, color=VLM, label='VLM KV refreshes')
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, 1.2), ncol=2, frameon=False, fontsize=7.5)
    fig.tight_layout(pad=0.3)
    for ext in ('pdf', 'png'):
        fig.savefig(args.out / f'fig_decoupled_rate.{ext}', dpi=600 if ext == 'png' else None)


if __name__ == '__main__':
    main()

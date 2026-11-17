#!/usr/bin/env python3
"""Regenerate the DQ interval figure from the committed statistics snapshot.

Run from any directory with Python and matplotlib. Output: PDF and PNG next
to this script. Bin lengths are descriptive, not GPU-admission thresholds.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
BINS = ["1-4", "5-8", "9-14", "15-32", "33-64", "65-256", "257-1024", ">1024"]
plt.rcParams.update({
    "font.size": 8, "axes.titlesize": 8.5, "axes.labelsize": 8,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": "#52514e", "axes.labelcolor": "#0b0b0b",
    "xtick.color": "#52514e", "ytick.color": "#52514e",
    "axes.grid": True, "grid.color": "#e6e5e1", "grid.linewidth": 0.6,
    "axes.axisbelow": True, "legend.frameon": False,
    "legend.fontsize": 7.5, "pdf.fonttype": 42, "ps.fonttype": 42,
})

data = json.loads((ROOT / "data/dq-gap-distribution.json").read_text())
fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.4))
width = 0.38
for i, (case, label, color) in enumerate([
    ("combined-e", "Streaming input (e)", "#2a78d6"),
    ("combined-g", "Input preloading (VLA-PIM, g)", "#eb6834"),
]):
    bins = {row["length_bin_ck"]: row for row in data["bins"][case]}
    count = sum(row["count"] for row in bins.values())
    cycles = sum(row["cycles"] for row in bins.values())
    fractions = [100 * bins[key]["count"] / count for key in BINS]
    time = [100 * bins[key]["cycles"] / cycles for key in BINS]
    epochs = [100 * bins[key]["io_epoch_overlap_ck"] / cycles for key in BINS]
    positions = [j + (i - 0.5) * width for j in range(len(BINS))]
    axes[0].bar(positions, fractions, width * 0.92, color=color, label=label)
    outside = [total - epoch for total, epoch in zip(time, epochs)]
    axes[1].bar(positions, outside, width * 0.92, color=color, label=label)
    if any(epochs):
        axes[1].bar(positions, epochs, width * 0.92, bottom=outside,
                    color="white", edgecolor=color, hatch="////", linewidth=0.6,
                    label="VLA-PIM: inside I/O epoch (GPU barred)")

for ax in axes:
    ax.set_xticks(range(len(BINS)))
    ax.set_xticklabels(BINS, rotation=30, ha="right")
    ax.set_xlabel("PIM-burst / stage-boundary interval (CK)")
    ax.grid(axis="x", visible=False)
    ax.set_ylim(0, 108)
axes[0].set_ylabel("Share of intervals (%)")
axes[1].set_ylabel("Share of interval time (%)")
axes[0].set_title("(a) By count", loc="left")
axes[1].set_title("(b) By time", loc="left")
axes[1].legend(loc="upper left")
fig.tight_layout()
for extension in ["pdf", "png"]:
    fig.savefig(ROOT / f"fig_dq_gap_distribution.{extension}",
                bbox_inches="tight", dpi=300)
plt.close(fig)

#!/usr/bin/env python3
"""Render Fig. 5 in Arial, matching Fig. 1's single-column text scale.

Run: python3 figures/plot-layout-dq.py [--out OUTPUT_DIRECTORY]
No simulator, external paths or new experiment is needed. Cache files use scratch.
"""
import argparse
import json
import os
from pathlib import Path
from figure_style import use_arial, export_tiff

os.environ.setdefault("MPLCONFIGDIR", "/scratch/xinyaowang/dq-traffic-matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/scratch/xinyaowang/dq-traffic-cache")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

HERE = Path(__file__).resolve().parent
BANKS = 16

INK, MUTED, GREEN = "#303030", "#52514e", "#1baf7a"
# Fig. 1 uses approximately 7 pt at 3.5-inch column width.
TITLE_SIZE, LABEL_SIZE = 7, 7
BAR_VALUE_SIZE = 6

COLORS = {
    "qkv_input": "#C6D9E4", "rope": "#DBC5A3", "q_exchange": "#eb6834",
    "scores": "#3272b1", "probabilities": "#1baf7a", "context": "#a8adb4",
    "pv_o_handoff": "#AFB2C0", "o_output": "#9DA9C4", "ffn": "#DEE3E6",
}

NAMES = {
    "qkv_input": "QKV input", "rope": "GPU RoPE Q/K round trip",
    "q_exchange": "Q exchange", "scores": "Scores", "probabilities": "Probabilities",
    "context": "Context", "pv_o_handoff": "PV / O handoff", "o_output": "O output",
    "ffn": "FFN input + output",
}

CORE = ("q_exchange", "scores", "probabilities", "context")

def save(fig, output, name):
    for suffix in ("pdf", "svg", "png"):
        fig.savefig(output / f"{name}.{suffix}", dpi=600, facecolor="white")
    svg = output / f"{name}.svg"
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
    export_tiff(output / f"{name}.png", output / f"{name}.tif")
    plt.close(fig)

def traffic_panel(fig, data):
    """Draw the same compact 76-point traffic panel in either figure."""
    figure_width, figure_height = fig.get_size_inches() * 72
    ax = fig.add_axes([9 / figure_width, 0, 234 / figure_width, 76 / figure_height])
    totals = {case: sum(data[case]["components_bytes"][key] for key in CORE) / 1024
              for case in ("c", "d")}
    ax.set_xlim(0, totals["c"])
    ax.set_ylim(0, 76)
    ax.set_axis_off()
    ax.text(0, 74, "(b) External DQ traffic (Attention)", fontsize=TITLE_SIZE,
            fontweight="bold", color="black", va="top")

    for case, y, label in (("c", 45, "Feature-wise"), ("d", 18, "Token-wise")):
        start = 0
        for key in CORE:
            width = data[case]["components_bytes"][key] / 1024
            if not width:
                continue
            ax.barh(y, width, left=start, height=9.5, color=COLORS[key],
                    edgecolor="white", linewidth=0.35)
            ax.text(start + width / 2, y, f"{width:,.0f}", ha="center", va="center",
                    fontsize=BAR_VALUE_SIZE, color="white" if key == "scores" else INK)
            start += width
        ax.text(0, y + 11, label, ha="left", va="center", fontsize=LABEL_SIZE,
                color=INK)
        ax.text(totals[case], y + 11, f"{totals[case]:,.0f} KiB", ha="right", va="center",
                fontsize=LABEL_SIZE, color=INK)

    difference = totals["c"] - totals["d"]
    ax.text(totals["c"], 18, f"−{difference:,.0f} KiB",
            ha="right", va="center", fontsize=LABEL_SIZE, color=GREEN)
    fig.legend(handles=[Patch(facecolor=COLORS[key], label=NAMES[key]) for key in CORE],
               loc="lower left", bbox_to_anchor=(9 / figure_width, 2 / figure_height,
                                                 234 / figure_width, 8 / figure_height), mode="expand",
               ncol=4, borderaxespad=0, borderpad=0, frameon=False, fontsize=LABEL_SIZE,
               handlelength=0.85, handletextpad=0.35, columnspacing=0.7)

def partition_schematic(ax, *, feature):
    """Logical PIM-rank pair; feature lanes / token parity grouped for display."""
    from matplotlib.patches import Rectangle

    x, y, width, height = (21 if feature else 153), 91, 90, 27
    center = x + width / 2
    blue, aqua, edge, bank_edge = "#D7E7EF", "#D6E6DF", MUTED, "#b8c0c4"
    bank_label = r"$\mathrm{B}_{0}\;\ldots\;\mathrm{B}_{15}$"
    # Show representative bank boundaries; the intervening banks are omitted.
    bank_boundaries = range(4, BANKS, 4)
    ax.text(center, 135, "Feature-wise" if feature else "Token-wise", ha="center",
            va="center", fontsize=TITLE_SIZE, color="black")

    if feature:
        for rank, color in enumerate((blue, aqua)):
            left = x + rank * width / 2
            ax.add_patch(Rectangle((left, y), width / 2, height, facecolor=color, edgecolor="none"))
            ax.text(left + width / 4, 125, "Rank A" if rank == 0 else "Rank B",
                    ha="center", va="center", fontsize=LABEL_SIZE, color=INK)
            for bank in bank_boundaries:
                bx = left + width / 2 * bank / BANKS
                ax.plot([bx, bx], [y, y + height], color=bank_edge, linewidth=0.3,
                        linestyle=(0, (1.4, 1.4)))
            ax.text(left + width / 4, 84, bank_label, ha="center", va="center",
                    fontsize=LABEL_SIZE, color=MUTED)
        ax.plot([center, center], [y, y + height], color=MUTED, linewidth=0.8)
    else:
        ax.add_patch(Rectangle((x, y + height / 2), width, height / 2,
                               facecolor=blue, edgecolor="none"))
        ax.add_patch(Rectangle((x, y), width, height / 2, facecolor=aqua, edgecolor="none"))
        for fraction, label in ((0.75, "Rank A"), (0.25, "Rank B")):
            ax.text(x - 5, y + height * fraction, label, ha="right", va="center",
                    fontsize=LABEL_SIZE, color=INK)
        for bank in bank_boundaries:
            bx = x + width * bank / BANKS
            ax.plot([bx, bx], [y, y + height], color=bank_edge, linewidth=0.3,
                    linestyle=(0, (1.4, 1.4)))
        ax.plot([x, x + width], [y + height / 2] * 2, color=MUTED, linewidth=0.8)
        ax.text(center, 84, bank_label, ha="center", va="center", fontsize=LABEL_SIZE,
                color=MUTED)
    ax.add_patch(Rectangle((x, y), width, height, facecolor="none", edgecolor=edge, linewidth=0.6))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    data = json.loads((HERE / "data/layout-dq-20261117.json").read_text())["cases"]
    use_arial()
    plt.rcParams.update({"font.size": TITLE_SIZE, "font.weight": "normal",
                         "pdf.fonttype": 42, "ps.fonttype": 42,
                         "svg.fonttype": "none", "text.color": INK})
    fig = plt.figure(figsize=(3.5, 2.15))
    layout = fig.add_axes([0, 0, 1, 1])
    layout.set(xlim=(0, 252), ylim=(0, 2.15 * 72))
    layout.set_axis_off()
    layout.text(9, 151, "(a) KV features partitioning", fontsize=TITLE_SIZE,
                fontweight="bold", color="black", va="top")
    partition_schematic(layout, feature=True)
    partition_schematic(layout, feature=False)
    traffic_panel(fig, data)
    save(fig, args.out, "fig_layout_dq")
    print(f"Saved layout/DQ figure to {args.out}")


if __name__ == "__main__":
    main()

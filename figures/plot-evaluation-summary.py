#!/usr/bin/env python3
"""Render the one-row evaluation summary at the manuscript's text width.

The LaTeX caption and figure wrapper are in evaluation-summary.tex.
"""

import argparse
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from figure_style import use_arial

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


HERE = Path(__file__).resolve().parent
# IEEEtran's 516 TeX points of text width, converted to PDF points.
FIGURE_WIDTH = 516 * 72 / 72.27
FIGURE_HEIGHT = 108  # PDF points, including ticks and headings
PLOT_BOTTOM, PLOT_TOP = 13, 96
HEADING_OFFSET = 4.5  # points above the top of the plot
BAR_WIDTH = 12.5
WITHIN_GROUP_GAP = 3.5
BETWEEN_GROUP_GAP = 12
INK = "#303030"
AXIS = "#52514e"
SPEEDUP = "#a54823"
PI05 = r"$\pi_{0.5}$"
CYCLE_COLORS = ("#a8adb4", "#808892", "#78a8da", "#4a8dce", "#3272b1", "#eb6834")
RATE_COLORS = ("#398C83", "#E7BA42")
ENERGY_COLORS = (CYCLE_COLORS[0], CYCLE_COLORS[-1])


def load_data(filename):
    return json.loads((HERE / "data" / filename).read_text())


def one_decimal(value):
    return str(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def panel(figure, left, width, letter, ylabel, tick_step, *, y_start=0):
    # Use real PDF points for the horizontal data scale in every panel.
    ax = figure.add_axes([left / FIGURE_WIDTH, PLOT_BOTTOM / FIGURE_HEIGHT,
                          width / FIGURE_WIDTH, (PLOT_TOP - PLOT_BOTTOM) / FIGURE_HEIGHT])
    ax.annotate(letter, (0, 1), xycoords="axes fraction", xytext=(-3, HEADING_OFFSET),
                textcoords="offset points", weight="bold", ha="right", va="center")
    # Four equal intervals in each panel keep the horizontal guides aligned
    # even though the three axes use different units.
    ax.set(xlim=(0, width), ylim=(y_start, y_start + 4.16 * tick_step),
           yticks=[y_start + i * tick_step for i in range(5)])
    ax.set_ylabel(ylabel, labelpad=2.0, color=INK)
    ax.tick_params(axis="x", length=2.5, width=0.65, pad=3)
    ax.tick_params(axis="y", length=2, pad=2)
    ax.yaxis.grid(True, color="#dbdddf", linewidth=0.5, linestyle=(0, (2.5, 2)))
    return ax


def bar_positions(ax, group_count, bars_per_group):
    pitch = BAR_WIDTH + WITHIN_GROUP_GAP
    group_width = BAR_WIDTH + (bars_per_group - 1) * pitch
    total_width = group_count * group_width + (group_count - 1) * BETWEEN_GROUP_GAP
    left, right = ax.get_xlim()
    first = (left + right - total_width + BAR_WIDTH) / 2
    return [[first + group * (group_width + BETWEEN_GROUP_GAP) + i * pitch
             for i in range(bars_per_group)] for group in range(group_count)]


def model_heading(ax, xs, model_name):
    ax.annotate(model_name, ((xs[0] + xs[-1]) / 2, 1), xycoords=ax.get_xaxis_transform(),
                xytext=(0, HEADING_OFFSET), textcoords="offset points", ha="center", va="center")


def comparison_arrow(ax, xs, baseline, final, *, decimals=2, label_dy=0, label_gap=1.5):
    left, right = xs[0] - BAR_WIDTH / 2, xs[-1] + BAR_WIDTH / 2
    ax.hlines(baseline, left, right, colors=SPEEDUP, linestyles=(0, (3, 2)),
              linewidth=0.75, zorder=4)
    ax.annotate("", xy=(right, final), xytext=(right, baseline), zorder=5,
                arrowprops=dict(arrowstyle="-|>", color=SPEEDUP, lw=0.8,
                                mutation_scale=7, shrinkA=0, shrinkB=0))
    ax.annotate(f"{baseline / final:.{decimals}f}×", (right, (baseline + final) / 2 + label_dy),
                xytext=(-label_gap, 0), textcoords="offset points", ha="right", va="center",
                color=SPEEDUP, zorder=6)


def inference_cycle(figure, models):
    ax = panel(figure, 27, 202, "(a)", "Async. cycle (ms)", 25, y_start=50)
    labels = ["a-s", "a-d", "b", "c", "d", "e"]
    ticks = []
    groups = bar_positions(ax, len(models), len(labels))
    for xs, model_name, model in zip(groups, (PI05, "GR00T N1.6"), models, strict=True):
        configurations = model["configurations"]
        values = [item.get("plot_ms", item["cycle_ms"]) for item in configurations]
        ax.bar(xs, values, width=BAR_WIDTH, color=CYCLE_COLORS, zorder=3)
        comparison_arrow(ax, xs, values[0], values[-1], label_dy=5)
        for x, value in zip(xs, values, strict=True):
            # Keep nearby values above the serial reference, leaving its dashes intact.
            y = max(value, values[0]) if abs(value - values[0]) < 8 else value
            ax.annotate(f"{value:.0f}", (x, y), xytext=(0, 1.8),
                        textcoords="offset points", ha="center", va="bottom")
        model_heading(ax, xs, model_name)
        ticks.extend(xs)
    ax.set(xticks=ticks, xticklabels=labels * 2)


def color_key(ax, colors, labels):
    handles = [Patch(facecolor=color, label=label) for color, label in zip(colors, labels, strict=True)]
    heading_y = 1 + HEADING_OFFSET / (PLOT_TOP - PLOT_BOTTOM)
    ax.legend(handles=handles, loc="center", bbox_to_anchor=(0.5, heading_y),
              ncols=2, frameon=False, borderaxespad=0, handlelength=1.0,
              handletextpad=0.4, columnspacing=0.85)


def chunk_energy(figure, models):
    ax = panel(figure, 257, 73, "(b)", "Energy Consumption (J)", 4)
    groups = bar_positions(ax, len(models), 2)
    for xs, model_name, model in zip(groups, (PI05, "GR00T N1.6"), models, strict=True):
        gpu, pim = model["baseline_energy_J"], model["estimated_g_energy_J"]
        bars = ax.bar(xs, [gpu, pim], width=BAR_WIDTH, color=ENERGY_COLORS, zorder=3)
        ax.bar_label(bars, labels=[one_decimal(gpu), one_decimal(pim)], padding=2)
        comparison_arrow(ax, xs, gpu, pim, decimals=1, label_dy=0.35, label_gap=0.9)
        model_heading(ax, xs, model_name)
    ax.set(xticks=[x for group in groups for x in group], xticklabels=["a-s", "e"] * len(models))


def decoupled_rates(figure, configs):
    ax = panel(figure, 357, 155, "(c)", "Decoupled rates (Hz)", 5)
    groups = bar_positions(ax, len(configs), 2)
    for xs, config in zip(groups, configs, strict=True):
        values = [config["ae_hz"], config["vlm_hz"]]
        bars = ax.bar(xs, values, width=BAR_WIDTH, color=RATE_COLORS, zorder=3)
        ax.bar_label(bars, labels=[one_decimal(v) for v in values], padding=2)
    ax.set(xticks=[sum(xs) / 2 for xs in groups],
           xticklabels=["a-d", "Thor × 2", "d", "e"])
    color_key(ax, RATE_COLORS, ("AE", "VLM"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE.parent.parent / "output" / "pdf")
    args = parser.parse_args()
    use_arial()
    plt.rcParams.update({
        "font.size": 7, "text.color": INK, "axes.edgecolor": AXIS, "axes.linewidth": 0.65,
        "xtick.color": AXIS, "ytick.color": AXIS, "axes.axisbelow": True,
        "axes.spines.top": False, "axes.spines.right": False,
    })
    figure = plt.figure(figsize=(FIGURE_WIDTH / 72, FIGURE_HEIGHT / 72), facecolor="white")
    inference_cycle(figure, load_data("async-vla-performance.json")["models"])
    chunk_energy(figure, load_data("power-energy-comparison.json")["models"])
    decoupled_rates(figure, load_data("decoupled-rates.json")["configurations"])
    args.out.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.out / "evaluation-summary.pdf")
    figure.savefig(args.out / "evaluation-summary.png", dpi=600)
    plt.close(figure)


if __name__ == "__main__":
    main()

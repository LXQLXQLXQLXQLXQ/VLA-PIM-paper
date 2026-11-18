"""Shared Arial typography and lossless bitmap exports for Figures 5--8.

Install Arial on the host, or set VLA_PIM_FONT_DIR to a directory containing
the Arial regular, italic, bold and bold-italic TrueType fonts before plotting.
Font files are external dependencies and are not bundled with the paper.
"""
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/scratch/xinyaowang/vla-paper-matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/scratch/xinyaowang/vla-paper-cache")

import matplotlib
from matplotlib import font_manager
from PIL import Image


def use_arial():
    font_dir = os.environ.get("VLA_PIM_FONT_DIR")
    if font_dir:
        for path in sorted(Path(font_dir).iterdir()):
            if path.suffix.lower() in (".ttf", ".otf"):
                font_manager.fontManager.addfont(str(path))
    try:
        for style, weight in (("normal", "normal"), ("italic", "normal"),
                              ("normal", "bold"), ("italic", "bold")):
            properties = font_manager.FontProperties(family="Arial", style=style, weight=weight)
            path = font_manager.findfont(properties, fallback_to_default=False)
            if font_manager.FontProperties(fname=path).get_name() != "Arial":
                raise ValueError("The resolved font is not Arial")
    except ValueError as exc:
        raise RuntimeError("Install Arial or set VLA_PIM_FONT_DIR to its font directory.") from exc
    matplotlib.rcParams.update({
        "font.family": "Arial", "font.sans-serif": ["Arial"],
        "mathtext.fontset": "custom", "mathtext.rm": "Arial",
        "mathtext.it": "Arial:italic", "mathtext.bf": "Arial:bold",
        "mathtext.bfit": "Arial:bold:italic", "mathtext.sf": "Arial",
        "mathtext.tt": "Arial", "mathtext.cal": "Arial",
        "mathtext.fallback": None, "pdf.fonttype": 42, "ps.fonttype": 42,
    })


def export_tiff(png_path, tiff_path):
    with Image.open(png_path) as png:
        png.convert("RGB").save(tiff_path, compression="tiff_lzw", dpi=(600, 600))

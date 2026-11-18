#!/usr/bin/env python3
"""Export Fig. 2 directly from its native vector master as a lossless PNG.

Requires pypdfium2 and Pillow. No bitmap is upscaled or sharpened.
"""
from pathlib import Path
import argparse
import pypdfium2 as pdfium

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--dpi", type=int, default=1200)
args = parser.parse_args()
if args.dpi <= 0:
    parser.error("dpi must be positive")
root = Path(__file__).resolve().parent
source = root / "sources/vla-characterization-v17.pdf"
output = root / "vla-characterization.png"
with pdfium.PdfDocument(str(source)) as document:
    if len(document) != 1:
        raise ValueError("The native master must contain exactly one figure page")
    page = document[0]
    bitmap = page.render(scale=args.dpi / 72)
    image = bitmap.to_pil().convert("RGB")
    image.save(output, format="PNG", dpi=(args.dpi, args.dpi), optimize=True)
    print(f"{output.name}: {image.width} x {image.height} pixels at {args.dpi} dpi")

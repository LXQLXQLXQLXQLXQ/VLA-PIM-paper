#!/usr/bin/env python3
"""Compatibility entry point; canonical audit lives in figures/fig7/scripts."""
from pathlib import Path
from runpy import run_path
import sys

if __name__ == '__main__':
    here = Path(__file__).resolve().parent
    if not any(a == '--experiment' or a.startswith('--experiment=') for a in sys.argv):
        sys.argv += ['--experiment', str(here.parent.parent/'experiments/2026-11-16')]
    if not any(a == '--out' or a.startswith('--out=') for a in sys.argv):
        sys.argv += ['--out', str(here/'data/streaming-input-gap-20261117.json')]
    run_path(str(here/'fig7/scripts/analyze_gaps.py'), run_name='__main__')

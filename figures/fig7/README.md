# Figure 7: plotting scripts and original data

This directory contains the complete data bundle for the double-column timeline
figure. All commands below run from the repository root. No simulator, network
access, or files outside the clone are needed to rebuild the plotted inputs.

## Files

| Directory | Contents |
| --- | --- |
| `scripts/` | Canonical plotting script, native-gap audit, raw-data preparation, and plotting dependencies |
| `data/raw/` | Two lossless archives containing the original experiment outputs, the command-pair timing matrix, and SHA-256 manifest |
| `data/processed/` | Small JSON inputs regenerated from those original records |
| `../fig7_step_timeline.pdf`, `../fig7_step_timeline.png` | Published vector figure and 600 dpi preview used by `../timeline.tex` |

### Original data

| Panel | Archive | Original experiment ID |
| --- | --- | --- |
| (a) Streaming input | `data/raw/streaming-input.tar.gz` | `combined-e`, repeat 1 |
| (b) Input preloading | `data/raw/input-preloading.tar.gz` | `combined-g`, repeat 1 |

Each archive retains all nine files from the original run: `raw.json`,
`dq-timeline.json`, `dq-bursts.csv`, `dq-epochs.csv`, `bus-diagnostics.json`,
`ca-commands.csv`, `config.json`, `native.log`, and `verification.json`.
These cover the complete 18-layer, 10-step run; they are not cropped to the
displayed layer. DQ tracing records physical channel 0. Some trace files contain
only a header, as in the original output. File contents are unchanged; compression
is lossless. The archives preserve the original `results/<case>/repeat-1/` paths.

`data/raw/manifest.json` records archive and original-file sizes and SHA-256
checksums. Original file hashes are also checked against each run's native
`verification.json`. `command-pair-matrix.json` supplies the different-rank
timing guards used for the 14-CK gap explanation. Original configurations retain
their recorded machine paths as provenance; the commands below do not use them.
The bundle-level `verification.json` records the independent reconstruction,
runtime versions, and matching PNG checksum.

## Reproduce the figure

Plotting was validated with Python 3.9.21, Matplotlib 3.4.3, NumPy 1.20.1,
and Pillow 10.0.1. The corresponding pins are in `scripts/requirements.txt`.
The raw-data preparation and audit use only Python's standard library.

To redraw directly from the committed processed inputs:

```sh
MPLCONFIGDIR=/scratch/fig7-matplotlib \
python3 figures/fig7/scripts/plot_figure.py
```

This writes `figures/fig7_step_timeline.pdf` and `figures/fig7_step_timeline.png`.
Use `--out /scratch/fig7-preview` to write a separate preview.

To verify and unpack the original data, rebuild both processed JSON files,
and then redraw:

```sh
python3 figures/fig7/scripts/rebuild_data.py \
  --work-dir /scratch/fig7-rebuild
MPLCONFIGDIR=/scratch/fig7-matplotlib \
python3 figures/fig7/scripts/plot_figure.py
```

Use a writable disposable directory for `--work-dir`; it holds unpacked copies.
Use `--out-dir /scratch/fig7-processed` when rebuilding JSON files separately.
The plotter accepts `--data` and `--detail-data` to read such alternate inputs.

## Data interpretation

`timeline.json` selects native step 0 / layer 0 events, DQ bursts, and I/O epochs.
`streaming-input-gap.json` records the gap audit and the six consecutive native
down-input WR bursts used in the inset. The selected gap is CK 359548–359562:
14 CK at 938 ps/CK, or 13.132 ns. The RD window needs 11 CK turnaround,
2 CK data, and 2 CK turnaround. Red marks the 1 CK rank-switch shortfall.
The VLM Request row illustrates this timing constraint; it is not a measured
GPU request or SM pause trace. A WR needs 4 CK and is not excluded by this gap.

The older `figures/plot-timeline-rates.py` command remains compatible and delegates
Figure 7 rendering to the canonical script here. It continues to support Figure 10
using its existing shared rate snapshot. The raw archives in this bundle cover
Figure 7's two native runs, not the separate Thor baseline measurements.

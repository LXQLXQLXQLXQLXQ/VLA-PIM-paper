#!/usr/bin/env python3
"""Audit native streaming-input gaps without rerunning the experiment."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path,
                        required=True)
    parser.add_argument('--out', type=Path,
                        default=here.parent/'data/processed/streaming-input-gap.json')
    args = parser.parse_args()
    base = args.experiment
    native = base/'results/combined-e/repeat-1'
    trace = native/'dq-bursts.csv'
    matrix = base/'source/reference/spec/command-pair-matrix.json'
    raw = json.loads((native/'raw.json').read_text())
    verified = json.loads((native/'verification.json').read_text())
    trace_sha = sha(trace)
    assert trace_sha == verified['output_sha256']['repeat-1/dq-bursts.csv']
    assert sha(native/'raw.json') == verified['raw_sha256']
    edges = {r['first'][0]+r['second'][0]: r['dq_gap_ck']
             for r in json.loads(matrix.read_text())
             if r['relation'] == 'different_rank'
             and r['first'] in ['RD', 'WR'] and r['second'] in ['RD', 'WR']}
    assert edges == dict(RR=2, RW=2, WR=11, WW=1)
    required = {q: edges['W'+q]+2+edges[q+'W'] for q in 'RW'}
    stages = {s['stage_id']: s for s in raw['stages']}
    counts = {s: Counter() for s in ['all_input_WW', 'first_layer_input_WW', 'qkv_stage0_WW']}
    previous, examples, down_bursts = {}, {}, []
    with trace.open() as stream:
        for row in csv.DictReader(stream):
            assert row['channel'] == '0'
            burst = {k: row[k] for k in ['direction', 'stage', 'command']}
            burst.update({k: int(row[k]) for k in ['start_ck', 'end_ck', 'stage_id']})
            sid = burst['stage_id']
            if sid == 8:
                down_bursts.append(burst)
            assert burst['end_ck']-burst['start_ck'] == 2
            left = previous.get(sid)
            if left and left['direction'] == burst['direction'] == 'W':
                gap = burst['start_ck']-left['end_ck']
                assert gap >= 0
                counts['all_input_WW'][gap] += 1
                if stages[sid]['step'] == stages[sid]['layer'] == 0:
                    counts['first_layer_input_WW'][gap] += 1
                if sid == 0:
                    counts['qkv_stage0_WW'][gap] += 1
                    if gap in [3, 14] and gap not in examples:
                        examples[gap] = dict(left=left, right=burst, gap_ck=gap)
            previous[sid] = burst
    scopes = {}
    for scope, hist in counts.items():
        no_either = {g: n for g, n in hist.items() if 0 < g < min(required.values())}
        no_read = {g: n for g, n in hist.items() if 0 < g < required['R']}
        assert max(no_either) == 3 and max(no_read) == 14
        scopes[scope] = dict(positive_gap_count=sum(n for g, n in hist.items() if g > 0),
                            gap_counts_up_to_15_ck={str(g): hist[g] for g in range(1, 16)},
                            longest_gap_excluding_both_ck=max(no_either),
                            longest_gap_excluding_read_ck=max(no_read))
    result = dict(clock_ps=raw['clock_ps'], case='combined-e', channel=0, step=0, layer=0,
                  read_excluded_example=examples[14], both_excluded_example=examples[3],
                  cross_rank_dq_edges_ck=edges, gpu_burst_ck=2,
                  required_vlm_window_ck=required, scopes=scopes,
                  definition='Native PIM burst times held fixed. A 14 CK WR-to-WR gap excludes a VLM RD (15 CK minimum), but permits a WR by DQ timing alone (4 CK minimum). This is not a measured GPU SM pause.',
                  source_trace='experiments/2026-11-16/results/combined-e/repeat-1/dq-bursts.csv',
                  source_trace_sha256=trace_sha,
                  source_matrix='experiments/2026-11-16/source/reference/spec/command-pair-matrix.json',
                  source_matrix_sha256=sha(matrix))
    index = next(i for i, (left, right) in enumerate(zip(down_bursts, down_bursts[1:]))
                 if left['direction'] == right['direction'] == 'W'
                 and right['start_ck']-left['end_ck'] == 14)
    selected = down_bursts[index-2:index+4]
    assert len(selected) == 6 and all(b['direction'] == 'W' for b in selected)
    result['zoom'] = dict(stage='down', stage_id=8, gap_ck=14,
                          left=down_bursts[index], right=down_bursts[index+1],
                          bursts=selected,
                          definition='Six consecutive native input WR bursts; GPU RD row shows required DQ timing rather than observed GPU requests.')
    result['read_excluded_example'] = dict(left=down_bursts[index],
                                           right=down_bursts[index+1], gap_ck=14)
    args.out.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(required_ck=required, scopes=scopes,
                          zoom=result['zoom']), indent=2))


if __name__ == '__main__':
    main()

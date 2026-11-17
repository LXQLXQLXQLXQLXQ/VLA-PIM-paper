#!/usr/bin/env python3
"""Verify bundled original results and rebuild Figure 7's processed inputs.

Only Python's standard library is required. No simulator or network is used.
The explicit work directory holds disposable, unpacked copies of raw files.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def unpack(raw_dir, manifest, experiment):
    for entry in manifest['archives']:
        archive = raw_dir/entry['file']
        assert sha(archive) == entry['sha256'], f'Archive checksum: {archive}'
        expected = {f['path']: f for f in entry['files']}
        with tarfile.open(archive, 'r:gz') as source:
            assert set(source.getnames()) == set(expected), 'Unexpected archive members'
            for member in source.getmembers():
                relative = PurePosixPath(member.name)
                assert member.isfile() and not relative.is_absolute() and '..' not in relative.parts
                target = experiment/Path(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as incoming, target.open('wb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
                record = expected[member.name]
                assert target.stat().st_size == record['bytes']
                assert sha(target) == record['sha256'], f'Native file checksum: {member.name}'
        native = experiment/'results'/entry['native_case']/'repeat-1'
        verification = json.loads((native/'verification.json').read_text())
        for file in entry['files']:
            name = PurePosixPath(file['path']).name
            if name != 'verification.json':
                assert file['sha256'] == verification['output_sha256']['repeat-1/'+name]
        assert sha(native/'raw.json') == verification['raw_sha256']
    reference = manifest['reference']
    assert sha(raw_dir/reference['file']) == reference['sha256']
    target = experiment/reference['path']
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(raw_dir/reference['file'], target)


def overview(native, entry):
    timeline = json.loads((native/'dq-timeline.json').read_text())
    events = [e for e in timeline['events'] if e['step'] == 0 and e['layer'] == 0]
    lo, hi = min(e['start_ck'] for e in events), max(e['end_ck'] for e in events)
    bursts, epochs = [], []
    for filename, destination in [('dq-bursts.csv', bursts), ('dq-epochs.csv', epochs)]:
        with (native/filename).open() as stream:
            for row in csv.DictReader(stream):
                start, end = int(row['start_ck']), int(row['end_ck'])
                if int(row['channel']) == 0 and start >= lo and end <= hi:
                    destination.append([start, end])
    assert all(end-start == 2 for start, end in bursts)
    return timeline['clock_ps'], dict(
        case=entry['native_case'], title=entry['panel_title'], lo_ck=lo, hi_ck=hi,
        events=events, pim_dq_bursts_ck=bursts, io_epochs_ck=epochs)


def main():
    bundle = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir', type=Path, default=bundle/'data/raw')
    parser.add_argument('--out-dir', type=Path, default=bundle/'data/processed')
    parser.add_argument('--work-dir', type=Path, required=True,
                        help='Disposable extraction directory, e.g. /scratch/fig7-rebuild')
    args = parser.parse_args()
    manifest = json.loads((args.raw_dir/'manifest.json').read_text())
    experiment = args.work_dir.resolve()/'experiment-2026-11-16'
    unpack(args.raw_dir, manifest, experiment)
    cases, clocks = [], []
    for entry in manifest['archives']:
        native = experiment/'results'/entry['native_case']/'repeat-1'
        clock, case = overview(native, entry)
        clocks.append(clock)
        cases.append(case)
    assert clocks == [938, 938]
    result = dict(schema_version=1, clock_ps=clocks[0], timeline_cases=cases,
                  provenance=dict(source='Bundled native experiment output; step 0, layer 0, channel 0',
                                  raw_manifest_sha256=sha(args.raw_dir/'manifest.json')))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir/'timeline.json').write_text(json.dumps(result, indent=2)+'\n')
    subprocess.run([sys.executable, str(bundle/'scripts/analyze_gaps.py'),
                    '--experiment', str(experiment), '--out',
                    str(args.out_dir/'streaming-input-gap.json')], check=True,
                   stdout=subprocess.PIPE, text=True)
    print('Verified both original archives and all 18 native files against their checksums.')
    print(f'Rebuilt timeline.json and streaming-input-gap.json in {args.out_dir}')


if __name__ == '__main__':
    main()

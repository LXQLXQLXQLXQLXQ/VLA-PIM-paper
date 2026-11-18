#!/usr/bin/env python3
"""Verify archived bytes, integrate Thor telemetry, and recompute both IDD reports.

This uses only the Python standard library and the adjacent g_power_report.py.
It does not run a model or submit a simulator job.
"""
import argparse
from bisect import bisect_left, bisect_right
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

import g_power_report


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_bytes(path):
    return gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()


def load(path):
    return json.loads(read_bytes(path))


def near(actual, expected, message):
    require(math.isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-9),
            f'{message}: {actual} != {expected}')


def compare_numbers(actual, expected, context):
    if isinstance(actual, dict):
        for key, value in actual.items():
            compare_numbers(value, expected[key], context + '.' + key)
    elif isinstance(actual, list):
        require(len(actual) == len(expected), context + ': length differs')
        for index, value in enumerate(actual):
            compare_numbers(value, expected[index], context + f'[{index}]')
    elif isinstance(actual, (int, float)) and not isinstance(actual, bool):
        near(actual, expected, context)
    else:
        require(actual == expected, context + ': value differs')


def thor_measurement(folder):
    measurement = load(folder / 'measurements.json')
    blocks = sorted((b for b in measurement['blocks'] if b['mode'] == 'fresh_cache'),
                    key=lambda b: b['round'])
    require(measurement.get('finished'), 'Thor run did not finish')
    require([b['round'] for b in blocks] == [1, 2, 3], 'Expected three fresh-cache rounds')
    rails = ('VIN', 'VDD_GPU', 'VDD_CPU_SOC_MSS', 'VIN_SYS_5V0')
    pattern = re.compile(r'\b(' + '|'.join(rails) + r')\s+(\d+)mW')
    readings = []
    for line in read_bytes(folder / 'tegrastats.tsv.gz').decode().splitlines():
        stamp, text = line.split('\t', 1)
        powers = {rail: int(value) / 1000 for rail, value in pattern.findall(text)}
        if set(powers) == set(rails):
            readings.append((int(stamp), powers))
    times = [stamp for stamp, _ in readings]
    require(all(a < b for a, b in zip(times, times[1:])), 'Telemetry times not increasing')
    seconds, chunks = 0, 0
    energies = {rail: 0.0 for rail in rails}
    for block in blocks:
        start, end = block['start_monotonic_ns'], block['end_monotonic_ns']
        near((end - start) / 1e9, block['seconds'], 'Window duration')
        require(block['seconds'] == 30 and block['ae_count'] > 0, 'Incomplete Thor window')
        first, last = bisect_right(times, start) - 1, bisect_left(times, end)
        require(first >= 0 and last < len(readings), 'Telemetry does not bracket window')
        selected = readings[first:last + 1]
        require(all(b - a <= 300_000_000 for (a, _), (b, _) in zip(selected, selected[1:])),
                'Telemetry gap exceeds 300 ms')
        for rail in rails:
            energy = 0.0
            for (a, pa), (b, pb) in zip(selected, selected[1:]):
                lo, hi = max(a, start), min(b, end)
                if hi > lo:
                    left = pa[rail] + (pb[rail] - pa[rail]) * (lo - a) / (b - a)
                    right = pa[rail] + (pb[rail] - pa[rail]) * (hi - a) / (b - a)
                    energy += (left + right) * 0.5 * (hi - lo) / 1e9
            near(energy, block['power'][rail]['energy_j'], 'Integrated ' + rail)
            near(energy / block['seconds'], block['power'][rail]['mean_w'], 'Average ' + rail)
            energies[rail] += energy
        seconds += block['seconds']
        chunks += block['ae_count']
    return {'seconds': seconds, 'AE_chunks': chunks,
            'board_W': energies['VIN'] / seconds, 'GPU_W': energies['VDD_GPU'] / seconds,
            'completion_period_ms': seconds / chunks * 1000,
            'board_J_per_chunk': energies['VIN'] / chunks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.data.resolve()
    manifest = load(root / 'SOURCE-MANIFEST.json')['files']
    for relative, entry in manifest.items():
        path = root / relative
        require(hashlib.sha256(path.read_bytes()).hexdigest() == entry['stored_sha256'],
                'Stored file hash differs: ' + relative)
        require(hashlib.sha256(read_bytes(path)).hexdigest() == entry['source_sha256'],
                'Original byte hash differs: ' + relative)
    original = load(root / 'original/comparison.json')
    logic = load(root / 'configs/pim-logic-power-533mhz.json')
    logic_w = logic['image_reported_total_mW_per_bank'] * logic['PIM_banks'] / 1000
    require(logic['PIM_banks'] == 256, 'PIM bank count differs')
    results = []
    for model, row in zip(('pi05', 'gr00t'), original['models']):
        folder = root / 'models' / model
        raw = load(folder / 'raw.json.gz')
        stats = load(folder / 'dram-power-stats.json.gz')
        spec = load(root / f'configs/{model}-spec-k2.json')
        model_file = 'pi05-micron-8533-aat-proxy.json' if model == 'pi05' else 'micron-8533-aat-proxy.json'
        rebuilt = g_power_report.report(stats, raw, spec, load(root / 'configs' / model_file), rho=0.5)
        saved = load(folder / 'power-report.json')
        for key in ('duration_ms', 'reference_energy_J', 'reference_average_power_W',
                    'PIM_energy_parameterization', 'coefficients', 'ranks', 'stages',
                    'statistics_validation'):
            compare_numbers(rebuilt[key], saved[key], model + '.' + key)
        require(saved['statistics_validation']['native_raw_byte_identical_to_baseline'],
                model + ': original passive-observer comparison failed')
        measured = thor_measurement(folder / 'thor')
        near(measured['board_W'], row['baseline_board_average_W'], model + ': board power')
        near(measured['GPU_W'], row['GPU_average_power_proxy_W'], model + ': GPU power')
        near(measured['completion_period_ms'], row['baseline_completion_period_ms'], model + ': period')
        near(rebuilt['reference_average_power_W'], row['DRAM_reference_average_power_W'], model + ': DRAM power')
        total_w = measured['GPU_W'] + rebuilt['reference_average_power_W'] + logic_w
        g_j = total_w * rebuilt['duration_ms'] / 1000
        near(total_w, row['estimated_g_average_W'], model + ': combined power')
        near(g_j, row['estimated_g_energy_J'], model + ': g energy')
        near(measured['board_W'] / total_w, row['power_ratio'], model + ': power ratio')
        near(measured['board_J_per_chunk'] / g_j, row['energy_ratio'], model + ': energy ratio')
        results.append({'model': model, 'Thor': measured, 'DRAM_W': rebuilt['reference_average_power_W'],
                        'g_W': total_w, 'g_J': g_j, 'energy_ratio': row['energy_ratio']})
    print(json.dumps({'verified_archived_files': len(manifest),
                      'telemetry_and_native_counter_audits': 'passed', 'models': results}, indent=2))


if __name__ == '__main__':
    main()

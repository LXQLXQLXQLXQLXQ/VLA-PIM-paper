"""GR00T N1.6 fresh-cache GPU baseline, with time-integrated Thor rail power.

Use the same input fixture, cached AE implementation, and compilation options
as the frozen 640x480 GR00T benchmark. Each AE waits for its own newly built
VLM cache; the next VLM may overlap that AE, matching the pi0.5 fresh_cache run.
"""
import argparse
from bisect import bisect_left, bisect_right
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import statistics
import subprocess
import sys
from threading import Thread
from time import monotonic_ns, sleep

import torch
from torch._dynamo.utils import counters
from transformers.feature_extraction_utils import BatchFeature
from transformers.modeling_utils import no_init_weights

from bench_gr00t_dual_stream import make_cached_head, new_noise
from capture_gr00t_thor import OPTIONS, SPEC, compare_embedding, load_weights, setup, write

NS = 1_000_000_000
RAILS = ("VIN", "VDD_GPU", "VDD_CPU_SOC_MSS", "VIN_SYS_5V0")
POWER_RE = re.compile(r"\b(" + "|".join(RAILS) + r")\s+(\d+)mW")


class Telemetry:
    def __init__(self, path):
        self.path, self.readings, self.error = path, [], None

    def __enter__(self):
        self.process = subprocess.Popen(["tegrastats", "--interval", "50"],
                                        stdout=subprocess.PIPE, text=True, bufsize=1)
        self.thread = Thread(target=self.read, daemon=True)
        self.thread.start()
        return self

    def read(self):
        try:
            with self.path.open("w", buffering=1) as out:
                for line in self.process.stdout:
                    stamp = monotonic_ns()
                    out.write(f"{stamp}\t{line}")
                    watts = {k: int(v) / 1000 for k, v in POWER_RE.findall(line)}
                    if set(watts) == set(RAILS):
                        self.readings.append((stamp, watts))
        except Exception as exc:
            self.error = repr(exc)

    def __exit__(self, *_):
        self.process.terminate()
        self.process.wait(timeout=5)
        self.thread.join(timeout=5)
        self.process.stdout.close()

    def window(self, start, end):
        sleep(0.2)
        if self.error:
            raise RuntimeError(self.error)
        readings = self.readings[:]
        times = [stamp for stamp, _ in readings]
        first, last = bisect_right(times, start) - 1, bisect_left(times, end)
        if first < 0 or last >= len(times):
            raise RuntimeError("Power samples do not bracket the measurement window")
        selected = readings[first:last + 1]
        if any(b - a > 0.30 * NS for (a, _), (b, _) in zip(selected, selected[1:])):
            raise RuntimeError("Power sampling gap exceeds 300 ms")
        output = {}
        for rail in RAILS:
            energy = 0.0
            for (a, left), (b, right) in zip(selected, selected[1:]):
                lo, hi = max(a, start), min(b, end)
                if hi > lo:
                    p, q = left[rail], right[rail]
                    energy += (p + (q - p) * (lo + hi - 2 * a) / (2 * (b - a))) * (hi - lo) / NS
            values = [r[rail] for stamp, r in selected if start <= stamp < end]
            if len(values) < 20:
                raise RuntimeError("Insufficient power samples")
            ordered = sorted(values)
            output[rail] = dict(mean_w=energy * NS / (end - start), energy_j=energy,
                                p95_sample_w=ordered[int(0.95 * (len(ordered) - 1))],
                                max_sample_w=max(values))
        return output, len(selected) - 2


def event():
    return torch.cuda.Event(enable_timing=True)


def fresh_cache_block(forward, project, action, frames, inputs, head, state,
                      embodiment, streams, warmup, seconds):
    vs, aes = streams
    torch.cuda.synchronize()
    origin = event()
    origin.record()
    origin.synchronize()
    anchor = monotonic_ns()
    begin = anchor + round(warmup * NS)
    end = begin + round(seconds * NS)
    pending, spans = deque(), []
    last_start = None
    while monotonic_ns() < end:
        frame = len(spans) % len(frames)
        with torch.cuda.stream(vs):
            if last_start is not None:
                vs.wait_event(last_start)
            v0, v1, vd = event(), event(), event()
            v0.record()
            embedding = forward(inputs[0], inputs[1], frames[frame], inputs[3])
            v1.record()
            cache = project(embedding)
            vd.record()
        with torch.cuda.stream(aes):
            aes.wait_event(vd)
            a0, ad = event(), event()
            a0.record()
            noise = new_noise(head, state)
            output = action(cache, state, embodiment, noise)
            ad.record()
        spans.append((v0, v1, vd, a0, ad))
        pending.append((ad, cache, output, noise))
        if len(pending) >= 2:
            pending[0][0].synchronize()
            pending.popleft()
        last_start = a0
    pending[-1][0].synchronize()
    # Keep only two in-flight tensor sets; events do not retain every KV cache.
    final_cache, final_output, final_noise = cache, output, noise

    def stamp(e):
        return anchor + round(origin.elapsed_time(e) * 1e6)

    intervals = [tuple(stamp(e) for e in row) for row in spans]
    assert all(vd <= a0 + 10_000 for _, _, vd, a0, _ in intervals)
    assert all(previous[3] <= current[0] + 10_000
               for previous, current in zip(intervals, intervals[1:]))
    completions = [ad for _, _, _, _, ad in intervals if begin <= ad < end]
    vlm_count = sum(begin <= vd < end for _, _, vd, _, _ in intervals)
    if len(completions) < 2:
        raise RuntimeError("Too few completed AE chunks")
    periods = [(b - a) / 1e6 for a, b in zip(completions, completions[1:])]
    overlap = sum(max(0, min(left[4], right[2], end) - max(left[3], right[0], begin))
                  for left, right in zip(intervals, intervals[1:])) / NS
    if overlap <= 0:
        raise RuntimeError("Fresh-cache streams did not overlap")
    if not torch.isfinite(final_output).all():
        raise RuntimeError("Nonfinite action output")
    # Validate the final result with identical cache/noise after the timed window.
    rerun = action(final_cache, state, embodiment, final_noise)
    torch.cuda.synchronize()
    torch.testing.assert_close(rerun, final_output, rtol=0, atol=0)
    return dict(mode="fresh_cache", start_monotonic_ns=begin, end_monotonic_ns=end,
                seconds=seconds, ae_count=len(completions), vlm_count=vlm_count,
                ae_hz=len(completions) / seconds, vlm_hz=vlm_count / seconds,
                average_completion_period_ms=seconds * 1000 / len(completions),
                observed_period_ms=dict(mean=statistics.mean(periods), p50=statistics.median(periods)),
                stream_interval_overlap_s=overlap, own_fresh_cache_dependency_checked=True,
                no_early_next_VLM_checked=True, repeated_output_exact=True)


@torch.inference_mode()
def run(args):
    if socket.gethostname().split('.')[0] != "fact-thor":
        raise RuntimeError("Run this measurement on fact-thor")
    torch.set_num_interop_threads(1)
    config, vlm, inputs, image_mask, fixture = setup(args)
    if fixture['vl_tokens'] != 371 or fixture['vit_input_shapes'] != [[1, 3, 252, 336]] * 3:
        raise RuntimeError("GR00T fixture differs from 640x480 simulation inputs")
    from gr00t.model.gr00t_n1d6.gr00t_n1d6 import Gr00tN1d6ActionHead
    with no_init_weights():
        head = Gr00tN1d6ActionHead(config)
    head = load_weights(head, args.checkpoint, "action_head.")
    assert head.num_inference_timesteps == 4 and head.action_horizon == 15
    project, denoise = make_cached_head(head, image_mask, inputs[1])
    embedding = vlm(*inputs)
    state = embedding.new_zeros((1, SPEC.state_tokens, config.max_state_dim))
    embodiment = torch.tensor([2], device="cuda")
    cache = project(embedding)
    assert len(cache) == 32
    torch.manual_seed(31)
    noise = new_noise(head, state)
    torch.manual_seed(31)
    official = head.get_action(BatchFeature(dict(backbone_features=embedding,
                               backbone_attention_mask=inputs[1], image_mask=image_mask)),
                               BatchFeature(dict(state=state, embodiment_id=embodiment))).action_pred
    cached = denoise(cache, state, embodiment, noise)
    torch.testing.assert_close(cached, official, rtol=0.012, atol=0.0039)
    correctness = compare_embedding(official, cached)
    frames = [inputs[2], [p.flip(-1).contiguous() for p in inputs[2]],
              [p.roll(8, -1).contiguous() for p in inputs[2]],
              [p.flip(-2).contiguous() for p in inputs[2]]]
    funcs = (torch.compile(vlm, dynamic=False, options=OPTIONS),
             torch.compile(project, fullgraph=True, dynamic=False, options=OPTIONS),
             torch.compile(denoise, fullgraph=True, dynamic=False, options=OPTIONS))
    forward, build, action = funcs
    print("Compiling and warming GR00T VLM, cache projection, and H15 AE", flush=True)
    for index in range(8):
        embedding = forward(inputs[0], inputs[1], frames[index % 4], inputs[3])
        cache = build(embedding)
        action(cache, state, embodiment, noise)
    torch.cuda.synchronize()
    streams = torch.cuda.Stream(), torch.cuda.Stream()
    report = dict(fixture, host=socket.gethostname(), interval_ms=50,
                  started=datetime.now(timezone.utc).isoformat(), blocks=[],
                  cache_correctness=correctness,
                  ae_scope="Cached cross K/V, state/action encoding, 4 x 32 DiT layers, decoder and fresh noise",
                  cache_semantics="Each AE waits for its own current VLM + per-layer K/V; next VLM can overlap that AE",
                  power_mode=subprocess.check_output(["nvpmodel", "-q"], text=True).strip(),
                  source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in Path(__file__).parent.glob('*.py')})
    graphs = counters['stats']['unique_graphs']
    report['compiled_graphs'] = graphs
    with Telemetry(args.output / 'tegrastats.tsv') as telemetry:
        sleep(0.3)
        for repeat in range(args.rounds):
            print(f"Fresh-cache power round {repeat + 1}: {args.seconds:g} seconds", flush=True)
            row = fresh_cache_block(forward, build, action, frames, inputs, head, state,
                                    embodiment, streams, args.warmup, args.seconds)
            assert counters['stats']['unique_graphs'] == graphs, 'recompilation in timed interval'
            row['power'], row['power_samples'] = telemetry.window(row['start_monotonic_ns'], row['end_monotonic_ns'])
            row['round'] = repeat + 1
            row['vin_j_per_ae_chunk'] = row['power']['VIN']['energy_j'] / row['ae_count']
            row['gpu_j_per_ae_chunk'] = row['power']['VDD_GPU']['energy_j'] / row['ae_count']
            report['blocks'].append(row)
            write(args.output / 'measurements.json', report)
            print(f"VIN {row['power']['VIN']['mean_w']:.3f} W; GPU {row['power']['VDD_GPU']['mean_w']:.3f} W; AE {row['ae_hz']:.3f}/s", flush=True)
    report['finished'] = datetime.now(timezone.utc).isoformat()
    report['power_mode_after'] = subprocess.check_output(['nvpmodel', '-q'], text=True).strip()
    assert report['power_mode_after'] == report['power_mode']
    write(args.output / 'measurements.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--warmup', type=float, default=4)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--prompt', default='Pick up the object and place it on the table.')
    args = parser.parse_args()
    if args.seconds < 2 or args.warmup < 0 or args.rounds < 1:
        parser.error('need >= 2 seconds per round, nonnegative warmup, and >= 1 round')
    args.image_size, args.image_width, args.image_height = 448, 640, 480
    args.default_image_preprocess, args.expected_vit_size, args.cameras = True, (336, 252), 3
    args.mode = 'power'
    args.output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(args.source))
    run(args)

"""Measure steady-state Thor power for three pi0.5 MHA8 CUDA schedules."""

import argparse
from bisect import bisect_left, bisect_right
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import re
import socket
import subprocess
from threading import Barrier, Thread
from time import monotonic_ns, sleep

import torch
from torch._dynamo.utils import counters

from bench_parallel import OPTIONS, cuda_event, make_workload
from common import compare, gpu_guard, stats


MODES = ("serial", "fresh_cache", "independent")
RAILS = ("VIN", "VDD_GPU", "VDD_CPU_SOC_MSS", "VIN_SYS_5V0")
POWER_RE = re.compile(r"\b(" + "|".join(RAILS) + r")\s+(\d+)mW")
NS = 1_000_000_000


class Telemetry:
    def __init__(self, path):
        self.path = path
        self.readings = []

    def __enter__(self):
        self.process = subprocess.Popen(
            ["tegrastats", "--interval", "50"], stdout=subprocess.PIPE, text=True, bufsize=1
        )
        self.thread = Thread(target=self.read)
        self.thread.start()
        return self

    def read(self):
        with self.path.open("w", buffering=1) as output:
            for line in self.process.stdout:
                stamp = monotonic_ns()
                output.write(f"{stamp}\t{line}")
                watts = {key: int(value) / 1000 for key, value in POWER_RE.findall(line)}
                if set(watts) == set(RAILS):
                    self.readings.append((stamp, watts))

    def __exit__(self, *_):
        self.process.terminate()
        self.process.wait(timeout=5)
        self.thread.join(timeout=5)
        self.process.stdout.close()

    def window(self, start, end):
        sleep(0.15)
        readings = self.readings[:]
        times = [stamp for stamp, _ in readings]
        first = bisect_right(times, start) - 1
        last = bisect_left(times, end)
        if first < 0 or last >= len(readings):
            raise RuntimeError("Tegrastats samples do not bracket the measurement")
        readings = readings[first : last + 1]
        if any(b - a > 0.30 * NS for (a, _), (b, _) in zip(readings, readings[1:])):
            raise RuntimeError("Tegrastats sample gap exceeds 300 ms")
        results = {}
        for rail in RAILS:
            energy = 0.0
            for (a, left), (b, right) in zip(readings, readings[1:]):
                lo, hi = max(a, start), min(b, end)
                if hi > lo:
                    p, q = left[rail], right[rail]
                    energy += ((p + (q - p) * ((lo + hi - 2 * a) / (b - a)) / 2)
                               * (hi - lo) / NS)
            values = [rails[rail] for stamp, rails in readings if start <= stamp < end]
            results[rail] = dict(
                mean_w=energy * NS / (end - start), energy_j=energy,
                p95_sample_w=stats(values)["p95"], max_sample_w=max(values)
            )
        return results, last - first - 1 + int(times[first] == start)


def queue_work(pending, done, *keepalive):
    pending.append((done, keepalive))
    if len(pending) >= 2:
        pending[0][0].synchronize()
        pending.popleft()


def combined(mode, context, deadline):
    frames, prefix, denoise, vlm_stream, ae_stream, _, _ = context
    if mode == "serial":
        vlm_stream = ae_stream = torch.cuda.default_stream()
    pending = deque()
    vlm_spans, ae_spans = [], []
    ae_start = None
    while monotonic_ns() < deadline:
        i = len(ae_spans)
        with torch.cuda.stream(vlm_stream):
            if mode == "fresh_cache" and ae_start is not None:
                vlm_stream.wait_event(ae_start)
            vlm_start, vlm_done = cuda_event(), cuda_event()
            vlm_start.record()
            cache = prefix(frames[i % len(frames)])
            vlm_done.record()
        with torch.cuda.stream(ae_stream):
            if mode == "fresh_cache":
                ae_stream.wait_event(vlm_done)
            ae_start, ae_done = cuda_event(), cuda_event()
            ae_start.record()
            actions = denoise(cache)
            ae_done.record()
        vlm_spans.append((vlm_start, vlm_done))
        ae_spans.append((ae_start, ae_done))
        queue_work(pending, ae_done, cache, actions)
    pending[-1][0].synchronize()
    return vlm_spans, ae_spans, i % len(frames), actions


def independent(context, deadline):
    frames, prefix, denoise, vlm_stream, ae_stream, fixed_cache, pool = context
    launch = Barrier(2, timeout=10)

    @torch.inference_mode()
    def feed(stream, work, inputs):
        pending, spans = deque(), []
        with torch.cuda.stream(stream):
            launch.wait()
            while monotonic_ns() < deadline:
                start, done = cuda_event(), cuda_event()
                start.record()
                result = work(inputs[len(spans) % len(inputs)])
                done.record()
                spans.append((start, done))
                queue_work(pending, done, result)
            pending[-1][0].synchronize()
        return spans, result

    vlm = pool.submit(feed, vlm_stream, prefix, frames)
    ae = pool.submit(feed, ae_stream, denoise, [fixed_cache])
    ae_spans, actions = ae.result()
    vlm_spans, _ = vlm.result()
    return vlm_spans, ae_spans, 0, actions


def span_overlap(left, right, start, end):
    i = j = 0
    overlap = 0
    while i < len(left) and j < len(right):
        a, b = left[i]
        c, d = right[j]
        overlap += max(0, min(b, d, end) - max(a, c, start))
        if b <= d:
            i += 1
        else:
            j += 1
    return overlap


def block(mode, context, refs, warmup, seconds):
    origin = cuda_event()
    origin.record()
    origin.synchronize()
    anchor = monotonic_ns()
    start = anchor + round(warmup * NS)
    end = start + round(seconds * NS)
    vlm, ae, frame, actions = (
        independent(context, end) if mode == "independent" else combined(mode, context, end)
    )
    output_check = compare(actions, refs[frame])
    if not output_check["accepted"]:
        raise RuntimeError(f"{mode} action output mismatch: {output_check}")

    def stamps(events):
        return [(anchor + round(origin.elapsed_time(a) * 1e6),
                 anchor + round(origin.elapsed_time(b) * 1e6)) for a, b in events]

    vlm, ae = stamps(vlm), stamps(ae)
    vlm_count = sum(start <= b < end for _, b in vlm)
    ae_count = sum(start <= b < end for _, b in ae)
    overlap = span_overlap(vlm, ae, start, end)
    # CUDA event timestamps have finite resolution. Allow 10 microseconds at dependencies.
    if mode != "independent":
        assert len(vlm) == len(ae) and all(b <= c + 10_000 for (_, b), (c, _) in zip(vlm, ae))
    if mode == "fresh_cache":
        assert all(a <= c + 10_000 for (a, _), (c, _) in zip(ae, vlm[1:]))
    if mode == "serial":
        assert overlap < 100_000
    if mode != "serial" and seconds >= 2:
        assert overlap > 0, f"{mode}: no stream interval overlap"
    assert ae_count and vlm_count
    return dict(mode=mode, start_monotonic_ns=start, end_monotonic_ns=end, seconds=seconds,
                ae_count=ae_count, vlm_count=vlm_count, ae_hz=ae_count / seconds,
                vlm_hz=vlm_count / seconds, stream_interval_overlap_s=overlap / NS,
                output_check=output_check)


@torch.inference_mode()
def main(args):
    gpu_guard()
    assert torch.cuda.device_count() == 1
    assert torch.cuda.get_device_properties(0).multi_processor_count == 20
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(17)
    profile = json.loads(args.vlm_profile.read_text())
    with torch.inference_mode(False), torch.no_grad():
        frames, prefix, denoise, _, workload = make_workload(
            args.support, True, mha8=True, vlm_compile_options=profile["compile_options"]
        )
    assert str(torch.__version__) == profile["torch"]
    assert workload["checkpoint"] == profile["checkpoint"]
    assert workload["kv_heads"] == profile["conversion"]["kv_heads"] == 8
    assert workload["gemma_overlay_sha256"] == profile["gemma_overlay_sha256"]
    print("Warming the compiled VLM and AE graphs", flush=True)
    caches = [prefix(frame) for frame in frames]
    refs = [denoise(cache) for cache in caches]
    torch.cuda.synchronize()
    gpu = torch.cuda.get_device_properties(0)
    meta = dict(host=socket.gethostname(), gpu=gpu.name, sm_count=gpu.multi_processor_count,
                cuda_visible_devices=os.environ.get("CUDA_VISIBLE_DEVICES"), pid=os.getpid(),
                started=datetime.now().astimezone().isoformat(), torch=str(torch.__version__),
                cuda=torch.version.cuda, power_mode=subprocess.check_output(["nvpmodel", "-q"], text=True).strip(),
                l4t=Path("/etc/nv_tegra_release").read_text().splitlines()[0],
                interval_ms=50, ae_compile_options=OPTIONS,
                vlm_compile_options=profile["compile_options"], workload=workload, blocks=[])
    output = args.output / "measurements.json"
    with ThreadPoolExecutor(max_workers=2) as pool:
        context = (frames, prefix, denoise, torch.cuda.Stream(), torch.cuda.Stream(), caches[0], pool)
        for mode in MODES:
            print(f"Validating {mode}", flush=True)
            block(mode, context, refs, warmup=2, seconds=3)
        graphs = counters["stats"]["unique_graphs"]
        assert graphs > 0
        meta["compiled_graphs"] = graphs
        with Telemetry(args.output / "tegrastats.tsv") as telemetry:
            sleep(0.3)
            for repeat in range(args.rounds):
                for mode in MODES[repeat % len(MODES):] + MODES[:repeat % len(MODES)]:
                    gpu_guard()
                    print(f"Round {repeat + 1}: measuring {mode} for {args.seconds:g} s", flush=True)
                    record = block(mode, context, refs, args.warmup, args.seconds)
                    assert counters["stats"]["unique_graphs"] == graphs, counters["stats"]
                    gpu_guard()
                    record["power"], record["power_samples"] = telemetry.window(
                        record["start_monotonic_ns"], record["end_monotonic_ns"]
                    )
                    record["round"] = repeat + 1
                    record["vin_j_per_ae_chunk"] = record["power"]["VIN"]["energy_j"] / record["ae_count"]
                    record["gpu_j_per_ae_chunk"] = record["power"]["VDD_GPU"]["energy_j"] / record["ae_count"]
                    meta["blocks"].append(record)
                    output.write_text(json.dumps(meta, indent=2) + "\n")
                    print(f"{mode}: VIN {record['power']['VIN']['mean_w']:.3f} W, "
                          f"GPU {record['power']['VDD_GPU']['mean_w']:.3f} W, "
                          f"AE {record['ae_hz']:.3f}/s, VLM {record['vlm_hz']:.3f}/s", flush=True)
    meta["power_mode_after"] = subprocess.check_output(["nvpmodel", "-q"], text=True).strip()
    assert meta["power_mode_after"] == meta["power_mode"]
    meta["finished"] = datetime.now().astimezone().isoformat()
    output.write_text(json.dumps(meta, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--support", type=Path, required=True)
    parser.add_argument("--vlm-profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--warmup", type=float, default=4)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    if args.seconds < 2 or args.warmup < 0 or args.rounds < 1:
        parser.error("need at least 2 seconds per block and at least 1 round")
    main(args)

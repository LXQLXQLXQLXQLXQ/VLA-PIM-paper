"""Continuous GR00T N1.6 with latest completed per-layer cross-attention KV."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
from threading import Barrier, Event, Lock
from time import perf_counter_ns

import torch
import torch.nn.functional as F
from torch._dynamo.utils import counters
from transformers.feature_extraction_utils import BatchFeature
from transformers.modeling_utils import no_init_weights

from capture_gr00t_thor import OPTIONS, SPEC, compare_embedding, load_weights, setup, write


def stats(values):
    if not values:
        return None
    return dict(n=len(values), mean=statistics.mean(values), p50=statistics.median(values),
                p90=statistics.quantiles(values, n=10, method="inclusive")[8] if len(values) > 1 else values[0],
                min=min(values), max=max(values), samples=values)


def event():
    return torch.cuda.Event(enable_timing=True)


def make_cached_head(head, image_mask, valid):
    dit = head.model
    cross_blocks = [block for i, block in enumerate(dit.transformer_blocks) if i % 2 == 0]
    for block in dit.transformer_blocks:
        a = block.attn1
        if type(a.processor).__name__ != "AttnProcessor2_0":
            raise ValueError(f"unexpected attention processor {type(a.processor).__name__}")
        if a.spatial_norm is not None or a.group_norm is not None:
            raise ValueError("unsupported attention input normalization")
    masks = []
    for i, block in enumerate(dit.transformer_blocks):
        if i % 2 == 0:
            mask = (~image_mask & valid) if i % (2 * dit.attend_text_every_n_blocks) == 0 else (image_mask & valid)
            a = block.attn1
            mask = a.prepare_attention_mask(mask, valid.shape[1], valid.shape[0])
            masks.append(mask.view(valid.shape[0], a.heads, -1, mask.shape[-1]))

    def build_cache(embedding):
        v = head.vlln(embedding)
        cache = []
        for block in cross_blocks:
            a = block.attn1
            source = a.norm_encoder_hidden_states(v) if a.norm_cross else v
            key, value = a.to_k(source), a.to_v(source)
            key = key.view(v.shape[0], -1, a.heads, key.shape[-1] // a.heads).transpose(1, 2)
            value = value.view(v.shape[0], -1, a.heads, value.shape[-1] // a.heads).transpose(1, 2)
            if a.norm_k is not None:
                key = a.norm_k(key)
            cache.extend((key, value))
        return tuple(cache)

    def denoise(cache, state, embodiment, noise):
        state_features = head.state_encoder(state, embodiment)
        actions = noise
        for step in range(head.num_inference_timesteps):
            timestep = torch.full((state.shape[0],), step * head.num_timestep_buckets // head.num_inference_timesteps,
                                  device=state.device)
            x = head.action_encoder(actions, timestep, embodiment)
            if head.config.add_pos_embed:
                position = torch.arange(x.shape[1], dtype=torch.long, device=x.device)
                x = x + head.position_embedding(position).unsqueeze(0)
            x = torch.cat((state_features, x), dim=1).contiguous()
            temb = dit.timestep_encoder(timestep)
            cross = 0
            for i, block in enumerate(dit.transformer_blocks):
                if i % 2:
                    x = block(x, attention_mask=None, encoder_hidden_states=None,
                              encoder_attention_mask=None, temb=temb)
                    continue
                z = block.norm1(x, temb) if block.norm_type == "ada_norm" else block.norm1(x)
                if block.pos_embed is not None:
                    z = block.pos_embed(z)
                a = block.attn1
                q = a.to_q(z)
                q = q.view(x.shape[0], -1, a.heads, q.shape[-1] // a.heads).transpose(1, 2)
                if a.norm_q is not None:
                    q = a.norm_q(q)
                y = F.scaled_dot_product_attention(q, cache[2 * cross], cache[2 * cross + 1],
                                                  attn_mask=masks[cross], dropout_p=0.0, is_causal=False)
                y = y.transpose(1, 2).reshape(x.shape[0], -1, a.heads * q.shape[-1]).to(q.dtype)
                y = a.to_out[1](a.to_out[0](y))
                if a.residual_connection:
                    y = y + z
                y = y / a.rescale_output_factor
                if block.final_dropout is not None:
                    y = block.final_dropout(y)
                x = x + y
                if x.ndim == 4:
                    x = x.squeeze(1)
                x = x + block.ff(block.norm3(x))
                if x.ndim == 4:
                    x = x.squeeze(1)
                cross += 1
            shift, scale = dit.proj_out_1(F.silu(temb)).chunk(2, dim=1)
            x = dit.norm_out(x) * (1 + scale[:, None]) + shift[:, None]
            pred = head.action_decoder(dit.proj_out_2(x), embodiment)[:, -head.action_horizon:]
            actions = actions + (1.0 / head.num_inference_timesteps) * pred
        return actions

    return build_cache, denoise


@dataclass
class Cache:
    version: int
    frame: int
    tensors: tuple
    start: object
    vlm_done: object
    done: object


def new_noise(head, state):
    return torch.randn((state.shape[0], head.action_horizon, head.action_dim), device=state.device, dtype=state.dtype)


@torch.inference_mode()
def block(pool, streams, frames, vlm, project, denoise, common, head, state, embodiment, samples, warmup, concurrent):
    stream_vlm, stream_ae = streams
    ids, valid, _, indices = common
    seed_start, seed_middle, seed_done = event(), event(), event()
    with torch.cuda.stream(stream_vlm):
        seed_start.record()
        seed_embedding = vlm(ids, valid, frames[0], indices)
        seed_middle.record()
        seed_tensors = project(seed_embedding)
        seed_done.record()
    seed_done.synchronize()
    seed = Cache(0, 0, seed_tensors, seed_start, seed_middle, seed_done)
    origin = event()
    origin.record()
    origin.synchronize()
    count = warmup + samples + 1
    records, actions, selections = [], [], []
    lock, stop = Lock(), Event()
    launch = Barrier(2) if concurrent else None
    latest = seed

    @torch.inference_mode()
    def produce():
        nonlocal latest
        with torch.cuda.stream(stream_vlm):
            stream_vlm.wait_event(origin)
            launch.wait(timeout=60)
            version = 0
            while not stop.is_set():
                version += 1
                frame = version % len(frames)
                begin, middle, end = event(), event(), event()
                begin.record()
                embedding = vlm(ids, valid, frames[frame], indices)
                middle.record()
                tensors = project(embedding)
                end.record()
                cache = Cache(version, frame, tensors, begin, middle, end)
                with lock:
                    records.append(cache)
                end.synchronize()
                with lock:
                    latest = cache

    @torch.inference_mode()
    def consume():
        nonlocal latest
        with torch.cuda.stream(stream_ae):
            stream_ae.wait_event(origin)
            if launch is not None:
                launch.wait(timeout=60)
            for index in range(count):
                begin, end = event(), event()
                with lock:
                    # Query the submitted frame too, so a delayed producer-thread
                    # publication cannot hide an already completed GPU cache.
                    submitted_done = bool(records) and records[-1].done.query()
                    if submitted_done:
                        latest = records[-1]
                    chosen = latest
                    assert chosen.done.query()
                    observed = records[-1].version if submitted_done else chosen.version
                    assert chosen.version == observed
                    selected_ns = perf_counter_ns()
                    begin.record()
                for tensor in chosen.tensors:
                    tensor.record_stream(stream_ae)
                noise = new_noise(head, state)
                output = denoise(chosen.tensors, state, embodiment, noise)
                end.record()
                # No queued next chunk: select the cache again only after this
                # inference finishes. Keep its input cache and output alive.
                end.synchronize()
                actions.append((begin, end, chosen, output))
                selections.append(dict(index=index, cache_version=chosen.version, frame=chosen.frame,
                                       latest_observed_completed=observed, selected_cpu_ns=selected_ns))
            return output

    producer = pool.submit(produce) if concurrent else None
    consumer = pool.submit(consume)
    try:
        output = consumer.result(timeout=600)
    finally:
        stop.set()
        if producer is not None:
            producer.result(timeout=600)
    if not torch.isfinite(output).all():
        raise ValueError("nonfinite concurrent action output")

    all_caches = [seed, *records]
    seed_relative = -seed.done.elapsed_time(origin)
    completed = {c.version: origin.elapsed_time(c.done) if c.version else seed_relative for c in all_caches}
    launches = []
    for i, (start, finish, cache, _) in enumerate(actions):
        begin, end = origin.elapsed_time(start), origin.elapsed_time(finish)
        latest_device = max(c.version for c in all_caches if completed[c.version] <= begin)
        launches.append(dict(selections[i], start_ms=begin, end_ms=end, latency_ms=start.elapsed_time(finish),
                             cache_done_ms=completed[cache.version], cache_age_ms=cache.done.elapsed_time(start),
                             latest_completed_at_gpu_start=latest_device,
                             gpu_start_race=cache.version != latest_device))
    measured = launches[warmup + 1:]
    begin_window, end_window = launches[warmup]["end_ms"], launches[-1]["end_ms"]
    periods = [launches[i]["end_ms"] - launches[i - 1]["end_ms"] for i in range(warmup + 1, count)]
    idle = [launches[i]["start_ms"] - launches[i - 1]["end_ms"] for i in range(warmup + 1, count)]
    refreshes = [dict(version=c.version, frame=c.frame, start_ms=origin.elapsed_time(c.start),
                      vlm_done_ms=origin.elapsed_time(c.vlm_done), end_ms=completed[c.version],
                      vlm_ms=c.start.elapsed_time(c.vlm_done), projection_ms=c.vlm_done.elapsed_time(c.done),
                      refresh_ms=c.start.elapsed_time(c.done)) for c in records]
    in_window = [v for v in refreshes if begin_window < v["end_ms"] <= end_window]
    versions = [v["cache_version"] for v in measured]
    assert len(periods) == samples and versions == sorted(versions)
    assert min(periods) > 0 and min(idle) >= -0.002
    assert (len(set(versions)) > 1) == concurrent
    assert bool(in_window) == concurrent
    return dict(period_ms=periods, ae_latency_ms=[v["latency_ms"] for v in measured], ae_idle_ms=idle,
                cache_age_ms=[v["cache_age_ms"] for v in measured], cache_versions=versions,
                cache_reused=sum(a == b for a, b in zip(versions, [launches[warmup]["cache_version"], *versions[:-1]])),
                gpu_start_races=sum(v["gpu_start_race"] for v in measured), latest_observed_checks_passed=True,
                window_start_ms=begin_window, window_end_ms=end_window, elapsed_ms=end_window - begin_window,
                vlm_refreshes=len(in_window), vlm_latency_ms=[v["vlm_ms"] for v in in_window],
                projection_latency_ms=[v["projection_ms"] for v in in_window],
                refresh_latency_ms=[v["refresh_ms"] for v in in_window],
                ae_launches=launches, producer_refreshes=refreshes)


def summarize(blocks):
    result = {}
    for condition, runs in blocks.items():
        collect = lambda key: [value for run in runs for value in run[key]]
        periods = stats(collect("period_ms"))
        elapsed = sum(run["elapsed_ms"] for run in runs)
        refreshes = sum(run["vlm_refreshes"] for run in runs)
        result[condition] = dict(ae_chunk_hz=1000 * periods["n"] / elapsed,
                                 vlm_refresh_hz=1000 * refreshes / elapsed,
                                 period_ms=periods, ae_latency_ms=stats(collect("ae_latency_ms")),
                                 ae_idle_ms=stats(collect("ae_idle_ms")),
                                 cache_age_ms=stats(collect("cache_age_ms")),
                                 vlm_latency_ms=stats(collect("vlm_latency_ms")),
                                 projection_latency_ms=stats(collect("projection_latency_ms")),
                                 refresh_latency_ms=stats(collect("refresh_latency_ms")),
                                 cache_reuse_fraction=sum(run["cache_reused"] for run in runs) / periods["n"],
                                 gpu_start_races=sum(run["gpu_start_races"] for run in runs), blocks=runs)
    return result


@torch.inference_mode()
def run(args):
    torch.set_num_interop_threads(1)
    config, vlm, inputs, image_mask, fixture = setup(args)
    shapes = []
    def observe(module, positional, keywords):
        values = keywords["pixel_values"] if "pixel_values" in keywords else positional[0]
        shapes.extend(list(value.shape) for value in values)
    with vlm.vision_model.register_forward_pre_hook(observe, with_kwargs=True):
        embedding = vlm(*inputs)
    if shapes != [[1, 3, 252, 336]] * 3 or fixture["vl_tokens"] != 371:
        raise ValueError(f"unexpected 640x480 fixture: {shapes}, {fixture}")
    from gr00t.model.gr00t_n1d6.gr00t_n1d6 import Gr00tN1d6ActionHead
    with no_init_weights():
        head = Gr00tN1d6ActionHead(config)
    head = load_weights(head, args.checkpoint, "action_head.")
    if head.num_inference_timesteps != 4:
        raise ValueError("expected four denoising steps")
    project, denoise = make_cached_head(head, image_mask, inputs[1])
    state = embedding.new_zeros((1, SPEC.state_tokens, config.max_state_dim))
    embodiment = torch.tensor([2], device="cuda")
    cache = project(embedding)
    expected = [1, SPEC.heads, fixture["vl_tokens"], SPEC.head_dim]
    if len(cache) != 32 or any(list(t.shape) != expected for t in cache):
        raise ValueError("expected K and V for sixteen cross-attention layers")
    torch.manual_seed(31)
    noise = new_noise(head, state)
    torch.manual_seed(31)
    official = head.get_action(BatchFeature(dict(backbone_features=embedding,
                              backbone_attention_mask=inputs[1], image_mask=image_mask)),
                              BatchFeature(dict(state=state, embodiment_id=embodiment))).action_pred
    cached = denoise(cache, state, embodiment, noise)
    torch.testing.assert_close(cached, official, rtol=0.012, atol=0.0039)
    cache_comparison = compare_embedding(official, cached)
    print("Cached head vs official eager", cache_comparison, flush=True)
    frames = [inputs[2], [p.flip(-1).contiguous() for p in inputs[2]],
              [p.roll(8, -1).contiguous() for p in inputs[2]],
              [p.flip(-2).contiguous() for p in inputs[2]]]
    changed = project(vlm(inputs[0], inputs[1], frames[1], inputs[3]))
    if torch.equal(changed[0], cache[0]):
        raise ValueError("frame bank did not change actual cache contents")
    report = dict(fixture, started_at_utc=datetime.now(timezone.utc).isoformat(),
                  vit_input_shapes=shapes, cache_shapes=[list(t.shape) for t in cache],
                  kv_bytes=sum(t.numel() * t.element_size() for t in cache),
                  cache_semantics="VLM -> VL LayerNorm -> 16 per-layer K/V projections; publish only on completion; one snapshot per full AE chunk",
                  ae_scope="State/action encoding, 4 x 32-layer DiT using cached cross K/V, decoder, fresh noise per inference",
                  frame_policy="Four device-resident frames: original, horizontal flip, 8-pixel horizontal roll, vertical flip after preprocessing",
                  dispatch_policy="Two Python worker threads, equal-priority CUDA streams, one in-flight operation per stream; no next AE prequeue",
                  cache_correctness=cache_comparison, cache_values_change_with_frame=True,
                  source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in (Path(__file__), Path(__file__).with_name("capture_gr00t_thor.py"))},
                  modes={}, profiling_warning="CUPTI overlap traces are separate from reported unprofiled latency/throughput")
    write(args.output / "dual-stream-summary.json", report)
    for backend in args.backends:
        funcs = (vlm, project, denoise) if backend == "eager" else (
            torch.compile(vlm, dynamic=False, options=OPTIONS),
            torch.compile(project, fullgraph=True, dynamic=False, options=OPTIONS),
            torch.compile(denoise, fullgraph=True, dynamic=False, options=OPTIONS))
        forward, build, action = funcs
        print("Preparing", backend, flush=True)
        ref_cache = build(forward(*inputs))
        result = action(ref_cache, state, embodiment, noise)
        if not torch.isfinite(result).all():
            raise ValueError("nonfinite prepared action")
        comparison = compare_embedding(cached, result)
        for _ in range(args.warmup):
            ref_cache = build(forward(*inputs))
            action(ref_cache, state, embodiment, noise)
        torch.cuda.synchronize()
        solo_vlm, solo_projection, solo_refresh = [], [], []
        for _ in range(args.solo_samples):
            a, b, c = event(), event(), event()
            a.record(); v = forward(*inputs); b.record(); ref_cache = build(v); c.record(); c.synchronize()
            solo_vlm.append(a.elapsed_time(b)); solo_projection.append(b.elapsed_time(c)); solo_refresh.append(a.elapsed_time(c))
        streams = torch.cuda.Stream(), torch.cuda.Stream()
        order = ("ae_only", "with_vlm", "with_vlm", "ae_only")
        blocks = {"ae_only": [], "with_vlm": []}
        with ThreadPoolExecutor(max_workers=2) as pool:
            block(pool, streams, frames, forward, build, action, inputs, head, state, embodiment, 4, 4, True)
            graphs = counters["stats"]["unique_graphs"]
            for condition in order:
                print(backend, condition, "samples", args.block_samples, flush=True)
                value = block(pool, streams, frames, forward, build, action, inputs, head, state, embodiment,
                              args.block_samples, args.warmup, condition == "with_vlm")
                blocks[condition].append(value)
            if counters["stats"]["unique_graphs"] != graphs:
                raise ValueError("recompilation occurred in timed blocks")
            trace_block = None
            if args.trace:
                with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CUDA]) as profiler:
                    trace_block = block(pool, streams, frames, forward, build, action, inputs, head, state, embodiment, 6, 3, True)
                profiler.export_chrome_trace(str(args.output / f"dual-{backend}.trace.json"))
        result = dict(results=summarize(blocks), solo_vlm_ms=stats(solo_vlm),
                      solo_projection_ms=stats(solo_projection), solo_refresh_ms=stats(solo_refresh),
                      eager_cached_comparison=comparison, compiled_graphs=graphs,
                      no_recompilation_in_timing=True, block_order=order,
                      stream_handles=dict(vlm=streams[0].cuda_stream, ae=streams[1].cuda_stream),
                      trace_block=trace_block)
        report["modes"][backend] = result
        write(args.output / "dual-stream-summary.json", report)
        for name, row in result["results"].items():
            print(backend, name, "AE Hz", row["ae_chunk_hz"], "AE p50 ms", row["ae_latency_ms"]["p50"],
                  "VLM refresh Hz", row["vlm_refresh_hz"], "GPU-start races", row["gpu_start_races"], flush=True)
    report["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    write(args.output / "dual-stream-summary.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backends", nargs="+", choices=("eager", "compile"), default=("eager", "compile"))
    parser.add_argument("--block-samples", type=int, default=40)
    parser.add_argument("--solo-samples", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=6)
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--prompt", default="Pick up the object and place it on the table.")
    args = parser.parse_args()
    if min(args.block_samples, args.solo_samples, args.warmup) < 2:
        parser.error("sample and warmup counts must be >= 2")
    args.image_size, args.image_width, args.image_height = 448, 640, 480
    args.default_image_preprocess, args.expected_vit_size, args.cameras = True, (336, 252), 3
    args.mode = "dual-stream"
    args.output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(args.source))
    run(args)

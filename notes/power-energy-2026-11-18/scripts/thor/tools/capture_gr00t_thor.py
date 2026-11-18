"""Measure GR00T N1.6 H=15 with its released checkpoint on NVIDIA Thor."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import shutil
import statistics
import sys
from time import perf_counter

import numpy as np
import torch
from PIL import Image
from safetensors import safe_open
from transformers import AutoConfig, AutoModel, AutoProcessor
from transformers.feature_extraction_utils import BatchFeature
from transformers.modeling_utils import no_init_weights

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workloads.models import GR00T_N16_H15 as SPEC

OPTIONS = dict(max_autotune=True, **{"triton.cudagraphs": False, "triton.unique_kernel_names": True,
                                   "emulate_precision_casts": True})
CHECKPOINT_REV = "d0814e7ecb19202e7c8468b46098b0b7ef3a6d61"
SOURCE_REV = "9b37aa1ce69c73c6d165233fa88128283bba4508"


def eagle_sdpa_source(source, output):
    """Retain packed per-image attention boundaries using a block diagonal mask."""
    target = output / "eagle_sdpa"
    shutil.copytree(source, target, dirs_exist_ok=True)
    eagle = target / "modeling_eagle3_vl.py"
    eagle.write_text(eagle.read_text().replace('"flash_attention_2"', '"sdpa"'))
    siglip = target / "modeling_siglip2.py"
    old = "        attention_mask = None\n        attn_output, attn_weights = attention_interface("
    new = """        attention_mask = None
        if self.config._attn_implementation == "sdpa" and len(seq_len_list) > 1:
            owners = torch.tensor([i for i, n in enumerate(seq_len_list) for _ in range(n)],
                                  device=queries.device)
            attention_mask = (owners[:, None] == owners[None, :])[None, None]
        attn_output, attn_weights = attention_interface("""
    original = siglip.read_text()
    if original.count(old) != 1:
        raise ValueError("pinned SigLIP source changed")
    siglip.write_text(original.replace(old, new))
    cfg = target / "config.json"
    data = json.loads(cfg.read_text())
    data["_attn_implementation"] = "sdpa"
    cfg.write_text(json.dumps(data))
    return target


def load_weights(module, checkpoint, prefix):
    index = json.loads((checkpoint / "model.safetensors.index.json").read_text())["weight_map"]
    expected = set(module.state_dict())
    files = defaultdict(list)
    for name in expected:
        if prefix + name in index:
            files[index[prefix + name]].append(name)
    state = {}
    for filename, names in files.items():
        with safe_open(checkpoint / filename, framework="pt") as handle:
            for name in names:
                state[name] = handle.get_tensor(prefix + name)
    if "language_model.lm_head.weight" in expected and "language_model.lm_head.weight" not in state:
        state["language_model.lm_head.weight"] = state["language_model.model.embed_tokens.weight"]
    module.load_state_dict(state, strict=True, assign=True)
    return module.to(device="cuda", dtype=torch.bfloat16).eval()


def setup(args):
    from gr00t.configs.model.gr00t_n1d6 import Gr00tN1d6Config

    if torch.cuda.get_device_name() != "NVIDIA Thor":
        raise RuntimeError("This capture requires NVIDIA Thor")
    torch.manual_seed(17)
    torch.set_num_threads(1)
    vpath = args.source / "gr00t/model/modules/nvidia/Eagle-Block2A-2B-v2"
    eagle_path = eagle_sdpa_source(vpath, args.output)
    cfg = Gr00tN1d6Config.from_pretrained(args.checkpoint, local_files_only=True)
    cfg.action_horizon = SPEC.horizon
    ecfg = AutoConfig.from_pretrained(eagle_path, trust_remote_code=True)
    ecfg.text_config.num_hidden_layers = cfg.select_layer
    with no_init_weights():
        eagle = AutoModel.from_config(ecfg, trust_remote_code=True, torch_dtype=torch.bfloat16,
                                      attn_implementation="sdpa")
    if args.mode != "fixture":
        load_weights(eagle, args.checkpoint, "backbone.model.")
    processor = AutoProcessor.from_pretrained(eagle_path, trust_remote_code=True)
    generator = torch.Generator().manual_seed(17)
    image_size = getattr(args, "image_size", 256)
    image_width = getattr(args, "image_width", None) or image_size
    image_height = getattr(args, "image_height", None) or image_size
    images = [Image.fromarray(torch.randint(0, 256, (image_height, image_width, 3), generator=generator,
                                            dtype=torch.uint8).numpy()) for _ in range(args.cameras)]
    preprocessing = dict(kind="Eagle alignment only")
    if getattr(args, "default_image_preprocess", False):
        from gr00t.model.gr00t_n1d6.image_augmentations import build_image_transformations_albumentations

        settings = json.loads((args.checkpoint / "processor_config.json").read_text())["processor_kwargs"]
        if not settings["use_albumentations"]:
            raise ValueError("checkpoint does not select the expected image preprocessing pipeline")
        _, transform = build_image_transformations_albumentations(
            settings["image_target_size"], settings["image_crop_size"], settings["random_rotation_angle"],
            settings["color_jitter_params"], settings["shortest_image_edge"], settings["crop_fraction"],
        )
        stage_image = np.asarray(images[0])
        stages = []
        for stage in transform.transforms:
            stage_image = stage(image=stage_image)["image"]
            stages.append(dict(name=type(stage).__name__, size_wh=[stage_image.shape[1], stage_image.shape[0]]))
        transformed = [transform(image=np.asarray(image))["image"] for image in images]
        if not np.array_equal(transformed[0], stage_image):
            raise ValueError("recorded preprocessing stages differ from the checkpoint evaluation transform")
        images = [Image.fromarray(image) for image in transformed]
        preprocessing = dict(kind="Checkpoint evaluation image transform followed by Eagle alignment",
                             shortest_image_edge=settings["shortest_image_edge"],
                             crop_fraction=settings["crop_fraction"], stages=stages,
                             output_sizes_wh=[[image.width, image.height] for image in images])
    conversation = [{"role": "user", "content": [{"type": "text", "text": args.prompt},
                    *[{"type": "image", "image": image} for image in images]]}]
    prompt = processor.apply_chat_template(conversation, tokenize=False, add_generation_prompt=False)
    pixels, _ = processor.process_vision_info([conversation])
    processed_image_sizes = [[image.height, image.width] for image in pixels]
    inputs = processor(text=[prompt], images=pixels, return_tensors="pt", padding=True)
    ids = inputs["input_ids"].cuda()
    valid = inputs["attention_mask"].cuda().bool()
    pixels = [p.to(device="cuda", dtype=torch.bfloat16) for p in inputs["pixel_values"]]
    vit_input_shapes = [list(p.shape) for p in pixels]
    expected_vit_size = getattr(args, "expected_vit_size", None)
    if expected_vit_size:
        width, height = expected_vit_size
        if any(shape[-2:] != [height, width] for shape in vit_input_shapes):
            raise ValueError(f"ViT inputs differ from the requested {width}x{height}: {vit_input_shapes}")
    image_mask = ids == ecfg.image_token_index
    image_indices = image_mask.flatten().nonzero().flatten()

    def vlm(ids, mask, pixel_values, indices):
        visual = eagle.extract_feature(pixel_values)
        embeds = eagle.language_model.get_input_embeddings()(ids)
        embeds = embeds.flatten(0, 1).index_copy(0, indices, visual).reshape_as(embeds)
        return eagle.language_model(inputs_embeds=embeds, attention_mask=mask, use_cache=False,
                                    output_hidden_states=True).hidden_states[-1]

    vlm.vision_model = eagle.vision_model
    inputs = ids, valid, pixels, image_indices
    fixture = dict(model=SPEC.name, horizon=SPEC.horizon, queries=SPEC.queries, cameras=args.cameras,
                   image_size=[image_height, image_width], image_size_order="height,width",
                   preprocessing=preprocessing, processed_image_sizes=processed_image_sizes,
                   vit_input_shapes=vit_input_shapes,
                   seed=17, prompt=args.prompt, torch=torch.__version__,
                   gpu=torch.cuda.get_device_name(), compile_options=OPTIONS, attention="packed SDPA",
                   checkpoint_revision=CHECKPOINT_REV, source_revision=SOURCE_REV,
                   vl_tokens=ids.shape[1], image_tokens=int((image_mask & valid).sum()),
                   text_tokens=int((~image_mask & valid).sum()))
    return cfg, vlm, inputs, image_mask, fixture


def latency(fn, inputs, count):
    events, wall = [], []
    begin, end = (torch.cuda.Event(enable_timing=True) for _ in range(2))
    torch.cuda.synchronize()
    for _ in range(count):
        t = perf_counter()
        begin.record()
        fn(*inputs)
        end.record()
        end.synchronize()
        wall.append(1000 * (perf_counter() - t))
        events.append(begin.elapsed_time(end))
    return {k: dict(mean=statistics.mean(v), p50=statistics.median(v), samples=v)
            for k, v in (("cuda_ms", events), ("wall_ms", wall))}


def write(path, record):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n")
    temporary.replace(path)


def compare_embedding(reference, result):
    if reference.shape != result.shape or reference.dtype != result.dtype:
        raise ValueError("compiled and eager Eagle returned different tensor types")
    reference, result = reference.float(), result.float()
    error = result - reference
    if not torch.isfinite(error).all():
        raise ValueError("nonfinite compiled Eagle results")
    norms = reference.norm(dim=-1).clamp_min(1e-12)
    per_token = error.norm(dim=-1) / norms
    return dict(relative_rms=float(error.norm() / reference.norm()),
                per_token_relative_error_p95=float(per_token.quantile(0.95)),
                max_abs=float(error.abs().max()), reference_max_abs=float(reference.abs().max()))


def measure_ae(args, config, embedding, mask, image_mask, fixture):
    from gr00t.model.gr00t_n1d6.gr00t_n1d6 import Gr00tN1d6ActionHead

    # The official constructor creates a Beta distribution on CPU.
    with no_init_weights():
        head = Gr00tN1d6ActionHead(config)
    head = load_weights(head, args.checkpoint, "action_head.")
    dit = head.model
    state = embedding.new_zeros((1, SPEC.state_tokens, config.max_state_dim))
    embodiment = torch.tensor([2], device="cuda")
    gt = tuple("self" if block.attn1.to_k.in_features == SPEC.hidden else "cross"
               for block in dit.transformer_blocks)
    if gt != SPEC.layer_kinds:
        raise ValueError("loaded DiT layer order differs from the simulator contract")
    for block in dit.transformer_blocks:
        if tuple(block.ff.net[0].proj.weight.shape) != (SPEC.ffn, SPEC.hidden):
            raise ValueError("checkpoint FFN differs from the simulator contract")

    def action(v, state, embodiment, mask, image_mask):
        backbone = BatchFeature(dict(backbone_features=v, image_mask=image_mask, backbone_attention_mask=mask))
        return head.get_action(backbone, BatchFeature(dict(state=state, embodiment_id=embodiment))).action_pred

    inputs = embedding, state, embodiment, mask, image_mask
    shapes = []

    def record_queries(module, args, kwargs):
        value = kwargs["hidden_states"] if "hidden_states" in kwargs else args[0]
        shapes.append(tuple(value.shape))

    with dit.transformer_blocks[0].register_forward_pre_hook(record_queries, with_kwargs=True):
        eager_result = action(*inputs)
    if shapes != [(1, SPEC.queries, SPEC.hidden)] * SPEC.steps or not torch.isfinite(eager_result).all():
        raise ValueError(f"expected {SPEC.steps} DiT calls with H=15 and one state token, got {shapes}")
    call = torch.compile(action, dynamic=False, options=OPTIONS)
    print("Compiling full H=15 action head", flush=True)
    result = call(*inputs)
    if result.shape != (1, SPEC.horizon, config.max_action_dim) or not torch.isfinite(result).all():
        raise ValueError("unexpected H=15 result")
    for _ in range(4):
        call(*inputs)
    full = latency(call, inputs, args.samples)
    write(args.output / "ae-latency.json", dict(fixture, **full, layer_kinds=gt,
                                                dit_query_shapes=shapes, embodiment_id=2))
    print("Compiled H=15 AE CUDA p50", full["cuda_ms"]["p50"], flush=True)
    return head, state, embodiment


@torch.inference_mode()
def run(args):
    config, vlm, inputs, image_mask, fixture = setup(args)
    print("VLM fixture", fixture, flush=True)
    if args.mode == "fixture":
        write(args.output / "fixture.json", fixture)
        return
    if args.mode == "ae":
        embedding = vlm(*inputs)
        if embedding.shape != (1, fixture["vl_tokens"], SPEC.backbone_width):
            raise ValueError("unexpected VLM shape")
        head, state, embodiment = measure_ae(args, config, embedding, inputs[1], image_mask, fixture)
        from capture_gr00t_ae import ledger
        write(args.output / "ae-ledger.json", ledger(head, embedding, state, embodiment, inputs[1],
                                                    image_mask, fixture, OPTIONS, args.samples))
        return
    compiled = torch.compile(vlm, dynamic=False, options=OPTIONS)
    print("Compiling Eagle VLM", flush=True)
    result = compiled(*inputs)
    if args.mode == "trace":
        validation = compare_embedding(vlm(*inputs), result)
        print("Eagle eager/compile comparison", validation, flush=True)
        fixture["eager_compile_comparison"] = validation
    for _ in range(4):
        compiled(*inputs)
    torch.cuda.synchronize()
    if args.mode == "counter":
        torch.cuda.cudart().cudaProfilerStart()
        compiled(*inputs)
        torch.cuda.synchronize()
        torch.cuda.cudart().cudaProfilerStop()
        return
    profile = latency(compiled, inputs, args.samples)
    fixture.update(phase="GR00T N1.6 Eagle vision + 16 Qwen3 layers",
                   gpu_ms={"compile": profile["cuda_ms"]}, wall_ms=profile["wall_ms"])
    write(args.output / "capture-summary.json", fixture)
    print("Compiled VLM CUDA p50", profile["cuda_ms"]["p50"], flush=True)
    for i in range(5):
        with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU,
                                                torch.profiler.ProfilerActivity.CUDA]) as prof:
            compiled(*inputs)
            torch.cuda.synchronize()
        prof.export_chrome_trace(str(args.output / f"compiled-prefix-{i}.json"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("fixture", "trace", "counter", "ae"), required=True)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--cameras", type=int, default=3)
    parser.add_argument("--image-size", type=int, default=256)
    parser.add_argument("--image-width", type=int)
    parser.add_argument("--image-height", type=int)
    parser.add_argument("--default-image-preprocess", action="store_true")
    parser.add_argument("--expected-vit-size", type=int, nargs=2, metavar=("WIDTH", "HEIGHT"))
    parser.add_argument("--prompt", default="Pick up the object and place it on the table.")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.source))
    run(args)

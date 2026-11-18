"""Model geometry shared by program generation and measured schedules."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    name: str
    layers: int
    steps: int
    horizon: int
    state_tokens: int
    heads: int
    head_dim: int
    hidden: int
    ffn: int
    ffn_gated: bool
    rope: bool
    layer_kinds: tuple[str, ...]
    backbone_width: int

    @property
    def queries(self):
        return self.horizon + self.state_tokens

    def kv_shape(self, kind, vl_tokens=None):
        if kind not in self.layer_kinds:
            raise ValueError(f"{self.name} has no {kind!r} layer")
        if kind == "decoder":
            return 968 + self.queries, 992
        if kind == "self":
            return self.queries, self.queries
        if type(vl_tokens) is not int or vl_tokens < 1:
            raise ValueError("GR00T cross attention requires the captured VLM sequence length")
        return vl_tokens, (vl_tokens + 15) // 16 * 16


PI05 = ModelSpec("pi05", 18, 10, 16, 0, 8, 256, 1024, 4096, True, True, ("decoder",) * 18, 0)
GR00T_N16_H15 = ModelSpec(
    "gr00t_n16", 32, 4, 15, 1, 32, 48, 1536, 6144, False, False, ("cross", "self") * 16, 2048
)
MODELS = {spec.name: spec for spec in (PI05, GR00T_N16_H15)}


def get(name="pi05"):
    try:
        return MODELS[name]
    except KeyError:
        raise ValueError(f"unknown workload model {name!r}") from None

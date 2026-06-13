"""Parse a ``patterns.config`` programme into per-code space requirements.

Only the ``spaces:`` section is read here. Generic codes (c/o/s) carry no
explicit targets and are left unconstrained by the solver (they absorb slack).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml

# Urb::Dom::Fitness defaults for optional params (ProgrammeDriven.default_params).
_DEFAULT_WIDTH = (4.0, 1.0)
_DEFAULT_PROPORTION = (1.5, 0.5)


@dataclass
class SpaceReq:
    code: str
    name: str = ""
    size: float = 0.0  # target floor area, m^2
    size_sigma: float = 1.0
    width: float = _DEFAULT_WIDTH[0]
    width_sigma: float = _DEFAULT_WIDTH[1]
    proportion: float = _DEFAULT_PROPORTION[0]  # max length/width ratio
    proportion_sigma: float = _DEFAULT_PROPORTION[1]
    adjacency: list[str] = field(default_factory=list)
    level: int | None = None
    requires_below: str | None = None
    count: int = 1
    # Whether each quality param was explicitly in the config (not a default)
    has_size: bool = False
    has_width: bool = False
    has_proportion: bool = False


def _pair(d: dict, key: str, default: tuple[float, float]) -> tuple[float, float]:
    v = d.get(key)
    if v is None:
        return default
    return float(v[0]), float(v[1])


def load_programme(path: str) -> dict[str, SpaceReq]:
    with open(path) as fh:
        conf = yaml.safe_load(fh)
    spaces = conf.get("spaces") or {}
    out: dict[str, SpaceReq] = {}
    for code, c in spaces.items():
        size = _pair(c, "size", (0.0, 1.0))
        width = _pair(c, "width", _DEFAULT_WIDTH)
        prop = _pair(c, "proportion", _DEFAULT_PROPORTION)
        out[code] = SpaceReq(
            code=code,
            name=c.get("name", ""),
            size=size[0],
            size_sigma=size[1],
            width=width[0],
            width_sigma=width[1],
            proportion=prop[0],
            proportion_sigma=prop[1],
            adjacency=list(c.get("adjacency") or []),
            level=c.get("level"),
            requires_below=c.get("requires_below"),
            count=int(c.get("count") or 1),
            has_size="size" in c,
            has_width="width" in c,
            has_proportion="proportion" in c,
        )
    return out

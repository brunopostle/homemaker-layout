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


def _parse_spaces(conf: dict) -> dict[str, SpaceReq]:
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


def load_programme(path: str) -> dict[str, SpaceReq]:
    with open(path) as fh:
        conf = yaml.safe_load(fh)
    return _parse_spaces(conf)


def n_storeys_required(reqs: dict[str, SpaceReq]) -> int:
    """Number of storeys the programme implies, from the highest ``level:`` key.

    Level-free rooms (no ``level``) do not force extra storeys — they are
    distributed across whatever storeys the level-constrained rooms require.
    """
    levels = [r.level for r in reqs.values() if r.level is not None]
    return (max(levels) + 1) if levels else 1


def partition_rooms_by_storey(
    reqs: dict[str, SpaceReq], n_storeys: int, rng,
) -> list[dict[str, int]]:
    """Per-storey required-room multisets (DESIGN.md §11.3 staging).

    Level-constrained rooms land on their required storey; level-free rooms are
    distributed round-robin over a shuffled order across all storeys. Generic
    circulation/outside/sahn codes are excluded (they are added per storey at
    construction time). Mirrors the inline partition in
    ``operators.constructive_topology`` so Stage 1 (base) and Stage 2 (upper
    deltas) draw from one consistent partition.

    Returns a list of length ``n_storeys``; each entry maps room code -> count.
    """
    buckets: list[dict[str, int]] = [{} for _ in range(n_storeys)]

    def _add(li: int, code: str) -> None:
        buckets[li][code] = buckets[li].get(code, 0) + 1

    free: list[str] = []
    for code, req in reqs.items():
        if code[0].lower() in ("c", "o", "s"):
            continue
        for _ in range(req.count):
            if req.level is not None and req.level < n_storeys:
                _add(req.level, code)
            else:
                free.append(code)
    free = [free[i] for i in rng.permutation(len(free))]
    for i, code in enumerate(free):
        _add(i % n_storeys, code)
    return buckets


def write_stage1_programme(
    full_dir: str | Path, out_dir: str | Path, base_codes: dict[str, int],
) -> Path:
    """Derive a single-storey base-floor programme (DESIGN.md §11.3 Stage 1).

    Filters the full merged ``patterns.config`` down to the rooms assigned to the
    base floor (``base_codes``: code -> count), drops their ``level:`` keys,
    prunes each kept space's ``adjacency`` to references that survive (retained
    codes or generic c/o/s), and forces single-storey building constraints. The
    result is written as a *self-contained* ``patterns.config`` in ``out_dir`` so
    ``fitness.load_config``'s parent-dir merge contributes nothing — keep
    ``out_dir`` outside the corpus tree (e.g. a tempdir).

    Returns ``out_dir`` as a ``Path``.
    """
    from pathlib import Path as _Path

    from . import fitness as _fit

    out_dir = _Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    conf, _cost = _fit.load_config(full_dir)

    keep = set(base_codes)
    src_spaces = conf.get("spaces") or {}
    new_spaces: dict = {}
    for code, count in base_codes.items():
        if code not in src_spaces:
            continue
        spec = dict(src_spaces[code])
        spec.pop("level", None)
        spec["count"] = count
        adj = spec.get("adjacency")
        if adj is not None:
            spec["adjacency"] = [
                r for r in adj if r in keep or r[0].lower() in ("c", "o", "s")
            ]
        new_spaces[code] = spec

    new_conf = {k: v for k, v in conf.items() if k != "spaces"}
    new_conf["spaces"] = new_spaces
    new_conf.update(
        storey_minimum=1, storey_limit=1, staircase_min=1, staircase_max=1,
    )

    with open(out_dir / "patterns.config", "w") as fh:
        yaml.safe_dump(new_conf, fh, sort_keys=False, default_flow_style=False)
    return out_dir


def load_programme_dir(directory: str | Path) -> dict[str, SpaceReq]:
    """Load programme from a directory, merging parent patterns.config as base.

    Mirrors urb-evolve.pl: ../patterns.config loaded first, then the local
    file's top-level keys override it (same shallow-merge as fitness.load_config).
    """
    from pathlib import Path as _Path
    directory = _Path(directory)
    conf: dict = {}
    for p in (directory.parent / "patterns.config", directory / "patterns.config"):
        if p.is_file():
            with open(p) as fh:
                conf.update(yaml.safe_load(fh) or {})
    return _parse_spaces(conf)

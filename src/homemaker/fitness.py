"""Native port of Urb's programme-driven fitness: leaf quality terms + cost model.

Scope (homemaker-py-gnw): per-leaf quality factors (perpendicular, proportion,
size, width, crinkliness, daylight, access), the programme-driven parameter
lookup chain (``get_space_params``), value rates, and the cost denominator
(per-leaf area costs, interior/exterior wall edge costs, boundary costs).
Storey/building checks, staircases, failure stacking and final assembly are
homemaker-py-hgg; corpus-parity validation is homemaker-py-uxz.

Source of truth: ``Urb::Dom::Fitness::{Base,Leaf,Storey,ProgrammeDriven}``.

DESCOPE (DESIGN.md §6, decision 2026-06-12): this ports *simple* crinkliness —
the CIEsky illumination factor is pinned to 1, exactly what Urb computes under
``URB_NO_OCCLUSION=1``.  ``quality_daylight`` is likewise pinned to 1.  Parity
targets the *flagged* oracle, never stock Urb.

Call ``dom.merge_divided(root)`` and rebuild graphs before ``process_storey``
— storey processing runs on the MERGED tree (two-phase pattern, see graph.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx
import yaml

from . import dom as dom_mod
from . import geometry
from .dom import Node

FAIL_THRESHOLD = 0.1  # Urb::Dom::Fitness::Base

# Urb::Dom::Fitness::Base $CONF — keep values byte-identical to the Perl
# expressions (5.0/6 etc. evaluate to the same IEEE doubles in both languages).
CONF_DEFAULTS: dict = {
    "value_inside": 300.0,
    "value_circulation": 50.0,
    "value_outside": 100.0,
    "value_supported": 300.0,
    "storey_limit": 4,
    "storey_minimum": 2,
    "latitude": 53.3814,
    "door_width": 1.2,
    "plot_ratio": [2.00, 0.50],
    "ratio_outside": [0.33, 0.15],
    "ratio_circulation": [0.00, 0.20],
    "uncrinkliness": [5.0 / 6, 1.1 / 3],
    "uncrinkliness_circulation": [5.0 / 6, 1.1 / 3],
    "size_circulation": [0.0, 14.0],
    "size_inside": [16.0, 3.5],
    "proportion_outside": [1.5, 50],
    "proportion_circulation": [1.5, 0.5],
    "proportion_inside": [1.5, 0.5],
    "width_outside": [3.0, 0.3],
    "width_circulation": [2.4, 0.2],
    "width_inside": [4.0, 1.0],
    "perpendicular_inside": 0.3,
    "perpendicular_outside": 10.0,
    "allow_sahn_circulation": 0,
    "force_roof_garden": 1,
    "evaluate_room_types": 1,
}

# Urb::Dom::Fitness::Base $COST
COST_DEFAULTS: dict = {
    "plot": 10.0,
    "outside_covered_supported": 210.0,
    "outside_covered": 110.0,
    "outside_supported": 110.0,
    "outside": 10.0,
    "inside": 200.0,
    "interior_wall": 200.0 / 3,
    "exterior_wall": 100.0,
    "boundary": 50.0 / 3,
    "boundary_wall": 400.0 / 3,
}

# ProgrammeDriven::default_params ultimate fallbacks
_PARAM_FALLBACKS = {
    "size": [16.0, 3.5],
    "width": [4.0, 1.0],
    "proportion": [1.5, 0.5],
}

_E = 2.718281828  # Urb::Math::gaussian uses this truncated e, not math.e


def gaussian(x: float, a: float, b: float, c: float) -> float:
    """Bit-faithful port of ``Urb::Math::gaussian`` (note the truncated e)."""
    return a * (_E ** (0 - ((x - b) ** 2 / (2 * c * c))))


def load_config(directory: str | Path) -> tuple[dict, dict]:
    """Load (patterns, costs) config for a corpus directory, mirroring
    ``urb-fitness.pl``: project-level ``../<name>.config`` first, then the
    local file's keys override it."""
    directory = Path(directory)
    conf: dict = {}
    cost: dict = {}
    for target, name in ((conf, "patterns.config"), (cost, "costs.config")):
        for p in (directory.parent / name, directory / name):
            if p.is_file():
                with open(p) as fh:
                    target.update(yaml.safe_load(fh) or {})
    return conf, cost


@dataclass
class LeafEval:
    level: int
    id: str
    type: str
    area: float
    rate: float
    quality: float
    factors: dict[str, float] = field(default_factory=dict)


@dataclass
class StoreyEval:
    cost: float
    value: float
    leaves: list[LeafEval] = field(default_factory=list)


def _t0(n: Node) -> str:
    """First char of the type, lowercased ('' if untyped) — Urb's /^x/i tests."""
    return n.type[0].lower() if n.type else ""


def _height(n: Node) -> float:
    """Floor-to-floor height of n's level; mirrors ``Urb::Quad::Height``."""
    h = dom_mod._level_root(n).height
    return h if h is not None else 3.0


def _perimeter(n: Node) -> dict:
    """Perimeter dict from the lowest level root (``Urb::Quad::Perimeter``)."""
    lr = dom_mod._level_root(n)
    while lr.below is not None:
        lr = lr.below
    return lr.perimeter or {}


class Fitness:
    """Programme-driven leaf quality + cost evaluation.

    ``conf`` is the parsed patterns.config mapping (including ``spaces``);
    ``cost`` the costs.config mapping.  Lookup falls back to the Base.pm
    defaults, as ``Urb::Dom::Fitness::Base::Conf/Cost`` do.
    """

    def __init__(self, conf: dict | None = None, cost: dict | None = None):
        self._conf = conf or {}
        self._cost = cost or {}
        self.spaces: dict = self._conf.get("spaces") or {}

    def conf(self, key: str):
        v = self._conf.get(key)
        if v is not None:
            return v
        return CONF_DEFAULTS.get(key)

    def cost(self, key: str) -> float:
        v = self._cost.get(key)
        if v is not None:
            return v
        return COST_DEFAULTS.get(key, 0.0)

    def preprocess_building(self, root: Node) -> None:
        """Sahn-to-Outside type conversion (``Building.pm::preprocess_building``).
        Run BEFORE graph build and merge_divided — it changes merge outcomes."""
        if self.conf("allow_sahn_circulation"):
            return
        for lvl in dom_mod.levels(root):
            for leaf in lvl.leaves():
                if _t0(leaf) == "s":
                    leaf.type = "O"

    # ------------------------------------------------------------------ #
    # Programme-driven parameter lookup (ProgrammeDriven.pm:29-69)
    # ------------------------------------------------------------------ #

    def get_space_params(self, code: str, param: str) -> list[float]:
        c0 = code[0].lower() if code else ""
        if c0 == "c":
            v = self.conf(f"{param}_circulation")
            if v is not None:
                return v
        if c0 in ("o", "s"):
            v = self.conf(f"{param}_outside")
            if v is not None:
                return v
        sp = self.spaces.get(code)  # exact-key match, as in Perl
        if sp is not None and param in sp:
            return sp[param]
        v = self.conf(f"{param}_inside")
        if v is not None:
            return v
        return _PARAM_FALLBACKS.get(param)

    # ------------------------------------------------------------------ #
    # Quality terms (Leaf.pm)
    # ------------------------------------------------------------------ #

    def quality_perpendicular(self, leaf: Node) -> float:
        sigma = self.conf(
            "perpendicular_outside" if dom_mod.is_outside(leaf) else "perpendicular_inside"
        )
        score = 1.0
        for i in range(4):
            # 1.570796: Urb::Dom::Perpendicular hard-codes this, not pi/2
            score *= gaussian(geometry.angle(leaf, i), 1.0, 1.570796, sigma)
        return score

    def quality_proportion(self, leaf: Node) -> float:
        t0 = _t0(leaf)
        if t0 in ("o", "s"):
            params = self.conf("proportion_outside")
        elif t0 == "c":
            params = self.conf("proportion_circulation")
        else:
            params = self.get_space_params(leaf.type, "proportion")
        aspect = geometry.aspect(leaf)
        if aspect < params[0]:
            return 1.0
        return gaussian(aspect, 1.0, params[0], params[1])

    def quality_size(self, leaf: Node) -> float:
        t0 = _t0(leaf)
        if t0 in ("o", "s"):
            return 1.0
        if t0 == "c":
            params = self.conf("size_circulation")
        else:
            params = self.get_space_params(leaf.type, "size")
        return gaussian(geometry.area(leaf), 1.0, params[0], params[1])

    def quality_width(self, leaf: Node) -> float:
        t0 = _t0(leaf)
        if (
            t0 in ("o", "s")
            and not dom_mod.is_covered(leaf)
            and not dom_mod.is_supported(leaf)
            and dom_mod.level_of(leaf)
        ):
            return 1.0
        if t0 in ("o", "s"):
            params = self.conf("width_outside")
        elif t0 == "c":
            params = self.conf("width_circulation")
        else:
            params = self.get_space_params(leaf.type, "width")
        width = geometry.length_narrowest(leaf)
        if width > params[0]:
            return 1.0
        return gaussian(width, 1.0, params[0], params[1])

    # --- simple crinkliness (URB_NO_OCCLUSION: illumination factor = 1) --- #

    def area_outside(self, leaf: Node, G: nx.Graph, groups: dict) -> float:
        """Illuminated external wall area; ``Urb::Dom::Area_Outside`` with the
        CIEsky illumination factor pinned to 1 (simple crinkliness)."""
        length = 0.0
        for nb in G.neighbors(leaf):
            if not dom_mod.is_outside(nb) or dom_mod.is_covered(nb):
                continue
            # Faithful loop over all internal boundaries: Overlap() is > 0
            # only on a boundary both quads actually share an edge of.
            for contributors in groups.values():
                if geometry.boundary_pair_overlap(contributors, leaf, nb) > 0:
                    length += G[leaf][nb]["width"]
        perimeter = _perimeter(leaf)
        for e in range(4):
            bid = geometry.boundary_id(leaf, e)
            if bid not in geometry._EXTERNAL:
                continue
            ptype = (perimeter.get(bid) or "").lower()
            if ptype in ("private", "fortified"):
                continue
            length += geometry.edge_length(leaf, e)
        return length * _height(leaf)

    def crinkliness(self, leaf: Node, G: nx.Graph, groups: dict) -> float:
        area = geometry.area(leaf)
        if not area:
            return 9999999999
        return self.area_outside(leaf, G, groups) / area

    def quality_uncrinkliness(self, leaf: Node, G: nx.Graph, groups: dict) -> float:
        if dom_mod.is_outside(leaf) and not dom_mod.is_covered(leaf):
            return 1.0
        key = "uncrinkliness_circulation" if dom_mod.is_circulation(leaf) else "uncrinkliness"
        distance, sigma = self.conf(key)
        crink = self.crinkliness(leaf, G, groups)
        if not crink:
            return 0.0
        return gaussian(1 / crink, 1.0, distance, sigma)

    # --- access --- #

    def neighbour_types(self, leaf: Node, G: nx.Graph) -> list[str]:
        return sorted(nb.type or "" for nb in G.neighbors(leaf) if dom_mod.is_usable(nb))

    def access(self, leaf: Node, G: nx.Graph) -> list[str]:
        """Useful circulation/access neighbour types; ``Urb::Dom::Access``."""
        types = self.neighbour_types(leaf, G)
        if _t0(leaf) == "k":
            return [t for t in types if t and t[0].lower() in ("l", "c", "s")]
        if dom_mod.is_outside(leaf) or dom_mod.is_circulation(leaf):
            return types
        return [t for t in types if t and t[0].lower() in ("c", "s")]

    # ------------------------------------------------------------------ #
    # Leaf evaluation (Leaf.pm::evaluate_leaf)
    # ------------------------------------------------------------------ #

    def evaluate_leaf(
        self, leaf: Node, G: nx.Graph, level_id: int, groups: dict, fail
    ) -> tuple[float, dict[str, float]]:
        """Return (quality, per-factor dict); appends failures via ``fail``.

        Factor order and fail strings mirror ``evaluate_leaf`` exactly.
        """
        lid = leaf.id
        factors: dict[str, float] = {}
        quality = 1.0

        f = self.quality_perpendicular(leaf)
        if f < FAIL_THRESHOLD:
            fail(f"{level_id}/{lid} perpendicular")
        factors["perpendicular"] = f
        quality *= f

        f = self.quality_proportion(leaf)
        if f < FAIL_THRESHOLD:
            fail(f"{level_id}/{lid} proportion")
        factors["proportion"] = f
        quality *= f

        f = self.quality_size(leaf)
        if f < FAIL_THRESHOLD:
            fail(f"{level_id}/{lid} size")
        factors["size"] = f
        quality *= f

        f = self.quality_width(leaf)
        if f < FAIL_THRESHOLD:
            fail(f"{level_id}/{lid} width")
        factors["width"] = f
        quality *= f

        f = self.quality_uncrinkliness(leaf, G, groups)
        if f < FAIL_THRESHOLD:
            fail(f"{level_id}/{lid} crinkliness")
        factors["crinkliness"] = f
        quality *= f

        # Daylight pinned to 1 — URB_NO_OCCLUSION semantics (DESIGN.md §6).
        factors["daylight"] = 1.0

        if len(self.access(leaf, G)) > 0:
            f = 1.0
        elif not dom_mod.level_of(leaf) and dom_mod.is_outside(leaf):
            f = 1.0
        else:
            f = 0.01
            fail(f"{level_id}/{lid} access")
        factors["access"] = f
        quality *= f

        return quality, factors

    # ------------------------------------------------------------------ #
    # Value rates and costs (Leaf.pm:146-251, Storey.pm:122-147)
    # ------------------------------------------------------------------ #

    def value_rate(self, leaf: Node) -> float:
        t0 = _t0(leaf)
        if t0 in ("o", "s") and dom_mod.level_of(leaf) == 0:
            return self.conf("value_outside")
        if t0 in ("o", "s"):
            return self.conf("value_supported")
        if t0 == "c":
            return self.conf("value_circulation")
        return self.conf("value_inside")

    def leaf_cost(self, leaf: Node) -> float:
        if dom_mod.is_outside(leaf):
            covered = dom_mod.is_covered(leaf)
            supported = dom_mod.is_supported(leaf)
            if covered and supported:
                rate = self.cost("outside_covered_supported")
            elif covered:
                rate = self.cost("outside_covered")
            elif supported:
                rate = self.cost("outside_supported")
            else:
                rate = self.cost("outside")
        else:
            rate = self.cost("inside")
        return rate * geometry.area(leaf)

    def edge_cost(self, G: nx.Graph, a: Node, b: Node, fail) -> float:
        """Interior/exterior wall cost for one graph edge
        (``Storey.pm::calculate_edge_cost``)."""
        height = _height(a)
        a_out, b_out = dom_mod.is_outside(a), dom_mod.is_outside(b)
        if a_out and b_out:
            rate = 0.0
        elif not a_out and not b_out:
            rate = self.cost("interior_wall")
        else:
            rate = self.cost("exterior_wall")
        width = G[a][b]["width"]
        if width > 8.0 and rate > 0.0:
            fail(f"{dom_mod.level_of(a)}/{a.id} {b.id} edge too long")
        return rate * width * height

    def outside_edge_cost(self, leaf: Node, fail) -> float:
        """Plot-boundary cost for a leaf's external edges
        (``Leaf.pm::calculate_outside_edge_cost``)."""
        rate = self.cost("boundary") if dom_mod.is_outside(leaf) else self.cost("boundary_wall")
        length = 0.0
        for e in range(4):
            if geometry.boundary_id(leaf, e) not in geometry._EXTERNAL:
                continue
            edge_len = geometry.edge_length(leaf, e)
            length += edge_len
            if dom_mod.is_outside(leaf):
                continue
            if edge_len > 8.0:
                fail(f"{dom_mod.level_of(leaf)}/{leaf.id} outside edge too long")
        return rate * length * _height(leaf)

    # ------------------------------------------------------------------ #
    # Storey processing (Storey.pm::process_storey — cost/value/leaf scope)
    # ------------------------------------------------------------------ #

    def process_storey(self, level_root: Node, G: nx.Graph, level_id: int, fail) -> StoreyEval:
        """Per-storey cost, value and leaf evaluations on the MERGED tree.

        Covers the cost/value accumulation and per-leaf checks of
        ``process_storey``; circulation connectivity, roof-garden, stair fit
        and tracking-driven building checks are homemaker-py-hgg.
        """
        groups = geometry.boundary_groups(level_root)
        cost = 0.0
        value = 0.0
        leaves_eval: list[LeafEval] = []

        for leaf in level_root.leaves():
            if dom_mod.is_outside(leaf) and dom_mod.is_covered(leaf) and level_id:
                if not dom_mod.is_supported(leaf):
                    fail(f"{level_id}/{leaf.id} unsupported covered outside")
                fail(f"{level_id}/{leaf.id} covered outside above ground")

            cost += self.leaf_cost(leaf)
            if not dom_mod.is_usable(leaf):
                continue

            quality, factors = self.evaluate_leaf(leaf, G, level_id, groups, fail)
            rate = self.value_rate(leaf)
            value += quality * rate * geometry.area(leaf)
            leaves_eval.append(
                LeafEval(
                    level=level_id,
                    id=leaf.id,
                    type=leaf.type or "",
                    area=geometry.area(leaf),
                    rate=rate,
                    quality=quality,
                    factors=factors,
                )
            )

        for a, b in G.edges():
            cost += self.edge_cost(G, a, b, fail)
        for leaf in level_root.leaves():
            cost += self.outside_edge_cost(leaf, fail)

        return StoreyEval(cost=cost, value=value, leaves=leaves_eval)

    def plot_cost(self, root: Node) -> float:
        """The 'initial cost' term: plot rate x lowest-root area."""
        return self.cost("plot") * geometry.area(root)

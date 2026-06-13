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
        self._programme_cache: dict | None = None
        self._load_programme(self._conf)

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

    # ----------------------------------------------------------------------- #
    # Stair geometry (Urb::Misc::Stairs + Urb::Dom::Stair_Fit)
    # ----------------------------------------------------------------------- #

    @staticmethod
    def _risers_number(height: float, max_riser: float) -> int:
        """Number of risers; mirrors ``risers_number`` in ``Urb::Misc::Stairs``."""
        n = height / max_riser
        return n if int(n) == n else 1 + int(n)

    @staticmethod
    def _ideal_going(riser: float) -> float:
        """Ideal going in metres; mirrors ``ideal_going`` in ``Urb::Misc::Stairs``."""
        going = 0.625 - 2 * riser
        if going < 0.22:
            return 0.22
        if int(going * 200) == going * 200:
            return going
        return 0.005 + int(going * 200) / 200

    @staticmethod
    def _three_turn(risers: int, going_a: int) -> int:
        r = int((risers + 1) / 2) - 5 - int(going_a)
        return max(0, r)

    @staticmethod
    def _two_turn(risers: int, going_a: int) -> int:
        if risers % 2 == 1:
            r = int(risers / 2) - 3 - int(going_a / 2)
        else:
            r = int(risers / 2) - 3 - int((going_a + 1) / 2)
        return max(0, r)

    @staticmethod
    def _one_turn(risers: int, going_a: int) -> int:
        r = risers - 4 - int(going_a)
        return max(0, r)

    @staticmethod
    def _zero_turn(risers: int, going_a: int) -> int:
        if going_a + 2 > risers:
            return 0
        return risers - 1

    def _stair_fit(self, leaf: Node, corners: list[int]) -> float:
        """Stair fit score for one circulation leaf; mirrors ``Urb::Dom::Stair_Fit``."""
        root = dom_mod._level_root(leaf)
        while root.below is not None:
            root = root.below
        max_riser = getattr(root, "stair_riser", None) or 0.21
        width = getattr(root, "stair_width", None) or 1.25

        height = _height(leaf)
        risers = self._risers_number(height, max_riser)
        going = self._ideal_going(height / risers)
        base = geometry.edge_length(leaf, corners[0])
        length = geometry.edge_length(leaf, corners[0] + 1)

        going_a = int((base - 2 * width) / going)
        n = len(corners)
        if n == 1:
            going_b = self._three_turn(risers, going_a)
        elif n == 2:
            going_b = self._two_turn(risers, going_a)
        elif n == 3:
            going_b = self._one_turn(risers, going_a)
        else:
            going_b = self._zero_turn(risers, going_a)

        return length / (width * 2 + going * going_b)

    # ----------------------------------------------------------------------- #
    # Building-level ratio helpers (Dom.pm:Ratios/Areas/Area_Internal)
    # ----------------------------------------------------------------------- #

    @staticmethod
    def _areas(root: Node) -> tuple[float, dict[str, float]]:
        """Total usable area and per-type area dict; mirrors ``Urb::Dom::Areas``."""
        area_all = 0.0
        areas: dict[str, float] = {}
        for lvl in dom_mod.levels(root):
            for leaf in lvl.leaves():
                if not dom_mod.is_usable(leaf):
                    continue
                a = geometry.area(leaf)
                area_all += a
                t = leaf.type or ""
                areas[t] = areas.get(t, 0.0) + a
        return area_all, areas

    @staticmethod
    def _area_internal(root: Node) -> float:
        """Non-outside usable area; mirrors ``Urb::Dom::Area_Internal``."""
        total = 0.0
        for lvl in dom_mod.levels(root):
            for leaf in lvl.leaves():
                if dom_mod.is_outside(leaf):
                    continue
                total += geometry.area(leaf)
        return total

    def _ratios(self, root: Node) -> dict[str, float]:
        """Per-type proportions; mirrors ``Urb::Dom::Ratios``."""
        area_all, areas = self._areas(root)
        if area_all == 0.0:
            return {}
        return {t: a / area_all for t, a in areas.items()}

    def ratio_o(self, ratios: dict[str, float]) -> float:
        """Outside/sahn proportion gaussian; mirrors ``ProgrammeDriven::ratio_o``."""
        proportion_o = sum(v for k, v in ratios.items() if k and k[0].lower() in ("o", "s"))
        return gaussian(proportion_o, 1.0, *self.conf("ratio_outside"))

    def ratio_type(self, ratios: dict[str, float], code: str, ratio: float, sigma: float) -> float:
        """Type-class proportion gaussian; mirrors ``ProgrammeDriven::ratio_type``."""
        proportion_type = sum(v for k, v in ratios.items() if k and k[0].lower() == code[0].lower())
        proportion_non_o = 1.0 - sum(v for k, v in ratios.items() if k and k[0].lower() in ("o", "s"))
        if proportion_non_o <= 0.0:
            proportion_non_o = 1.0
        return gaussian(proportion_type / proportion_non_o, 1.0, ratio, sigma)

    def quality_staircase_volume(self, *stair_fits: float) -> float:
        """Best-stair gaussian; mirrors ``ProgrammeDriven::quality_staircase_volume``."""
        factor = 0.09
        for sf in stair_fits:
            if sf < 1:
                f2 = gaussian(sf, 1.2, 1.0, 0.1)
            else:
                f2 = gaussian(sf, 1.2, 1.0, 0.5)
            if f2 > factor:
                factor = f2
        return factor

    # ----------------------------------------------------------------------- #
    # Public access / boundary length helpers
    # ----------------------------------------------------------------------- #

    @staticmethod
    def _access_external(leaf: Node) -> list[str]:
        """External boundary ids ('a'-'d') for each edge of leaf."""
        _EXT = frozenset("abcd")
        result = []
        for edge in range(4):
            bid = geometry.boundary_id(leaf, edge)
            if bid in _EXT:
                result.append(bid)
        return result

    @staticmethod
    def _perimeter_type(root: Node, bid: str) -> str:
        """Type string from root perimeter dict ('' if not set)."""
        p = root.perimeter
        if p is None:
            return ""
        return p.get(bid) or ""

    def _public_access(self, leaf: Node, root: Node) -> str | None:
        """Return external boundary id if leaf has public street access; mirrors
        ``Urb::Dom::Public_Access``. Returns None if no public access."""
        if dom_mod.level_of(leaf) != 0:
            return None
        if leaf.divided:
            return None
        for bid in self._access_external(leaf):
            if self._perimeter_type(root, bid).lower() != "private":
                return bid
        return None

    def _entrance_bid_for_stair(
        self,
        stair_leaf: Node,
        level_root: Node,
        G: nx.Graph,
        graph_circ: list,
        all_lvls: list,
        root: Node,
    ) -> str | None:
        """Return boundary id if stair_leaf is the building entrance; else None.

        Mirrors the stair-entrance selection in Urb::Dom::Entrances: a stair C
        leaf wins (priority 3) only when no non-stair C leaf has a higher-priority
        entrance (priority 4 direct, 4.5 via outdoor).  Via-outdoor stair entries
        (priority 3.5) map to a leaf id, not a boundary, so they never produce
        entrance corners in Perl either.
        """
        from . import graph as graph_mod

        stair_bid = self._public_access(stair_leaf, root)
        if stair_bid is None:
            return None
        for other in level_root.leaves():
            if other is stair_leaf:
                continue
            if not other.type or other.type[0].lower() != "c":
                continue
            other_corners = graph_mod.stack_corners_in_use(other, graph_circ, all_lvls)
            if dom_mod.is_covered(other) and other_corners:
                continue  # also a stair — same priority, skip
            if self._public_access(other, root) is not None:
                return None
            for nb in G.neighbors(other):
                if nb.type and nb.type[0].lower() == "o" and self._public_access(nb, root) is not None:
                    return None
        # If the stair itself has via-outdoor access (Entrances priority 3.5), Perl's
        # Entrances maps it to a leaf id, not a boundary id.  Boundary_Id(edge) eq
        # leaf_id never matches → no entrance corners added.  Return None here so
        # Python matches that behaviour.
        for nb in G.neighbors(stair_leaf):
            if nb.type and nb.type[0].lower() == "o" and self._public_access(nb, root) is not None:
                return None
        return stair_bid

    def _public_access_outside(self, leaf: Node, G: nx.Graph, root: Node) -> bool:
        """True if leaf is an outside street-edge node with an lck neighbour;
        mirrors ``Urb::Dom::Public_Access_Outside``."""
        if leaf.divided:
            return False
        if not dom_mod.is_outside(leaf):
            return False
        if self._public_access(leaf, root) is None:
            return False
        for nb in G.neighbors(leaf):
            if nb.type and nb.type[0].lower() in ("l", "c", "k"):
                return True
        return False

    def _public_length(self, leaf: Node, root: Node) -> float:
        """Non-private external boundary metres; mirrors ``Urb::Dom::Public_Length``."""
        if dom_mod.level_of(leaf) != 0:
            return 0.0
        total = 0.0
        for edge in range(4):
            bid = geometry.boundary_id(leaf, edge)
            if bid not in frozenset("abcd"):
                continue
            if self._perimeter_type(root, bid).lower() == "private":
                continue
            total += geometry.edge_length(leaf, edge)
        return total

    def _private_length(self, leaf: Node, root: Node) -> float:
        """Private external boundary metres; mirrors ``Urb::Dom::Private_Length``."""
        if dom_mod.level_of(leaf) != 0:
            return 0.0
        total = 0.0
        for edge in range(4):
            bid = geometry.boundary_id(leaf, edge)
            if bid not in frozenset("abcd"):
                continue
            if self._perimeter_type(root, bid).lower() != "private":
                continue
            total += geometry.edge_length(leaf, edge)
        return total

    # ----------------------------------------------------------------------- #
    # Extended process_storey (adds circ, stair, tracking)
    # ----------------------------------------------------------------------- #

    def process_storey(
        self,
        level_root: Node,
        G: nx.Graph,
        level_id: int,
        fail,
        graph_circ: list[nx.Graph] | None = None,
        tracking: dict | None = None,
        lvls: list[Node] | None = None,
        root: Node | None = None,
    ) -> StoreyEval:
        """Per-storey cost, value and leaf evaluations on the MERGED tree.

        Optional ``graph_circ``, ``tracking``, ``lvls``, ``root`` activate the
        homemaker-py-hgg storey checks (stair fit, circulation connectivity,
        roof-garden, public-access tracking).  When omitted the method behaves
        as in homemaker-py-gnw (leaf quality + costs only).
        """
        from . import graph as graph_mod

        groups = geometry.boundary_groups(level_root)
        cost = 0.0
        value = 0.0
        leaves_eval: list[LeafEval] = []
        has_outdoor_space = False

        for leaf in level_root.leaves():
            if dom_mod.is_outside(leaf) and dom_mod.is_covered(leaf) and level_id:
                if not dom_mod.is_supported(leaf):
                    fail(f"{level_id}/{leaf.id} unsupported covered outside")
                fail(f"{level_id}/{leaf.id} covered outside above ground")

            cost += self.leaf_cost(leaf)
            if not dom_mod.is_usable(leaf):
                continue

            if dom_mod.is_outside(leaf):
                has_outdoor_space = True

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

            if graph_circ is not None and tracking is not None and lvls is not None and root is not None:
                # Stair fit — ground floor circulation/covered only
                stair_fit = 0.0
                if level_id == 0 and leaf.type and leaf.type[0].lower() == "c" and dom_mod.is_covered(leaf):
                    all_lvls = lvls
                    corners = graph_mod.stack_corners_in_use(leaf, graph_circ, all_lvls)
                    n_corners = len(corners)
                    if n_corners:
                        # Mirror Perl check_stair_fit: add entrance door corners so
                        # the stair loses the corner it shares with the entrance.
                        entrance_bid = self._entrance_bid_for_stair(
                            leaf, level_root, G, graph_circ, all_lvls, root
                        )
                        if entrance_bid is not None:
                            for edge in range(4):
                                if geometry.boundary_id(leaf, edge) == entrance_bid:
                                    for ec in (edge, edge + 1):
                                        if ec not in corners:
                                            corners = corners + [ec]
                        stair_fit = self._stair_fit(leaf, corners)
                        tracking["stair_fit"].append(stair_fit)

                # Public access tracking
                if root is not None:
                    if self._public_access_outside(leaf, G, root):
                        tracking["has_public_access_outside"] = True
                    if (not stair_fit
                            and leaf.type and leaf.type[0].lower() == "c"
                            and self._public_access(leaf, root) is not None):
                        tracking["has_public_access_inside"] = True

                    pub = self._public_length(leaf, root)
                    tracking["public_length_all"] = tracking.get("public_length_all", 0.0) + pub
                    if dom_mod.is_outside(leaf):
                        tracking["public_length_outside"] = tracking.get("public_length_outside", 0.0) + pub
                    priv = self._private_length(leaf, root)
                    tracking["private_length_all"] = tracking.get("private_length_all", 0.0) + priv
                    if dom_mod.is_outside(leaf):
                        tracking["private_length_outside"] = tracking.get("private_length_outside", 0.0) + priv

        for a, b in G.edges():
            cost += self.edge_cost(G, a, b, fail)
        for leaf in level_root.leaves():
            cost += self.outside_edge_cost(leaf, fail)

        if graph_circ is not None:
            # Connected_Circulation check on a copy of the circ graph
            gc_copy = graph_circ[level_id].copy() if level_id < len(graph_circ) else nx.Graph()
            if not graph_mod.connected_circulation(gc_copy):
                fail(f"level {level_id} not connected")

            conf_fg = self.conf("force_roof_garden")
            if conf_fg and not has_outdoor_space:
                fail(f"level {level_id} no outside space")

        return StoreyEval(cost=cost, value=value, leaves=leaves_eval)

    # ----------------------------------------------------------------------- #
    # Building-level evaluation
    # ----------------------------------------------------------------------- #

    def evaluate_building(self, root: Node, tracking: dict) -> float:
        """Building factor; mirrors ``evaluate_building_program_driven``."""
        from . import graph as graph_mod

        ratios = self._ratios(root)

        factor = 1.0
        factor *= self.ratio_o(ratios)

        circ_ratio = self.conf("ratio_circulation")
        factor *= self.ratio_type(ratios, "c", circ_ratio[0], circ_ratio[1])

        min_required = 0.0
        for req in (self._programme or {}).values():
            if req.code and req.code[0].lower() in ("c", "o", "s"):
                continue
            if req.size > 0:
                min_required += req.size * req.count
        min_required *= 1.2
        actual_internal = self._area_internal(root)
        if actual_internal < min_required and min_required > 0:
            f2 = gaussian(actual_internal, 1.0, min_required, min_required * 0.15)
            factor *= f2

        # Public/private ratios (optional config)
        pub_all = tracking.get("public_length_all", 0.0)
        pub_ratio = tracking.get("public_length_outside", 0.0) / pub_all if pub_all else 0.0
        conf_po = self.conf("ratio_public_outside")
        if conf_po and isinstance(conf_po, list):
            factor *= gaussian(pub_ratio, 1.0, conf_po[0], conf_po[1])

        priv_all = tracking.get("private_length_all", 0.0)
        priv_ratio = tracking.get("private_length_outside", 0.0) / priv_all if priv_all else 0.0
        conf_pr = self.conf("ratio_private_outside")
        if conf_pr and isinstance(conf_pr, list):
            factor *= gaussian(priv_ratio, 1.0, conf_pr[0], conf_pr[1])

        # Staircase volume (multi-level only)
        lvls = dom_mod.levels(root)
        if len(lvls) > 1:
            sf_factor = self.quality_staircase_volume(*tracking.get("stair_fit", []))
            if sf_factor < FAIL_THRESHOLD:
                tracking["_failures"].append("staircase volume")
            factor *= sf_factor

        stair_min = self.conf("staircase_min") or 1
        stair_max = self.conf("staircase_max") or 1
        stair_count = len(tracking.get("stair_fit", []))

        if stair_count < stair_min:
            tracking["_failures"].append(
                f"too few stairs ({stair_count}, min {stair_min})"
            )
        if stair_count > stair_max:
            tracking["_failures"].append(
                f"too many stairs ({stair_count}, max {stair_max})"
            )

        # Storey limit / minimum
        n_storeys = len(lvls)
        storey_limit = self.conf("storey_limit") or 4
        storey_min = self.conf("storey_minimum") or 2
        if n_storeys - 1 >= storey_limit:
            tracking["_failures"].append("storey limit")
        if n_storeys < storey_min:
            tracking["_failures"].append("storey minimum")

        # Public access
        if not (tracking.get("has_public_access_outside") or tracking.get("has_public_access_inside")):
            tracking["_failures"].append("no outside public access")

        return factor

    # ----------------------------------------------------------------------- #
    # Full pipeline
    # ----------------------------------------------------------------------- #

    def evaluate(self, root: Node) -> float:
        """Full programme-driven fitness; mirrors ``ProgrammeDriven::_apply``.

        Returns ``value / cost`` (the final score as in Urb).
        """
        score, _ = self._evaluate_full(root)
        return score

    def score_with_fails(self, root: Node) -> tuple[float, tuple[str, ...]]:
        """Same as ``evaluate`` but also returns the sorted failure strings."""
        return self._evaluate_full(root)

    def _evaluate_full(self, root: Node) -> tuple[float, tuple[str, ...]]:
        from . import graph as graph_mod

        geometry.clear_cache()

        failures: list[str] = []
        tracking: dict = {
            "has_public_access_outside": False,
            "has_public_access_inside": False,
            "public_length_all": 0.0,
            "public_length_outside": 0.0,
            "private_length_all": 0.0,
            "private_length_outside": 0.0,
            "stair_fit": [],
            "_failures": failures,
        }

        programme = self._programme or {}

        # --- Phase 1: UNMERGED tree checks ---
        check_fails, missing = graph_mod.check_space_counts(root, programme)
        failures.extend(check_fails)

        self.preprocess_building(root)
        _, graph_circ_pre = graph_mod.build_graphs_with_circ(
            root, self.conf("door_width") or 1.2, failures.append
        )

        graph_base_pre = graph_mod.build_graphs(root, self.conf("door_width") or 1.2)

        failures.extend(graph_mod.check_adjacency(root, programme, graph_base_pre, missing))
        failures.extend(graph_mod.check_level_constraints(root, programme, missing))
        failures.extend(graph_mod.check_vertical_connectivity(root, programme, missing))

        # --- Phase 2: MERGED tree ---
        dom_mod.merge_divided(root)
        geometry.clear_cache()  # mirror Perl Merge_Divided → Clean_Cache

        _, graph_circ = graph_mod.build_graphs_with_circ(
            root, self.conf("door_width") or 1.2, failures.append
        )
        graph_base = graph_mod.build_graphs(root, self.conf("door_width") or 1.2)

        cost = self.plot_cost(root)
        value = 0.0
        lvls = dom_mod.levels(root)

        for li, lvl in enumerate(lvls):
            se = self.process_storey(
                lvl, graph_base[li], li, failures.append,
                graph_circ=graph_circ,
                tracking=tracking,
                lvls=lvls,
                root=root,
            )
            cost += se.cost
            value += se.value

        building_factor = self.evaluate_building(root, tracking)
        value *= building_factor

        # 0.5^n failure penalty (programme-driven mode, not 0.1^n)
        value *= 0.5 ** len(failures)

        score = value / cost if cost != 0.0 else 0.0
        return score, tuple(sorted(failures))

    @property
    def _programme(self) -> dict | None:
        """Programme requirements parsed from config, or None."""
        return self._programme_cache

    def _load_programme(self, conf: dict) -> None:
        """Populate ``_programme_cache`` from spaces section of conf dict."""
        from .programme import SpaceReq
        _DW = (4.0, 1.0)
        _DP = (1.5, 0.5)
        spaces = conf.get("spaces") or {}
        if not spaces:
            self._programme_cache = None
            return
        reqs: dict = {}
        for code, c in spaces.items():
            sz = c.get("size") or [0.0, 1.0]
            w = c.get("width") or _DW
            pr = c.get("proportion") or _DP
            reqs[code] = SpaceReq(
                code=code,
                name=c.get("name", ""),
                size=float(sz[0]),
                size_sigma=float(sz[1]),
                width=float(w[0]),
                width_sigma=float(w[1]),
                proportion=float(pr[0]),
                proportion_sigma=float(pr[1]),
                adjacency=list(c.get("adjacency") or []),
                level=c.get("level"),
                requires_below=c.get("requires_below"),
                count=int(c.get("count") or 1),
                has_size="size" in c,
                has_width="width" in c,
                has_proportion="proportion" in c,
            )
        self._programme_cache = reqs

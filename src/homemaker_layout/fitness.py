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

# Per-leaf quality factors that emit a failure when they drop below
# FAIL_THRESHOLD (evaluate_leaf, in emission order). The graded objective
# (DESIGN.md §11.4) reads each failing factor's value as a continuous proximity
# to satisfaction — it does NOT change the scalar fitness or the fail count, only
# supplies a tie/secondary signal to the outer comparator (driver.py).
_GRADED_FACTORS = ("perpendicular", "proportion", "size", "width",
                   "crinkliness", "access")


def _leaf_grade(factors: dict[str, float]) -> float:
    """Proximity credit for one leaf's *failing* quality factors.

    Each factor below FAIL_THRESHOLD contributes ``f / FAIL_THRESHOLD`` ∈ [0, 1):
    deeper failures score ~0, near-threshold failures score ~1. Summing this over
    all failing factors gives a continuous proximity signal. Passing factors
    contribute nothing — the signal lives entirely in the failing set — and
    structural/binary fails (missing, adjacency, edge-too-long, …) contribute 0,
    so the measure can never reward dropping a required room (§6 preserved).

    Intended as an outer-comparator secondary key, but REJECTED as such (DESIGN.md
    §11.4): within a fixed fail-tier the scalar fitness is not flat, so this added
    no benefit. Kept for reproducibility / possible reuse as a diversity signal.
    """
    g = 0.0
    for name in _GRADED_FACTORS:
        fv = factors.get(name, 1.0)
        if fv < FAIL_THRESHOLD:
            g += fv / FAIL_THRESHOLD
    return g

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


def _gaussian_product(target_a: float, sigma_a: float,
                      target_b: float, sigma_b: float) -> tuple[float, float]:
    """Precision-weighted combination of two Gaussian (target, sigma) pairs
    (homemaker-py-1s3): the product of two Gaussian curves evaluated at the
    same point is itself proportional to a Gaussian with precisions (1/sigma^2)
    ADDING and target the precision-weighted average — always an INTERMEDIATE
    target (never simply the stricter of the two) with a NARROWER spread than
    either input, unlike a naive max-target/min-sigma combination.

    Used by ``quality_width``/``quality_proportion`` to combine a co-located
    leaf's two codes' shape targets. A/B-measured (DESIGN.md §33) as the best
    of three tried: beats both the naive max-target/min-sigma hack (health-
    centre +24.5% worse) and the max-of-two MIXTURE combination below
    (health-centre +20.4% worse) — this precision-weighted single compromise
    peak was the only one to improve both example programmes."""
    prec_a, prec_b = 1.0 / (sigma_a * sigma_a), 1.0 / (sigma_b * sigma_b)
    prec_c = prec_a + prec_b
    target_c = (target_a * prec_a + target_b * prec_b) / prec_c
    return target_c, (1.0 / prec_c) ** 0.5


def _clipped_gaussian(x: float, target: float, sigma: float, good_side: str) -> float:
    """The 'flat 1.0 once the target is met, gaussian decay short of it' shape
    both ``quality_width`` (wider than target is good) and
    ``quality_proportion`` (squarer/lower aspect than target is good) use.

    Also the building block of a MIXTURE alternative to ``_gaussian_product``
    that was tried and measured worse (homemaker-py-1s3, DESIGN.md §33):
    evaluate this once per served code and combine with ``max()`` instead of
    computing one combined (target, sigma) — the leaf scores well if the
    realised geometry ends up close to EITHER code's target rather than one
    narrow compromise peak, echoing the per-leaf usage collapse §26 path (a)
    uses at the whole-leaf-type level. Appealing in principle (no forced
    compromise) but empirically worse on the tightly-packed health-centre
    programme (+20.4%, vs -13.9% for the precision-weighted product currently
    used) — plausibly because ``max()`` lets a leaf score 1.0 by satisfying
    only the WEAKER of two codes' targets, under-constraining the search."""
    if (good_side == "above" and x > target) or (good_side == "below" and x < target):
        return 1.0
    return gaussian(x, 1.0, target, sigma)


def load_config(directory: str | Path,
                overrides: dict | None = None) -> tuple[dict, dict]:
    """Load (patterns, costs) config for a corpus directory, mirroring
    ``urb-fitness.pl``: project-level ``../<name>.config`` first, then the
    local file's keys override it.

    ``overrides`` (homemaker-py-x3b) are merged into the patterns conf last, so a
    caller can switch on run-level knobs (e.g. ``leaf_sharing``) without editing
    any ``patterns.config`` on disk — keeping the §13.3 example programmes
    reproducible while the CLI/driver drives sharing programmatically."""
    directory = Path(directory)
    conf: dict = {}
    cost: dict = {}
    for target, name in ((conf, "patterns.config"), (cost, "costs.config")):
        for p in (directory.parent / name, directory / name):
            if p.is_file():
                with open(p) as fh:
                    target.update(yaml.safe_load(fh) or {})
    if overrides:
        conf.update(overrides)
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
        # erc.3 leaf-sharing (DESIGN.md §13.3): default OFF. When on, a leaf sized
        # to k×target counts as k same-code rooms (count check + size centring).
        self._leaf_sharing = bool(self.conf("leaf_sharing"))
        self._max_share = int(self.conf("leaf_share_max") or 4)
        # erc.hph §13.7/§13.8: scale the edge-too-long cap by a shared leaf's
        # share k so an aggregate (k-room) leaf is not penalised for long walls —
        # the §13.3 leak on a different measure. The §13.8 A/B verdict was
        # positive and monotone-harmless, so the default is ON for leaf-sharing
        # runs (mirrors the pll/interior_outside default flips). An explicit
        # share_edge_cap=False still reproduces the pre-flip control arm.
        cap = self.conf("share_edge_cap")
        self._share_edge_cap = self._leaf_sharing if cap is None else bool(cap)
        # 9o5 type superposition (DESIGN.md §13/homemaker-py-9o5): default OFF.
        # When on, interchangeable codes (similar requirements) form equivalence
        # classes; each candidate's fitness re-types (collapses) every superposed
        # leaf to its best in-class usage before scoring, so search optimises the
        # condensed objective directly and the relaxation gap is removed.
        self._superpose = bool(self.conf("superpose"))
        # homemaker-py-qi6 graded circulation-connectivity signal (DESIGN.md §18):
        # default OFF. When on, the graded proximity scalar (want_grade) is the
        # per-level largest-circ-component fraction instead of the §11.4 leaf
        # quality-proximity — a secondary comparator key giving the outer search
        # a gradient the binary "level N not connected" fail lacks. Leaves the
        # scalar fitness and fail count untouched, exactly like §11.4.
        self._conn_grade = bool(self.conf("conn_grade"))
        from .programme import CLASS_CAP as _CLASS_CAP
        self._class_cap = int(self.conf("superpose_class_cap") or _CLASS_CAP)
        self._interchange_classes: list | None = None  # lazily derived
        # homemaker-py-qpk: IN-SEARCH global collapse. Default OFF. When on,
        # collapse_global (the 94g finish-time cell<->room relabel) runs INSIDE
        # _evaluate_full every eval instead of once at the end, so search
        # optimises the collapsed objective directly (mirrors the 9o5 per-eval
        # collapse above, at GLOBAL scope). Carries the 9o5/xi7 landscape-
        # flattening risk amplified to the whole building; gated behind its own
        # A/B (DESIGN.md §17 follow-on, homemaker-py-qpk) — do not default on
        # without a positive result.
        self._collapse_insearch = bool(self.conf("collapse_insearch"))
        adj = self.conf("collapse_insearch_adjacency")
        self._collapse_insearch_adjacency = True if adj is None else bool(adj)
        # Fewer Jacobi passes than the finish-time default (6): a per-eval cost,
        # not a one-shot polish — profile before raising.
        self._collapse_insearch_iters = int(self.conf("collapse_insearch_iters") or 3)
        # homemaker-py-1s3 §26 path b: multi-use leaves as a PERMANENT design
        # goal (no per-eval collapse, unlike superpose above). Default OFF.
        # When on, a leaf carrying a live, valid co_type counts toward BOTH
        # codes' requirements simultaneously (graph.leaf_codes), and its size
        # target combines both codes' area (quality_size).
        self._multi_use = bool(self.conf("multi_use"))
        self._colocate_pairs: list | None = None  # lazily derived

    # ------------------------------------------------------------------ #
    # Type superposition + collapse (homemaker-py-9o5)
    # ------------------------------------------------------------------ #

    def interchange_classes(self) -> list:
        """Interchange equivalence classes (size>=2), derived once from the
        programme and cached. Empty list when superposition has nothing to act
        on, in which case the collapse is a no-op and scoring matches baseline."""
        if self._interchange_classes is None:
            from . import programme as _pr
            reqs = self._programme or {}
            self._interchange_classes = (
                _pr.derive_interchange_classes(reqs) if reqs else []
            )
        return self._interchange_classes

    # ------------------------------------------------------------------ #
    # Multi-use leaves (homemaker-py-1s3, §26 path b)
    # ------------------------------------------------------------------ #

    def colocate_pairs(self) -> list:
        """Valid co-location pairs, derived once from the programme and
        cached. Empty list when nothing is declared, in which case
        ``multi_use`` is a no-op and scoring matches baseline."""
        if self._colocate_pairs is None:
            from . import programme as _pr
            reqs = self._programme or {}
            self._colocate_pairs = (
                _pr.derive_colocate_pairs(reqs) if reqs else []
            )
        return self._colocate_pairs

    def _leaf_co_type(self, leaf: Node) -> "str | None":
        """The leaf's live, valid co_type under ``multi_use``, else ``None``."""
        if not self._multi_use or not leaf.co_type or not leaf.type:
            return None
        if frozenset((leaf.type, leaf.co_type)) in self.colocate_pairs():
            return leaf.co_type
        return None

    def _usage_quality(self, leaf: Node, usage: str) -> float:
        """The usage-DEPENDENT part of a leaf's quality (size x width x
        proportion) as if it were typed ``usage``. The remaining factors
        (perpendicular, crinkliness, access) and value rate are usage-invariant
        within a class, so this is the separable per-leaf collapse objective."""
        orig = leaf.type
        orig_share_type = leaf.share_type
        leaf.type = usage
        if usage != orig:
            # homemaker-py-iio: a stale share (share>1, share_type left over
            # from a code this leaf no longer holds) must not spuriously
            # reactivate just because THIS hypothetical usage probe happens to
            # match the old share_type -- graph.leaf_share reads leaf.type,
            # which we have just overridden, so it would otherwise compare the
            # stale share_type against the candidate usage instead of the
            # leaf's real committed type. Only the leaf's OWN current type
            # (usage == orig) may legitimately carry a live share.
            leaf.share_type = None
        try:
            return (
                self.quality_size(leaf)
                * self.quality_width(leaf)
                * self.quality_proportion(leaf)
            )
        finally:
            leaf.type = orig
            leaf.share_type = orig_share_type

    def _best_assignment(self, quality: list[list[float]]) -> list[tuple[int, int]]:
        """Maximum-total-quality matching of ``min(rows, cols)`` leaf->slot
        pairs. Brute-forces <= C! permutations when the smaller side is within
        the class cap (exact and tiny); otherwise solves the equivalent
        linear-sum assignment (Hungarian) — both give the optimum because the
        objective is separable per leaf (§3 cost note)."""
        rows = len(quality)
        cols = len(quality[0]) if rows else 0
        if rows == 0 or cols == 0:
            return []
        if min(rows, cols) <= self._class_cap:
            import itertools
            best: list[tuple[int, int]] = []
            best_score = float("-inf")
            if rows <= cols:
                for sel in itertools.permutations(range(cols), rows):
                    s = sum(quality[r][sel[r]] for r in range(rows))
                    if s > best_score:
                        best_score = s
                        best = [(r, sel[r]) for r in range(rows)]
            else:
                for sel in itertools.permutations(range(rows), cols):
                    s = sum(quality[sel[c]][c] for c in range(cols))
                    if s > best_score:
                        best_score = s
                        best = [(sel[c], c) for c in range(cols)]
            return best
        from scipy.optimize import linear_sum_assignment
        import numpy as np
        ri, ci = linear_sum_assignment(-np.array(quality))
        return list(zip(ri.tolist(), ci.tolist()))

    def collapse_superposition(self, root: Node) -> None:
        """Re-type each superposed leaf to its best in-class usage (the per-eval
        COLLAPSE, homemaker-py-9o5 §1). Runs on the UNMERGED tree before any
        check, so counts/adjacency/quality downstream see the condensed types.

        Per class: SUPPLY = leaves currently typed into the class; DEMAND = the
        class codes expanded by their required counts. The optimal supply->demand
        matching assigns each demand slot to the leaf that fits it best; surplus
        supply leaves keep their type (a genuine over-supply that scoring still
        penalises), unmet demand slots stay absent (a genuine missing room)."""
        classes = self.interchange_classes()
        if not classes:
            return
        prog = self._programme or {}
        by_type: dict[str, list[Node]] = {}
        for lvl in dom_mod.levels(root):
            for leaf in lvl.leaves():
                if leaf.type:
                    by_type.setdefault(leaf.type, []).append(leaf)

        for cls in classes:
            supply = [lf for code in cls for lf in by_type.get(code, [])]
            if not supply:
                continue
            slots: list[str] = []
            for code in sorted(cls):
                cnt = prog[code].count if code in prog else 0
                slots.extend([code] * max(0, cnt))
            if not slots:
                continue
            # Weight each leaf's usage quality by its area: the condensed value is
            # sum(quality * value_rate * area), and value_rate is constant within a
            # class (all in-class codes are inside rooms), so area is the per-leaf
            # weight that makes the matching maximise value, not just mean quality.
            quality = [
                [self._usage_quality(lf, s) * geometry.area(lf) for s in slots]
                for lf in supply
            ]
            for r, c in self._best_assignment(quality):
                supply[r].type = slots[c]

    # Forbidden-pairing penalty for the global collapse cost matrix: large and
    # finite (Hungarian cannot take -inf) yet far below any real value, so the
    # optimal matching never uses a level-mismatched pair unless it is forced.
    _COLLAPSE_FORBID = -1e12
    # Weight of one avoided fail (a satisfied adjacency or a passing
    # size/width/proportion factor) in the collapse objective — far above the
    # continuous quality span (~max area) so fail count dominates and raw
    # quality only breaks ties; far below the forbid penalty so level holds.
    _COLLAPSE_FAIL_W = 1e6

    def _collapse_value(
        self,
        lf: Node,
        code: str,
        lvl: int,
        prog: dict,
        objective: str,
        forbid: float,
        fail_w: float,
    ) -> float:
        """Base (non-adjacency) collapse value of relabelling ``lf`` (on storey
        ``lvl``) to ``code``: the ``_COLLAPSE_FORBID`` penalty on a level
        mismatch, else quality_size*width*proportion*area, plus ``fail_w`` per
        passing factor under the ``"threshold"`` objective. Shared by the
        collapse_global assignment matrix and the 2-opt polish below so both
        score a (leaf, code) pair identically."""
        req = prog[code]
        if req.level is not None and req.level != lvl:
            return forbid
        orig = lf.type
        orig_share_type = lf.share_type
        lf.type = code
        if code != orig:
            # homemaker-py-iio: see _usage_quality -- a stale share/share_type
            # left over from a code this leaf no longer holds must not
            # spuriously reactivate just because this hypothetical candidate
            # code happens to match it (graph.leaf_share reads leaf.type,
            # which is overridden to the candidate here). Only the leaf's own
            # current type (code == orig) may legitimately carry a live share.
            lf.share_type = None
        try:
            qs = self.quality_size(lf)
            qw = self.quality_width(lf)
            qp = self.quality_proportion(lf)
        finally:
            lf.type = orig
            lf.share_type = orig_share_type
        val = qs * qw * qp * geometry.area(lf)
        if objective == "threshold":
            passes = (
                (qs >= FAIL_THRESHOLD) + (qw >= FAIL_THRESHOLD) + (qp >= FAIL_THRESHOLD)
            )
            val += fail_w * passes
        return val

    def _two_opt_adjacency_polish(
        self,
        supply: list[Node],
        levels_of: list[int],
        graphs: list,
        code_adj: dict[str, list[str]],
        prog: dict,
        objective: str,
        forbid: float,
        fail_w: float,
        max_passes: int = 20,
    ) -> None:
        """homemaker-py-9wi: a local-search pass beyond collapse_global's Jacobi
        adjacency relaxation. Jacobi re-solves a LINEAR assignment each round
        holding neighbours' labels fixed from the previous round -- exact per
        round, but the true objective is quadratic (a satisfied adjacency
        depends on a PAIR of labels), so synchronous Jacobi can plateau short
        of the joint optimum. This adds 2-opt: for every same-level pair of
        supply leaves, try swapping their CURRENT labels and keep the swap
        only if it strictly increases the total reward (own quality/threshold
        value + fail_w per satisfied adjacency) summed over the two leaves and
        every leaf adjacent to either -- the only cells a label swap between
        i and j can change. Repeats to a fixpoint (or ``max_passes``).

        Same-level-only pairing keeps the hard level constraint for free: both
        codes already matched their own leaf's level before the swap, and the
        two leaves share a level, so the swap is valid on both sides. A swap
        is applied only when it is a STRICT improvement, so this can only
        reduce, never increase, the fail count -- monotone by construction,
        like the Hungarian solve it refines."""
        from . import graph as graph_mod

        idx_of_leaf = {id(lf): i for i, lf in enumerate(supply)}

        def reward(idx: int) -> float:
            lf = supply[idx]
            code = lf.type
            val = self._collapse_value(
                lf, code, levels_of[idx], prog, objective, forbid, fail_w
            )
            if val <= forbid:
                return val
            G = graphs[levels_of[idx]]
            sat = sum(1 for ac in code_adj.get(code, ()) if graph_mod.has_adjacency(lf, ac, G))
            return val + fail_w * sat

        def affected(i: int, j: int) -> set[int]:
            aff = {i, j}
            for k in (i, j):
                lf = supply[k]
                G = graphs[levels_of[k]]
                if G.has_node(lf):
                    for nb in G.neighbors(lf):
                        nidx = idx_of_leaf.get(id(nb))
                        if nidx is not None:
                            aff.add(nidx)
            return aff

        by_level: dict[int, list[int]] = {}
        for idx, lvl in enumerate(levels_of):
            by_level.setdefault(lvl, []).append(idx)

        changed = True
        passes = 0
        while changed and passes < max_passes:
            changed = False
            passes += 1
            for idxs in by_level.values():
                for a in range(len(idxs)):
                    for b in range(a + 1, len(idxs)):
                        i, j = idxs[a], idxs[b]
                        ci, cj = supply[i].type, supply[j].type
                        if ci == cj:
                            continue
                        aff = affected(i, j)
                        before = sum(reward(k) for k in aff)
                        supply[i].type, supply[j].type = cj, ci
                        after = sum(reward(k) for k in aff)
                        if after > before + 1e-9:
                            changed = True
                        else:
                            supply[i].type, supply[j].type = ci, cj

    def collapse_global(
        self,
        root: Node,
        adjacency: bool = True,
        objective: str = "threshold",
        preserve_public_access: bool = True,
        iters: int = 6,
        local_search: bool = False,
        local_search_passes: int = 20,
    ) -> None:
        """Finish-time GLOBAL cell->room collapse (homemaker-py-94g): relabel
        every inside-room leaf across the whole building to the required room it
        fits best, via one optimal assignment over the full leaf set — the 9o5
        per-class collapse generalised to N inside leaves <-> M required rooms.

        SUPPLY = leaves whose type is an assignable programme room code; DEMAND =
        every such code expanded by its required count, tagged with its required
        level. Assignable codes EXCLUDE any starting c/o/s: check_space_counts
        (graph.py) skips those as circulation/outside/sahn — including room codes
        that collide with the convention (cr1, st1, st2) — so those leaves form
        the circulation/structure skeleton and must not be relabelled. Surplus
        leaves keep their type (genuine over-supply); unmet demand stays absent
        (genuine missing room).

        HARD LEVEL constraint: a leaf may only take a room whose required level
        matches its storey (a -1e12 forbid penalty), so the collapse never adds a
        wrong-level fail. ADJACENCY (when ``adjacency``): the objective adds a
        bonus for each of a code's required adjacencies satisfied at a leaf given
        the CURRENT labelling. Because geometry is fixed at finish time, each
        leaf's graph neighbours are fixed and only labels move, so the problem is
        a labelling relaxation: warm-started from the evolved labels, each pass is
        a linear assignment over quality + adjacency-bonus computed from the
        previous pass, iterated to a fixpoint (Jacobi/WFC-style). Maximising
        satisfied adjacencies minimises adjacency fails.

        OBJECTIVE selects the per-leaf base value: ``"quality"`` maximises the
        separable continuous fit sum(usage_quality * area) collapse_superposition
        uses; ``"threshold"`` maximises the COUNT of size/width/proportion factors
        that PASS (>= FAIL_THRESHOLD), with continuous fit only as a tiebreak.
        Continuous quality can trade one leaf just over threshold for another just
        under (a fail SHUFFLE); the threshold objective optimises the fail count
        directly. Under both, a satisfied adjacency and a passing factor carry the
        same weight (_COLLAPSE_FAIL_W = one avoided fail), so the collapse
        minimises (adjacency + size/width/proportion) fails jointly.

        LOCAL_SEARCH (homemaker-py-9wi, default False HERE): after the Jacobi
        loop above reaches its fixpoint, run a 2-opt polish
        (_two_opt_adjacency_polish) that tries swapping the labels of every
        same-level pair of supply leaves and keeps a swap only if it strictly
        improves the total reward. Jacobi re-solves a LINEAR assignment each
        round holding neighbours' labels fixed from the previous round, so it
        can plateau short of the true quadratic-assignment optimum (a satisfied
        adjacency depends on a PAIR of labels, not one); 2-opt reaches past that
        plateau. Monotone by construction (only strictly-improving swaps are
        kept) and cheap (<1s on the largest file) as a ONE-SHOT finish-time
        polish — but this method is also called on the UNMERGED tree every
        fitness eval when collapse_insearch (qpk) is on, so the method-level
        default stays False to keep that hot path cheap. A 46-file A/B sweep
        across harbor-house (12) and programme-house (34) found 0 regressions
        and 2 improvements (evolved-anneal-3M.dom 21->19, a82f07068e4408fdd0d5e
        3dc469a8dee.dom 3->2 fails) for the finish-time, one-shot use, so
        homemaker-py-cdl turned it on by default there: homemaker-collapse
        --local-search and homemaker-evolve --collapse-local-search both
        default True and pass it through explicitly.

        PRESERVE_PUBLIC_ACCESS pins the room leaf that solely provides the
        building's street access (an l/k neighbour of a public outside leaf, with
        no circulation fallback) so the collapse cannot drop the building-level
        "no outside public access" check — the one recurring regression the
        per-leaf objective cannot see (it is existential and building-scoped).

        One-shot finish-time pass on a committed layout, not a per-eval re-type."""
        from collections import Counter
        from . import graph as graph_mod

        # homemaker-py-r5a: drop any stale share/share_type BEFORE this pass
        # relabels anything, so a leaf relabelled back to the code its stale
        # stamp names cannot resurrect a multiplicity credit (see
        # dom.canonicalize_shares).
        dom_mod.canonicalize_shares(root)

        prog = self._programme or {}
        if not prog:
            return
        room_codes = {c for c in prog if c[0].lower() not in ("c", "o", "s")}
        if not room_codes:
            return
        lvls = dom_mod.levels(root)
        graphs = (
            graph_mod.build_graphs(root, self.conf("door_width") or 1.2)
            if (adjacency or preserve_public_access)
            else None
        )

        pinned = (
            self._public_access_pins(root, graphs, lvls, room_codes)
            if (preserve_public_access and graphs is not None)
            else set()
        )
        supply = [
            lf
            for lvl in lvls
            for lf in lvl.leaves()
            if lf.type in room_codes and id(lf) not in pinned
        ]
        if not supply:
            return
        # Demand = room-code counts, minus one slot per pinned leaf (its instance
        # is already met by the pin, so it must not be demanded of another leaf).
        slot_counts = Counter({c: max(0, prog[c].count) for c in room_codes})
        if pinned:
            for lvl in lvls:
                for lf in lvl.leaves():
                    if id(lf) in pinned and slot_counts.get(lf.type, 0) > 0:
                        slot_counts[lf.type] -= 1
        slots = [c for c in sorted(slot_counts) for _ in range(slot_counts[c])]
        if not slots:
            return

        forbid = self._COLLAPSE_FORBID
        fail_w = self._COLLAPSE_FAIL_W
        levels_of = [dom_mod.level_of(lf) for lf in supply]
        # Base per-cell value: forbid on level mismatch, else the separable fit.
        # In "threshold" mode add fail_w per passing size/width/proportion factor
        # so the matching maximises passes first, continuous fit only as tiebreak.
        base: list[list[float]] = [
            [
                self._collapse_value(lf, code, levels_of[i], prog, objective, forbid, fail_w)
                for code in slots
            ]
            for i, lf in enumerate(supply)
        ]

        if not adjacency:
            for r, c in self._best_assignment(base):
                if base[r][c] > forbid:
                    supply[r].type = slots[c]
            return

        # Adjacency relaxation on the pre-merge base graph (built above, fixed
        # geometry). A satisfied adjacency is worth fail_w — one avoided fail,
        # the same unit as a passing factor — so both are minimised jointly.
        code_adj = {code: prog[code].adjacency for code in set(slots)}

        prev_labels: list[str | None] = None  # type: ignore[assignment]
        for _ in range(max(1, iters)):
            quality = [list(row) for row in base]
            for i, lf in enumerate(supply):
                G = graphs[levels_of[i]]
                for j, code in enumerate(slots):
                    if quality[i][j] <= forbid:
                        continue
                    sat = sum(
                        1
                        for ac in code_adj[code]
                        if graph_mod.has_adjacency(lf, ac, G)
                    )
                    quality[i][j] += fail_w * sat
            assign = self._best_assignment(quality)
            new_labels: list[str | None] = [lf.type for lf in supply]
            for r, c in assign:
                if quality[r][c] > forbid:
                    new_labels[r] = slots[c]
            # Apply synchronously so the next pass reads the updated neighbours.
            for lf, lab in zip(supply, new_labels):
                lf.type = lab
            if new_labels == prev_labels:
                break
            prev_labels = new_labels

        if local_search:
            self._two_opt_adjacency_polish(
                supply,
                levels_of,
                graphs,
                code_adj,
                prog,
                objective,
                forbid,
                fail_w,
                max_passes=local_search_passes,
            )

    def _public_access_pins(
        self, root: Node, graphs: list, lvls: list, room_codes: set
    ) -> set[int]:
        """id()s of room leaves to hold fixed so the building keeps street access
        across a collapse. If a ground circulation leaf already gives public
        access it is invariant (circulation is never relabelled) — return empty.
        Otherwise, for each outside leaf that provides public access solely via an
        l/k ROOM neighbour (no circulation fallback), pin one such neighbour."""
        for lvl in lvls:
            for lf in lvl.leaves():
                if (
                    lf.type
                    and lf.type[0].lower() == "c"
                    and self._public_access(lf, root) is not None
                ):
                    return set()
        pins: set[int] = set()
        for li, lvl in enumerate(lvls):
            G = graphs[li]
            for lf in lvl.leaves():
                if not G.has_node(lf):
                    continue
                if not self._public_access_outside(lf, G, root):
                    continue
                nbs = list(G.neighbors(lf))
                if any(nb.type and nb.type[0].lower() == "c" for nb in nbs):
                    continue  # circulation neighbour keeps access invariant
                for nb in nbs:
                    if nb.type in room_codes and nb.type[0].lower() in ("l", "k"):
                        pins.add(id(nb))
                        break
        return pins

    def collapse_finish(self, root: Node, **kw) -> tuple[Node, int, int, bool]:
        """Keep-better finish-time collapse: apply :meth:`collapse_global` to a
        copy and return it only if it does not INCREASE the fail count, else the
        original — a strictly monotone polish (safety belt; collapse_global is
        already monotone on the harbor-house set but not proven so in general).

        Returns ``(tree, base_fails, collapsed_fails, applied)``. Both the input
        and returned trees are UNMERGED — scoring is done on throwaway deepcopies
        because ``score_with_fails`` merges the tree in place."""
        import copy

        base_fails = len(self.score_with_fails(copy.deepcopy(root))[1])
        cand = copy.deepcopy(root)
        self.collapse_global(cand, **kw)
        cand_fails = len(self.score_with_fails(copy.deepcopy(cand))[1])
        if cand_fails <= base_fails:
            return cand, base_fails, cand_fails, True
        return copy.deepcopy(root), base_fails, cand_fails, False

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
        if param == "width" and sp is not None:
            # Derive a sane width from size and proportion rather than
            # falling back to width_inside [4.0, 1.0], which is impossible
            # for small programme spaces (e.g. a 3 m² WC).
            size = sp.get("size") or self.conf("size_inside") or _PARAM_FALLBACKS["size"]
            proportion = sp.get("proportion") or self.conf("proportion_inside") or _PARAM_FALLBACKS["proportion"]
            target = (size[0] / proportion[0]) ** 0.5
            sigma = max(0.1, target * size[1] / (2.0 * size[0]))
            return [target, sigma]
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
            co_type = self._leaf_co_type(leaf)
            if co_type:
                # 1s3: A/B-measured (DESIGN.md §33) — the precision-weighted
                # combination (one intermediate, narrower target) beat both
                # the naive max/min hack AND the max-of-two mixture on the
                # health-centre programme; the mixture's permissiveness (any
                # width/aspect satisfying the WEAKER of the two codes scores
                # 1.0) under-constrains the search on tightly-packed
                # programmes even though it is the more appealing model.
                co_params = self.get_space_params(co_type, "proportion")
                params = _gaussian_product(params[0], params[1],
                                           co_params[0], co_params[1])
        aspect = geometry.aspect(leaf)
        return _clipped_gaussian(aspect, params[0], params[1], "below")

    def quality_size(self, leaf: Node) -> float:
        t0 = _t0(leaf)
        if t0 in ("o", "s"):
            return 1.0
        if t0 == "c":
            params = self.conf("size_circulation")
        else:
            params = self.get_space_params(leaf.type, "size")
        target, sigma = params[0], params[1]
        if t0 != "c" and target > 0:
            k = 1
            if self._leaf_sharing:
                # erc.3: a shared leaf holds k same-code rooms; centre the
                # Gaussian on k×target (k = leaf's explicit, type-guarded
                # share) and scale sigma by k so the *fractional* size
                # tolerance is preserved. An undersize shared leaf now lands
                # a (light) size fail here instead of a (heavy) missing fail
                # in the count check — the §13.3 leak fix.
                from . import graph as _graph
                k = _graph.leaf_share(leaf, self._max_share)
            co_type = None if k > 1 else self._leaf_co_type(leaf)
            if k > 1:
                target, sigma = target * k, sigma * k
            elif co_type:
                # 1s3 §26 path b: a fused leaf's floor area serves BOTH codes'
                # requirements at once — additive, the same operation as
                # leaf-sharing's k×target sum (k identical terms), here with
                # 2 different terms. A leaf never carries both a live share>1
                # and a live co_type (construction never stamps both).
                co_params = self.get_space_params(co_type, "size")
                target, sigma = target + co_params[0], sigma + co_params[1]
        return gaussian(geometry.area(leaf), 1.0, target, sigma)

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
            co_type = self._leaf_co_type(leaf)
            if co_type:
                # 1s3: precision-weighted, same reasoning as quality_proportion
                # above.
                co_params = self.get_space_params(co_type, "width")
                params = _gaussian_product(params[0], params[1],
                                           co_params[0], co_params[1])
        width = geometry.length_narrowest(leaf)
        return _clipped_gaussian(width, params[0], params[1], "above")

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

    def _edge_cap(self, *leaves: Node) -> float:
        """Wall-length cap before 'edge too long' fires (erc.hph/§13.7).

        Default flat 8 m, as Urb. A shared leaf (share=k, type-guarded) holds k
        same-code rooms, so its walls run ~k× longer purely as a leaf-sharing
        representation artifact — the same leak §13.3 closed for size. Scale the
        cap by the largest share among the adjoining leaves, mirroring
        quality_size's k×target. Non-shared leaves keep the flat cap, so genuine
        narrow/oversize pathologies stay flagged."""
        cap = 8.0
        if self._leaf_sharing and self._share_edge_cap:
            from . import graph as _graph
            k = max(_graph.leaf_share(leaf, self._max_share) for leaf in leaves)
            if k > 1:
                cap *= k
        return cap

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
        if width > self._edge_cap(a, b) and rate > 0.0:
            fail(f"{dom_mod.level_of(a)}/{a.id} {b.id} edge too long")
        return rate * width * height

    def outside_edge_cost(self, leaf: Node, fail) -> float:
        """Plot-boundary cost for a leaf's external edges
        (``Leaf.pm::calculate_outside_edge_cost``)."""
        rate = self.cost("boundary") if dom_mod.is_outside(leaf) else self.cost("boundary_wall")
        cap = self._edge_cap(leaf)
        length = 0.0
        for e in range(4):
            if geometry.boundary_id(leaf, e) not in geometry._EXTERNAL:
                continue
            edge_len = geometry.edge_length(leaf, e)
            length += edge_len
            if dom_mod.is_outside(leaf):
                continue
            if edge_len > cap:
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
        score, _, _ = self._evaluate_full(root)
        return score

    def score_with_fails(self, root: Node) -> tuple[float, tuple[str, ...]]:
        """Same as ``evaluate`` but also returns the sorted failure strings."""
        score, fails, _ = self._evaluate_full(root)
        return score, fails

    def score_with_grade(
        self, root: Node
    ) -> tuple[float, tuple[str, ...], float]:
        """``score_with_fails`` plus the graded proximity scalar (§11.4).

        The grade is a continuous secondary signal for the outer comparator only;
        it leaves ``score`` and the fail count untouched (and so the inner-loop
        0.5^n cliff protection, §5.4, intact).
        """
        return self._evaluate_full(root, want_grade=True)

    def _evaluate_full(
        self, root: Node, want_grade: bool = False
    ) -> tuple[float, tuple[str, ...], float]:
        from . import graph as graph_mod

        geometry.clear_cache()
        # homemaker-py-r5a: canonicalise stale share stamps before any
        # relabelling pass (collapse_superposition/collapse_global) or read
        # can resurrect one -- see dom.canonicalize_shares.
        dom_mod.canonicalize_shares(root)

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

        # 9o5 COLLAPSE: re-type superposed leaves to their best in-class usage
        # before any check (no-op unless superposition is on and a class exists).
        if self._superpose:
            self.collapse_superposition(root)

        # homemaker-py-qpk: IN-SEARCH global collapse (DESIGN.md §17 follow-on).
        # Runs before any check, same as collapse_superposition above, so counts/
        # adjacency/quality downstream see the collapsed (relabelled) types. Uses
        # its own graph build (fixed geometry, only labels move) — safe to call
        # on the unmerged tree, exactly as collapse_global's finish-time use does.
        if self._collapse_insearch:
            self.collapse_global(
                root,
                adjacency=self._collapse_insearch_adjacency,
                objective="threshold",
                preserve_public_access=True,
                iters=self._collapse_insearch_iters,
            )

        # --- Phase 1: UNMERGED tree checks ---
        check_fails, missing = graph_mod.check_space_counts(
            root, programme, self._leaf_sharing, self._max_share,
            self._multi_use, self.colocate_pairs())
        failures.extend(check_fails)

        self.preprocess_building(root)
        _, graph_circ_pre = graph_mod.build_graphs_with_circ(
            root, self.conf("door_width") or 1.2, failures.append
        )

        graph_base_pre = graph_mod.build_graphs(root, self.conf("door_width") or 1.2)

        failures.extend(graph_mod.check_adjacency(
            root, programme, graph_base_pre, missing,
            self._multi_use, self.colocate_pairs()))
        failures.extend(graph_mod.check_level_constraints(
            root, programme, missing, self._multi_use, self.colocate_pairs()))
        failures.extend(graph_mod.check_vertical_connectivity(
            root, programme, missing, self._multi_use, self.colocate_pairs()))

        # --- Phase 2: MERGED tree ---
        dom_mod.merge_divided(root)
        geometry.clear_cache()  # mirror Perl Merge_Divided → Clean_Cache

        _, graph_circ = graph_mod.build_graphs_with_circ(
            root, self.conf("door_width") or 1.2, failures.append
        )
        graph_base = graph_mod.build_graphs(root, self.conf("door_width") or 1.2)

        cost = self.plot_cost(root)
        value = 0.0
        grade = 0.0
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
            if want_grade and not self._conn_grade:  # §11.4 signal; off by default
                for le in se.leaves:
                    grade += _leaf_grade(le.factors)

        # §18 (homemaker-py-qi6): repurpose the grade channel for the graded
        # circulation-connectivity signal — sum of per-level largest-circ-component
        # fractions, higher when circulation is closer to a single connected spine.
        # Secondary comparator key only; score and fail count are untouched.
        if want_grade and self._conn_grade:
            for gc in graph_circ:
                grade += graph_mod.circulation_connectivity(gc)

        building_factor = self.evaluate_building(root, tracking)
        value *= building_factor

        # 0.5^n failure penalty (programme-driven mode, not 0.1^n)
        value *= 0.5 ** len(failures)

        score = value / cost if cost != 0.0 else 0.0
        return score, tuple(sorted(failures)), grade

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
                co_locate=list(c.get("co_locate") or []),
                has_size="size" in c,
                has_width="width" in c,
                has_proportion="proportion" in c,
            )
        self._programme_cache = reqs

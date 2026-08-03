"""Otten/Stockmeyer shape-curve DP: exact size/width/proportion feasibility
for a frozen slicing-tree topology, in one bottom-up pass.

Promoted from ``experiments/shapecurve_spike.py`` (homemaker-py-2g7.4,
DESIGN.md §37.2 — validated PASS: 99% agreement vs shape-fail-minimising NM
on harbor-house-l0, 0 false negatives, ~97x speedup) for use as
``driver._evaluate``'s NM warm-start (homemaker-py-6xh, DESIGN.md §37.4).

The inner loop answers "does some equal-offset ratio assignment clear the
size/width/proportion FAIL_THRESHOLD for every leaf" by an 80-200-eval
Nelder-Mead search per topology. This DP answers the same question exactly:
each leaf's feasible (width, height) region is bounded by an area hyperbola
(``quality_size``), a min-width line (``quality_width``), and an aspect-ratio
wedge (``quality_proportion``) — FAIL_THRESHOLD-inversions of the Gaussian/
clipped-Gaussian factors in ``fitness.py`` (see ``leaf_constraints``). These
per-leaf regions compose bottom-up through the slicing tree: a node's cut
ALWAYS sums its two children's contributions into the node's own "w"
(edge0+edge2) dimension, with "h" (edge1+edge3) the shared/cross dimension —
a fixed convention of ``geometry.py``'s division formula, no per-node
ambiguity. The only variable is which of a CHILD's own (w, h) plays which
role, an EXACT function of that child's ``rotation`` parity (``_child_contrib``).

Explicit scope (see ``eligible``, and DESIGN.md §37.2/§37 point 2):

  * Only size/width/proportion is modelled — crinkliness, access, adjacency,
    level/vertical connectivity are graph/topology terms, not per-leaf shape.
  * Every quad (leaf or internal) is approximated by a rectangle with the
    same edge-length-derived (w, h) as ``geometry.aspect`` uses —
    ``(edge0+edge2)/2`` and ``(edge1+edge3)/2`` — exact only for a true
    rectangle/parallelogram. Rotation-invariant by construction (unlike a
    global-axis bounding box); a residual ~7-12% rectangle-vs-true-skewed-
    quad approximation error remains, quantified in DESIGN.md §37.2.
  * Composition (which of a child's local w/h sums into its parent's w) is an
    exact algebraic identity determined purely by ``child.rotation % 2`` (see
    ``_child_contrib``) — not measured or approximated.
  * ``leaf_sharing``/``co_type`` (multi-use leaves) target-adjustment is NOT
    modelled — ``leaf_constraints`` uses each leaf's own type's base params
    only. ``eligible`` excludes runs using either.
  * Only a single storey is modelled: ``solve`` writes ``division`` on every
    divided node under the given level root unconditionally, with no notion
    of upper-storey ``below``-inherited (wall-stacked) fixed splits. Calling
    it on a multi-storey tree would corrupt wall-stacking. ``eligible``
    excludes multi-storey topologies (``len(dom.levels(root)) > 1``).
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import numpy as np

from homemaker_layout import dom as dom_mod
from homemaker_layout import geometry

# sqrt(2*ln(10)): FAIL_THRESHOLD=0.1 inversion of a unit-height Gaussian,
# gaussian(x,1,target,sigma) >= 0.1  <=>  |x-target| <= K*sigma.
_K = math.sqrt(2.0 * math.log(10.0))

Interval = tuple[float, float] | None  # None = infeasible


def eligible(root: dom_mod.Node, leaf_sharing: bool = False,
             superpose: bool = False, max_share: int | None = None,
             multi_use: bool = False) -> bool:
    """Is ``root`` inside this DP's validated scope for ``solve``?

    Single storey only (no ``below``-inherited wall-stacking to model) and
    none of ``leaf_sharing``/``superpose``/``max_share``/``multi_use`` (none
    of which ``leaf_constraints`` models). See the module docstring.
    """
    return (len(dom_mod.levels(root)) == 1
            and not leaf_sharing and not superpose
            and max_share is None and not multi_use)


def _interval_add(a: Interval, b: Interval) -> Interval:
    if a is None or b is None:
        return None
    return (a[0] + b[0], a[1] + b[1])


# --------------------------------------------------------------------------- #
# Per-leaf feasible region (exact closed form; FAIL_THRESHOLD inversion of
# fitness.py's quality_size/quality_width/quality_proportion).
# --------------------------------------------------------------------------- #


@dataclass
class LeafBounds:
    amin: float
    amax: float
    wmin: float
    rmax: float  # max aspect ratio (>= 1)

    def h_range(self, w: float) -> Interval:
        if w < self.wmin - 1e-12:
            return None
        lo = self.wmin
        if self.amin > 0:
            lo = max(lo, self.amin / w)
        lo = max(lo, w / self.rmax)
        hi = w * self.rmax
        if self.amax < math.inf:
            hi = min(hi, self.amax / w)
        if lo > hi + 1e-12:
            return None
        return (lo, hi)

    def w_range(self, h: float) -> Interval:
        # symmetric in (w, h) -- same box+hyperbola+wedge shape.
        return self.h_range(h)

    def range_grid(self, grid: np.ndarray) -> list[Interval]:
        """Vectorised ``h_range``/``w_range`` (symmetric) over a whole grid."""
        lo = np.maximum(self.wmin, grid / self.rmax)
        if self.amin > 0:
            lo = np.maximum(lo, self.amin / grid)
        hi = grid * self.rmax
        if self.amax < math.inf:
            hi = np.minimum(hi, self.amax / grid)
        feasible = (grid >= self.wmin - 1e-12) & (lo <= hi + 1e-12)
        return [(float(lo[i]), float(hi[i])) if feasible[i] else None for i in range(len(grid))]


def leaf_constraints(fit, leaf: dom_mod.Node) -> LeafBounds:
    """FAIL_THRESHOLD-inverted (amin, amax, wmin, rmax) for one leaf.

    Mirrors the branching of ``Fitness.quality_size``/``quality_width``/
    ``quality_proportion`` (fitness.py) but returns the (target, sigma)-derived
    hard bounds instead of evaluating a Gaussian against actual geometry.
    Ignores leaf-sharing/co_type target adjustment (see module docstring).
    """
    t0 = leaf.type[0].lower() if leaf.type else ""

    # --- size -> (amin, amax) ---
    if t0 in ("o", "s"):
        amin, amax = 0.0, math.inf
    else:
        params = fit.conf("size_circulation") if t0 == "c" else fit.get_space_params(leaf.type, "size")
        target, sigma = params[0], params[1]
        # NB: quality_size's ``target > 0`` gate governs only the leaf-sharing/
        # co_type k-scaling of (target, sigma) (not modelled here, see module
        # docstring) -- the underlying gaussian(area, target, sigma) test
        # always applies, including target==0 (e.g. size_circulation's [0.0,
        # 14.0] default: a real one-sided "as small as possible" constraint,
        # not "unconstrained").
        amin, amax = max(0.0, target - _K * sigma), target + _K * sigma

    # --- width -> wmin ---
    if (
        t0 in ("o", "s")
        and not dom_mod.is_covered(leaf)
        and not dom_mod.is_supported(leaf)
        and dom_mod.level_of(leaf)
    ):
        wmin = 0.0
    else:
        if t0 in ("o", "s"):
            params = fit.conf("width_outside")
        elif t0 == "c":
            params = fit.conf("width_circulation")
        else:
            params = fit.get_space_params(leaf.type, "width")
        target, sigma = params[0], params[1]
        wmin = max(0.0, target - _K * sigma)

    # --- proportion -> rmax ---
    if t0 in ("o", "s"):
        params = fit.conf("proportion_outside")
    elif t0 == "c":
        params = fit.conf("proportion_circulation")
    else:
        params = fit.get_space_params(leaf.type, "proportion")
    target, sigma = params[0], params[1]
    rmax = max(1.0 + 1e-9, target + _K * sigma)

    return LeafBounds(amin=amin, amax=amax, wmin=wmin, rmax=rmax)


# --------------------------------------------------------------------------- #
# Local-edge-length dimensions + EXACT rotation-parity composition.
#
# NB: ``geometry.coordinate()`` applies a node's OWN ``rotation`` field even
# when reading corners it inherited from its parent -- a node with odd
# rotation has its local edge0/edge2 pair correspond to its PARENT's
# edge1/edge3 pair instead of edge0/edge2 (rotation parity selects between a
# quad's two possible opposite-edge pairings; ``operators.mutate_divide``
# randomises this on every newly-divided node, so it's common, not an edge
# case). This is an exact algebraic identity, not something to measure or
# approximate: ``left.w + right.h == parent.w`` whenever ``left.rotation`` is
# even and ``right.rotation`` is odd (and the symmetric case generally), for
# ANY topology, independent of skew or global orientation. ``_child_contrib``
# below applies this directly. See DESIGN.md §37.2 "Correction 2" for the
# validation history of this rule.
# --------------------------------------------------------------------------- #


def _dims(n: dom_mod.Node) -> tuple[float, float]:
    """Rotation-invariant (w, h) of a quad from its own edge lengths (mirrors
    the (edge0+edge2) vs (edge1+edge3) pairing ``geometry.aspect`` uses)."""
    w = (geometry.edge_length(n, 0) + geometry.edge_length(n, 2)) / 2
    h = (geometry.edge_length(n, 1) + geometry.edge_length(n, 3)) / 2
    return (w, h)


# --------------------------------------------------------------------------- #
# The DP itself
# --------------------------------------------------------------------------- #


@dataclass
class Curve:
    """A node's feasible region, both ways: w_of_h[i] is the feasible w-range
    at h=grid[i]; h_of_w[j] is the feasible h-range at w=grid[j]. Same shared
    grid at every node, so composition needs no cross-node interpolation."""

    w_of_h: list[Interval]
    h_of_w: list[Interval]


def _interp_range(grid: np.ndarray, arr: list[Interval], x: float) -> Interval:
    if x <= grid[0]:
        return arr[0]
    if x >= grid[-1]:
        return arr[-1]
    j = int(np.searchsorted(grid, x)) - 1
    j = max(0, min(j, len(grid) - 2))
    a, b = arr[j], arr[j + 1]
    if a is None or b is None:
        return a if x - grid[j] < grid[j + 1] - x else b
    t = (x - grid[j]) / (grid[j + 1] - grid[j])
    return (a[0] * (1 - t) + b[0] * t, a[1] * (1 - t) + b[1] * t)


def _invert(grid: np.ndarray, arr: list[Interval]) -> list[Interval]:
    """Given arr[i] = feasible cross-range at grid[i], return the inverse:
    inv[j] = {y : arr's cross-range at y contains grid[j]}, assumed contiguous
    in y (true for the monotonic hyperbola/line/wedge-composed regions this
    DP produces). O(N^2) but numpy-vectorised (the naive Python double loop
    was ~70% of total DP wall-clock, profiled on harbor-house-l0)."""
    lo_arr = np.array([r[0] if r is not None else np.nan for r in arr])
    hi_arr = np.array([r[1] if r is not None else np.nan for r in arr])
    # mask[i, j]: does grid[i]'s range contain grid[j]?
    mask = (lo_arr[:, None] - 1e-9 <= grid[None, :]) & (hi_arr[:, None] + 1e-9 >= grid[None, :])
    grid_masked = np.where(mask, grid[:, None], np.nan)
    any_feasible = mask.any(axis=0)
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        inv_lo = np.where(any_feasible, np.nanmin(grid_masked, axis=0), np.nan)
        inv_hi = np.where(any_feasible, np.nanmax(grid_masked, axis=0), np.nan)
    return [None if np.isnan(lo) else (float(lo), float(hi)) for lo, hi in zip(inv_lo, inv_hi)]


def make_grid(wmax: float, n: int = 400, wmin: float = 0.1) -> np.ndarray:
    return np.geomspace(wmin, wmax, n)


def _child_contrib(curve: "Curve", rotation: int) -> list[Interval]:
    """The child's curve, reinterpreted in the PARENT's frame: parent.w is
    ALWAYS the sum of its two children's ``_child_contrib`` (see module
    docstring) -- even rotation contributes the child's own w_of_h directly;
    odd rotation swaps w<->h (child.h sums; child.w is the one that
    approximates the parent's shared/cross dimension)."""
    return curve.w_of_h if rotation % 2 == 0 else curve.h_of_w


@dataclass
class Feasibility:
    feasible: bool
    h_range_at_w: Interval
    w_range_at_h: Interval


def check_feasible(root_curve: Curve, grid: np.ndarray, w_plot: float, h_plot: float) -> Feasibility:
    hr = _interp_range(grid, root_curve.h_of_w, w_plot)
    wr = _interp_range(grid, root_curve.w_of_h, h_plot)
    ok_h = hr is not None and hr[0] - 1e-6 <= h_plot <= hr[1] + 1e-6
    ok_w = wr is not None and wr[0] - 1e-6 <= w_plot <= wr[1] + 1e-6
    return Feasibility(feasible=bool(ok_h or ok_w), h_range_at_w=hr, w_range_at_h=wr)


# --------------------------------------------------------------------------- #
# Top-down back-substitution: realise one feasible point as division ratios.
# --------------------------------------------------------------------------- #


def realise(
    node: dom_mod.Node,
    curves: dict[int, tuple[Curve, Curve]],
    grid: np.ndarray,
    w: float,
    h: float,
) -> None:
    """Write ``division`` on every free branch under ``node`` so its subtree
    realises the (w, h) target, given each descendant's precomputed curves.
    ``curves[id(n)] = (left_curve, right_curve)`` for internal nodes.

    ``node.w`` (the summed dimension) is ALWAYS ``w`` -- the parent-child cut
    convention is fixed (see module docstring), not orientation-dependent.
    Only each CHILD's rotation parity determines which of ITS OWN (w, h) the
    allocated share becomes: even rotation -> child's own w; odd rotation ->
    child's own h (the two are swapped for that recursive call).
    """
    if not node.divided:
        return
    cl, cr = curves[id(node)]
    contrib_l = _child_contrib(cl, node.left.rotation)
    contrib_r = _child_contrib(cr, node.right.rotation)
    rl = _interp_range(grid, contrib_l, h)
    rr = _interp_range(grid, contrib_r, h)
    lo = max(rl[0], w - rr[1])
    hi = min(rl[1], w - rr[0])
    wl = min(max((lo + hi) / 2.0, rl[0]), rl[1])
    wl = min(max(wl, w - rr[1]), w - rr[0])
    wr = w - wl
    t = wl / w if w > 0 else 0.5
    # _interp_range's interpolation branch returns numpy float64 (grid is a
    # numpy array); dom.dumps (yaml.safe_dump) cannot serialise those, so
    # every division written here must be a plain Python float.
    node.division = [float(t), float(t)]
    if node.left.rotation % 2 == 0:
        realise(node.left, curves, grid, wl, h)
    else:
        realise(node.left, curves, grid, h, wl)
    if node.right.rotation % 2 == 0:
        realise(node.right, curves, grid, wr, h)
    else:
        realise(node.right, curves, grid, h, wr)


def build_curves_with_children(
    node: dom_mod.Node, fit, grid: np.ndarray,
    out: dict[int, tuple[Curve, Curve]],
) -> Curve:
    """Bottom-up: leaf curves are exact closed forms; internal nodes compose
    on ``grid`` via the EXACT rotation-parity rule (``_child_contrib``), also
    recording each internal node's (left, right) curves in ``out`` for
    ``realise`` to consume."""
    if not node.divided:
        b = leaf_constraints(fit, node)
        w_of_h = h_of_w = b.range_grid(grid)
        return Curve(w_of_h=w_of_h, h_of_w=h_of_w)

    cl = build_curves_with_children(node.left, fit, grid, out)
    cr = build_curves_with_children(node.right, fit, grid, out)
    out[id(node)] = (cl, cr)
    contrib_l = _child_contrib(cl, node.left.rotation)
    contrib_r = _child_contrib(cr, node.right.rotation)
    w_of_h = [_interval_add(contrib_l[i], contrib_r[i]) for i in range(len(grid))]
    h_of_w = _invert(grid, w_of_h)
    return Curve(w_of_h=w_of_h, h_of_w=h_of_w)


def _check(level_root: dom_mod.Node, fit, grid_n: int) -> tuple[
        Feasibility, dict[int, tuple[Curve, Curve]], np.ndarray, float, float]:
    w_plot, h_plot = _dims(level_root)
    grid = make_grid(max(w_plot, h_plot) * 1.2, n=grid_n)
    curves_by_node: dict[int, tuple[Curve, Curve]] = {}
    root_curve = build_curves_with_children(level_root, fit, grid, curves_by_node)
    feas = check_feasible(root_curve, grid, w_plot, h_plot)
    return feas, curves_by_node, grid, w_plot, h_plot


def is_feasible(level_root: dom_mod.Node, fit, grid_n: int = 150) -> bool:
    """Read-only DP feasibility verdict: does some equal-offset ratio
    assignment clear the size/width/proportion FAIL_THRESHOLD for every leaf?

    Unlike :func:`solve`, never writes ``division`` — the hard-prune caller
    (``driver._evaluate``, homemaker-py-wkh) needs the boolean verdict alone,
    without the warm-start's tree mutation (kept a strictly separate code path
    so the two experimental flags, ``shapecurve_prune``/``shapecurve_warmstart``,
    compose cleanly and can be A/B'd independently)."""
    feas, *_ = _check(level_root, fit, grid_n)
    return feas.feasible


def solve(level_root: dom_mod.Node, fit, grid_n: int = 150) -> tuple[bool, dict]:
    """End-to-end: compute plot dims, build curves, check root feasibility,
    and (if feasible) write realising ratios in place. Returns (feasible,
    info) where info carries timing-relevant intermediates for the caller.

    ``level_root`` must be a single storey (see ``eligible``) — the DP has no
    notion of upper-storey ``below``-inherited fixed splits and will
    overwrite ``division`` unconditionally on every divided node it walks.
    """
    feas, curves_by_node, grid, w_plot, h_plot = _check(level_root, fit, grid_n)
    if feas.feasible:
        realise(level_root, curves_by_node, grid, w_plot, h_plot)
        geometry.clear_cache()
    return feas.feasible, {
        "w_plot": w_plot, "h_plot": h_plot,
        "grid": grid, "h_range_at_w": feas.h_range_at_w, "w_range_at_h": feas.w_range_at_h,
    }

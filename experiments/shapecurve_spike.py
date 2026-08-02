"""Spike (homemaker-py-2g7.4): Otten/Stockmeyer shape-curve DP vs nm_search.

Motivation (DESIGN.md §37, plan point 2): the inner loop answers "does some
equal-offset ratio assignment clear the size/width/proportion FAIL_THRESHOLD
for every leaf" by an 80-200 eval Nelder-Mead search per topology. The
classic slicing-floorplan result answers the size/width/proportion family of
this question EXACTLY in one bottom-up pass: each leaf's feasible (width,
height) region is bounded by an area hyperbola (``quality_size``), a min-width
line (``quality_width``), and an aspect-ratio wedge (``quality_proportion``) --
all three are FAIL_THRESHOLD-inversions of the Gaussian/clipped-Gaussian
factors in ``fitness.py`` (see ``leaf_constraints`` below). These per-leaf
regions compose bottom-up through the slicing tree: a "width-split" node
(children share height, widths sum) or "height-split" node (children share
width, heights sum) -- see ``_orientation``.

Approximations made explicit (the plan's caveats, DESIGN.md §37 point 2):

  * Every quad (leaf or internal) is approximated by its axis-aligned
    bounding-box (w, h) -- exact only for a true rectangle; harbor-house-l0's
    plot is a near-rectangular trapezoid (DESIGN.md says "harbor plot is a
    near-rect quad"), so this is the intended first target, not a general
    solution for skew quads.
  * A node's cut orientation (does it split width or height?) is measured
    once from the ACTUAL geometry at ratio=0.5 baseline, not derived from
    ``rotation`` symbolically -- robust to any rotation convention, but a
    property of the *frozen topology*, computed once, not re-derived by the
    DP itself.
  * Leaf curves are EXACT closed forms (hyperbola/line/wedge intersection --
    no discretisation error). Internal-node composition is done on a shared
    discretised grid (log-spaced) with linear interpolation -- this is where
    approximation error enters, and is quantified in ``validate.py``.
  * ``leaf_sharing``/``co_type`` (multi-use leaves) target-adjustment is NOT
    modelled -- ``leaf_constraints`` uses each leaf's own type's base params
    only. harbor-house-l0's programme does not exercise these, so this is a
    scoping simplification, not a validated-safe omission for programmes that
    do.

Only the size/width/proportion family is modelled -- crinkliness, access,
adjacency, level/vertical connectivity are graph/topology terms, not per-leaf
shape, and are explicitly out of scope (DESIGN.md §37 point 2 caveat).
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
# Bounding-box geometry + cut-orientation detection (rectangular approximation)
# --------------------------------------------------------------------------- #


def _bbox(n: dom_mod.Node) -> tuple[float, float]:
    """Axis-aligned bounding-box (w, h) of a quad's 4 corners."""
    xs = [geometry.coordinate(n, i)[0] for i in range(4)]
    ys = [geometry.coordinate(n, i)[1] for i in range(4)]
    return (max(xs) - min(xs), max(ys) - min(ys))


def _orientation(node: dom_mod.Node) -> str:
    """'w' (width-split, children share height) or 'h' (height-split),
    measured from the actual baseline geometry -- see module docstring."""
    bw, bh = _bbox(node)
    lw, lh = _bbox(node.left)
    rw, rh = _bbox(node.right)
    err_w = abs((lw + rw) - bw)
    err_h = abs((lh + rh) - bh)
    return "w" if err_w <= err_h else "h"


def annotate_orientations(level_root: dom_mod.Node) -> dict[int, str]:
    """Baseline-geometry orientation per internal node, keyed by id(node).

    Sets every free branch's division to [0.5, 0.5] on the LIVE tree (matching
    the inner loop's cold-start convention), clears the geometry cache, then
    measures. Caller must re-clear the cache afterwards if it goes on to use
    different ratios (the DP itself never reads real coordinates again after
    this call -- only the plot bbox, computed separately).
    """
    from homemaker_layout import solver

    for b in solver._branches(level_root):
        if b.below is None or not b.below.divided:
            b.division = [0.5, 0.5]
    geometry.clear_cache()

    orientations: dict[int, str] = {}

    def _walk(n: dom_mod.Node) -> None:
        if not n.divided:
            return
        orientations[id(n)] = _orientation(n)
        _walk(n.left)
        _walk(n.right)

    _walk(level_root)
    return orientations


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
    orientations: dict[int, str],
    grid: np.ndarray,
    w: float,
    h: float,
) -> None:
    """Write ``division`` on every free branch under ``node`` so its subtree
    realises the (w, h) target, given each descendant's precomputed curves.
    ``curves[id(n)] = (left_curve, right_curve)`` for internal nodes."""
    if not node.divided:
        return
    cl, cr = curves[id(node)]
    orient = orientations[id(node)]
    if orient == "w":
        rl = _interp_range(grid, cl.w_of_h, h)
        rr = _interp_range(grid, cr.w_of_h, h)
        lo = max(rl[0], w - rr[1])
        hi = min(rl[1], w - rr[0])
        wl = min(max((lo + hi) / 2.0, rl[0]), rl[1])
        wl = min(max(wl, w - rr[1]), w - rr[0])
        wr = w - wl
        t = wl / w if w > 0 else 0.5
        node.division = [t, t]
        realise(node.left, curves, orientations, grid, wl, h)
        realise(node.right, curves, orientations, grid, wr, h)
    else:
        rl = _interp_range(grid, cl.h_of_w, w)
        rr = _interp_range(grid, cr.h_of_w, w)
        lo = max(rl[0], h - rr[1])
        hi = min(rl[1], h - rr[0])
        hl = min(max((lo + hi) / 2.0, rl[0]), rl[1])
        hl = min(max(hl, h - rr[1]), h - rr[0])
        hr = h - hl
        t = hl / h if h > 0 else 0.5
        node.division = [t, t]
        realise(node.left, curves, orientations, grid, w, hl)
        realise(node.right, curves, orientations, grid, w, hr)


def build_curves_with_children(
    node: dom_mod.Node, fit, orientations: dict[int, str], grid: np.ndarray,
    out: dict[int, tuple[Curve, Curve]],
) -> Curve:
    """Like ``build_curves`` but also records each internal node's (left,
    right) curves in ``out`` for ``realise`` to consume."""
    if not node.divided:
        b = leaf_constraints(fit, node)
        w_of_h = h_of_w = b.range_grid(grid)
        return Curve(w_of_h=w_of_h, h_of_w=h_of_w)

    cl = build_curves_with_children(node.left, fit, orientations, grid, out)
    cr = build_curves_with_children(node.right, fit, orientations, grid, out)
    out[id(node)] = (cl, cr)
    orient = orientations[id(node)]
    if orient == "w":
        w_of_h = [_interval_add(cl.w_of_h[i], cr.w_of_h[i]) for i in range(len(grid))]
        h_of_w = _invert(grid, w_of_h)
    else:
        h_of_w = [_interval_add(cl.h_of_w[j], cr.h_of_w[j]) for j in range(len(grid))]
        w_of_h = _invert(grid, h_of_w)
    return Curve(w_of_h=w_of_h, h_of_w=h_of_w)


def solve(level_root: dom_mod.Node, fit, grid_n: int = 150) -> tuple[bool, dict]:
    """End-to-end: orientation-annotate, compute plot bbox, build curves,
    check root feasibility, and (if feasible) write realising ratios in
    place. Returns (feasible, info) where info carries timing-relevant
    intermediates for the caller."""
    orientations = annotate_orientations(level_root)
    w_plot, h_plot = _bbox(level_root)
    grid = make_grid(max(w_plot, h_plot) * 1.2, n=grid_n)

    curves_by_node: dict[int, tuple[Curve, Curve]] = {}
    root_curve = build_curves_with_children(level_root, fit, orientations, grid, curves_by_node)

    feas = check_feasible(root_curve, grid, w_plot, h_plot)
    if feas.feasible:
        realise(level_root, curves_by_node, orientations, grid, w_plot, h_plot)
        geometry.clear_cache()
    return feas.feasible, {
        "w_plot": w_plot, "h_plot": h_plot, "orientations": orientations,
        "grid": grid, "h_range_at_w": feas.h_range_at_w, "w_range_at_h": feas.w_range_at_h,
    }

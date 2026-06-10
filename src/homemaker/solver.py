"""Bottom-up division-ratio solver.

Given a *fixed* slicing topology (types, rotations, tree shape), solve every
free division ratio so that each programme leaf best meets its target area —
with soft, one-sided penalties for being too narrow or too elongated. This is
the inversion of Urb's top-down sizing: rooms declare targets, geometry follows.

Only generic leaves (circulation/outside/storage) and unconstrained types are
left to absorb the residual area, exactly as a real plan lets corridors flex.

A division is *free* only at the lowest storey where its tree path is divided;
higher storeys inherit that cut via Below-inheritance (see geometry.coordinate),
so their stored ratios are dead variables and must not be optimised.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

from . import geometry
from .dom import Node, levels
from .programme import SpaceReq

_EPS = 0.02  # keep cuts off the edges


def _branches(n: Node) -> list[Node]:
    if not n.divided:
        return []
    return [n] + _branches(n.left) + _branches(n.right)


def free_branches(root: Node) -> list[Node]:
    """Branches whose division actually drives geometry (not inherited)."""
    out: list[Node] = []
    for lvl in levels(root):
        for b in _branches(lvl):
            if b.below is None or not b.below.divided:
                out.append(b)
    return out


def _width(leaf: Node) -> float:
    l0 = geometry.edge_length(leaf, 0)
    l1 = geometry.edge_length(leaf, 1)
    l2 = geometry.edge_length(leaf, 2)
    l3 = geometry.edge_length(leaf, 3)
    return min((l0 + l2) / 2, (l1 + l3) / 2)


def _aspect(leaf: Node) -> float:
    l0 = geometry.edge_length(leaf, 0)
    l1 = geometry.edge_length(leaf, 1)
    l2 = geometry.edge_length(leaf, 2)
    l3 = geometry.edge_length(leaf, 3)
    a = (l0 + l2) / 2
    b = (l1 + l3) / 2
    if a <= 0 or b <= 0:
        return 1.0
    return max(a, b) / min(a, b)


def solve_ratios(
    root: Node,
    targets: dict[str, SpaceReq],
    *,
    strip: bool = True,
    perpendicular: bool = True,
    weight_width: float = 1.0,
    weight_proportion: float = 0.3,
    min_width_generic: float = 1.2,
    max_nfev: int = 4000,
):
    """Solve free division ratios in place. Returns the scipy result object.

    ``strip=True`` discards the existing ratios first (start from 0.5) — the
    honest test that sizes are recoverable from the programme alone.

    ``perpendicular=True`` ties the two ends of each cut (``a == b``), one DOF
    per branch, so cuts stay perpendicular to their walls (matches Urb's
    ``perpendicular`` quality and the slicing-tree model). ``min_width_generic``
    keeps unconstrained circulation/outside leaves from collapsing into slivers.
    """
    free = free_branches(root)
    if not free:
        return None

    if strip:
        for b in free:
            b.division = [0.5, 0.5]

    per = 1 if perpendicular else 2
    x0 = np.array(
        [b.division[0] for b in free] if perpendicular
        else [v for b in free for v in b.division],
        dtype=float,
    )

    all_leaves = [leaf for lvl in levels(root) for leaf in lvl.leaves()]

    def apply(x: np.ndarray) -> None:
        for j, b in enumerate(free):
            if perpendicular:
                b.division = [float(x[j]), float(x[j])]
            else:
                b.division = [float(x[2 * j]), float(x[2 * j + 1])]
        geometry.clear_cache()  # divisions changed; invalidate derived coords

    def residuals(x: np.ndarray) -> list[float]:
        apply(x)
        r: list[float] = []
        for leaf in all_leaves:
            req = targets.get(leaf.type)
            if req is not None:
                area = geometry.area(leaf)
                r.append((area - req.size) / req.size)
                if weight_width:
                    w = _width(leaf)
                    r.append(weight_width * min(0.0, (w - req.width) / req.width))
                if weight_proportion:
                    asp = _aspect(leaf)
                    r.append(weight_proportion * max(0.0, (asp - req.proportion) / req.proportion))
            elif min_width_generic:
                # keep circulation/outside from collapsing to slivers
                w = _width(leaf)
                r.append(min(0.0, (w - min_width_generic) / min_width_generic))
        return r

    res = least_squares(
        residuals, x0, bounds=(_EPS, 1 - _EPS), max_nfev=max_nfev, xtol=1e-10, ftol=1e-10
    )
    apply(res.x)
    return res


def area_report(root: Node, targets: dict[str, SpaceReq]) -> str:
    """Human-readable per-programme-leaf area vs target (for experiment output)."""
    rows = []
    for lvl_idx, lvl in enumerate(levels(root)):
        for leaf in lvl.leaves():
            if leaf.type in targets:
                req = targets[leaf.type]
                a = geometry.area(leaf)
                rows.append(
                    f"  {lvl_idx}/{leaf.id:6s} {leaf.type:4s} area={a:6.2f} "
                    f"target={req.size:6.2f} err={(a - req.size):+6.2f} "
                    f"w={_width(leaf):.2f}/{req.width:.2f} asp={_aspect(leaf):.2f}/{req.proportion:.2f}"
                )
    return "\n".join(rows)

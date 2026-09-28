"""Bottom-up division-ratio solver.

Given a *fixed* slicing topology (types, rotations, tree shape), solve every
free division ratio so that each programme leaf best meets its target area —
with soft, one-sided penalties for being too narrow or too elongated. This is
the inversion of Urb's top-down sizing: rooms declare targets, geometry follows.

Only generic leaves (circulation/outside/storage) and unconstrained types are
left to absorb the residual area, exactly as a real plan lets corridors flex --
but they flex down to their own DECLARED minimum width (``width_circulation`` /
``width_outside``), not to a number invented here; see ``_generic_min_width``.

A division is *free* only at the lowest storey where its tree path is divided;
higher storeys inherit that cut via Below-inheritance (see geometry.coordinate),
so their stored ratios are dead variables and must not be optimised.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import least_squares

from . import geometry
from .dom import Node, is_covered, is_supported, level_of, levels
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


def _generic_min_width(leaf: Node, conf: dict | None) -> float | None:
    """Declared minimum width for a generic leaf, or ``None`` where the
    objective has no width rule for it.

    ``quality_width`` reads ``width_outside`` / ``width_circulation`` from the
    same config the room targets come from, and exempts exactly one case: an
    outside leaf that is uncovered, unsupported and above ground -- a roof
    garden -- scores 1.0 whatever its width, so pinning it wide only spends
    degrees of freedom the rooms want. All three of those predicates read the
    tree ADDRESS, so a leaf's answer is fixed with the topology and can be
    computed once per solve (homemaker-py-r8c, DESIGN.md §39.76).
    """
    from .fitness import CONF_DEFAULTS, _generic_class

    cls = _generic_class(leaf)
    if cls not in ("o", "c"):
        return None
    if (cls == "o"
            and not is_covered(leaf)
            and not is_supported(leaf)
            and level_of(leaf)):
        return None
    key = "width_outside" if cls == "o" else "width_circulation"
    params = (conf or {}).get(key) or CONF_DEFAULTS.get(key)
    return float(params[0]) if params else None


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
    min_width_generic: float | None = None,
    conf: dict | None = None,
    max_nfev: int = 4000,
):
    """Solve free division ratios in place. Returns the scipy result object.

    ``strip=True`` discards the existing ratios first (start from 0.5) — the
    honest test that sizes are recoverable from the programme alone.

    ``perpendicular=True`` ties the two ends of each cut (``a == b``), one DOF
    per branch, so cuts stay perpendicular to their walls (matches Urb's
    ``perpendicular`` quality and the slicing-tree model).

    Unconstrained circulation/outside leaves are held at their DECLARED minimum
    width, read per class from ``conf`` (``width_circulation`` /
    ``width_outside``, falling back to ``fitness.CONF_DEFAULTS``) by
    ``_generic_min_width``. Until §39.76 they were held at one hard-coded 1.2 m
    for every class -- below BOTH declared thresholds, so the solved point
    routinely failed ``quality_width`` on the very leaves this term exists to
    protect: 41 width fails over the twelve corpus topologies, against 11 once
    the declaration is read (homemaker-py-r8c). Pass ``min_width_generic`` a
    float to restore one floor for every generic leaf, or ``0.0`` to drop the
    term entirely.
    """
    free = free_branches(root)
    if not free:
        return None

    if strip:
        for b in free:
            b.division = [0.5, 0.5]

    x0 = np.array(
        [b.division[0] for b in free] if perpendicular
        else [v for b in free for v in b.division],
        dtype=float,
    )

    all_leaves = [leaf for lvl in levels(root) for leaf in lvl.leaves()]
    # Address-fixed, so resolved once rather than per residual evaluation.
    gmin = {id(leaf): (min_width_generic if min_width_generic is not None
                       else _generic_min_width(leaf, conf))
            for leaf in all_leaves if leaf.type not in targets}

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
                    w = geometry.length_narrowest(leaf)
                    r.append(weight_width * min(0.0, (w - req.width) / req.width))
                if weight_proportion:
                    asp = _aspect(leaf)
                    r.append(weight_proportion * max(0.0, (asp - req.proportion) / req.proportion))
            else:
                # keep circulation/outside from collapsing to slivers
                t = gmin.get(id(leaf))
                if t:
                    w = geometry.length_narrowest(leaf)
                    r.append(min(0.0, (w - t) / t))
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
                    f"w={geometry.length_narrowest(leaf):.2f}/{req.width:.2f} "
                    f"asp={_aspect(leaf):.2f}/{req.proportion:.2f}"
                )
    return "\n".join(rows)

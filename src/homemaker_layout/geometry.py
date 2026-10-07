"""Faithful port of Urb's top-down quad geometry (``Urb::Quad``).

A leaf has *no* intrinsic dimensions: its corners are derived by walking up to
the level root, and — for upper storeys — across to the matching quad on the
level below (wall-stacking). Every function here mirrors the corresponding Perl
method so areas computed in Python match ``urb-fitness.pl`` to floating point.

Corner ids run anti-clockwise and are offset by the node's ``rotation``. A
division is a line between a point on edge (0->1), parameter ``division[0]``, and
a point on edge (3->2), parameter ``division[1]`` — independent params allow a
skewed (non-perpendicular) cut.
"""

from __future__ import annotations

import math
import os

from .dom import Node

Point = list[float]

# Memoisation of derived coordinates. The pull-based recursion mirrors Urb but,
# uncached, re-derives ancestor/below corners exponentially with depth. Urb
# itself caches in the node and clears via Clean_Cache(); we do the same with a
# module cache keyed by node identity. Callers that mutate divisions (the
# solver) must call clear_cache(); dom.load() clears it for a fresh tree.
_cache: dict = {}


def clear_cache() -> None:
    _cache.clear()


# --------------------------------------------------------------------------- #
# Orthogonal division (homemaker-py-32t, DESIGN.md §39.38)
# --------------------------------------------------------------------------- #
# A division carries TWO ratios, and this module's own docstring says the
# independent params "allow a skewed (non-perpendicular) cut". The port never
# uses the second: every write is ``division = [x, x]`` and the inner loop
# copies one optimiser variable into both slots. That equal-offset convention
# propagates the plot's skew into every leaf -- on a harbor-house plot that HAS
# a true right angle, zero of 52 usable leaves are square (§39.36).
#
# With this ON, ``division[1]`` is DERIVED rather than pinned: the cut is placed
# parallel or perpendicular to the plot's longest boundary (the owner's ruling),
# which is what Urb's lost ``Straighten()`` provided. Search dimensionality is
# unchanged -- still one free ratio per division -- because the second was never
# free to begin with.
#
# Default OFF. It changes the geometry of every layout, so it is a new objective
# under §39.32 and needs the corpus re-run before anything is compared to it.
#
# Read from the environment, not just set as a global, because the driver runs
# its evaluations in WORKER PROCESSES: a global flipped in the parent would not
# reach them, and the search would silently score under a different geometry
# than the one it was asked for. An env var crosses the fork, and lets a sweep
# select the objective without editing code:
#
#     HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/run_coldstart_baseline.py ...
#
# Tests set the module attribute directly, which still works.
ORTHOGONAL_DIVISION = os.environ.get("HOMEMAKER_ORTHOGONAL_DIVISION", "") == "1"


# --------------------------------------------------------------------------- #
# Native rectangle-frame trees (homemaker-py-8b2u.4, DESIGN.md §39.103)
# --------------------------------------------------------------------------- #
# A tree whose lowest root carries a `plot` is drawn here and not by the quad
# recursion below: the frame rectangle is split by each cut, and a leaf is its
# rectangle cropped to the plot -- a polygon of three or more corners, or
# nothing. Every function a scorer calls dispatches on `_native(n)`; the quad
# code underneath is untouched and still draws every v1 tree.
def _native(n: Node) -> "Node | None":
    """The lowest root of ``n``'s building if the tree is native, else None."""
    key = (id(n), "native?")
    hit = _cache.get(key)
    if hit is None:
        r = n
        while r.parent is not None:
            r = r.parent
        while r.below is not None:
            r = r.below
        hit = _cache[key] = (r if r.plot is not None else False)
    return hit or None


def _native_frame(g0: Node):
    """``(u, v, inner plot, frame box)`` for a native building."""
    key = (id(g0), "frame")
    hit = _cache.get(key)
    if hit is None:
        from . import cells

        u = _unit(g0.frame_u[0], g0.frame_u[1])
        v = (-u[1], u[0])
        inner = cells.inset(g0.plot, g0.wall_outer if g0.wall_outer is not None else 0.25)
        pu = [p[0] * u[0] + p[1] * u[1] for p in inner]
        pv = [p[0] * v[0] + p[1] * v[1] for p in inner]
        hit = _cache[key] = (u, v, inner, (min(pu), max(pu), min(pv), max(pv)))
    return hit


def _native_turn(n: Node) -> int:
    """Which corner of ``n``'s rectangle its cut starts from, 0..3 counting
    anticlockwise from (low u, low v) -- ``rotation`` accumulated down the
    tree exactly as the quad recursion accumulates it: a child's own corner 0
    is its parent's (turned) corner 0, and an upper-storey node takes the turn
    of the node below it, its own ``rotation`` being a dead field there too.
    """
    key = (id(n), "turn")
    hit = _cache.get(key)
    if hit is None:
        if n.below is not None:
            hit = _native_turn(n.below)
        else:
            base = 0 if n.parent is None else _native_turn(n.parent)
            hit = (base + n.rotation) % 4
        _cache[key] = hit
    return hit


def _native_cut(n: Node) -> "tuple[str, float, bool]":
    """``(axis, position, left is the low side)`` of the line across divided
    node ``n``: its own, or -- where the storey below is cut at this path --
    that storey's.

    Turn 0 starts on the low-v side and runs up: the line fixes u (`cut: v`),
    ``division[0]`` is measured from low u, and the left child is the low one.
    Turn 1 the same a quarter round: it fixes v, measured from low v. Turns 2
    and 3 are those two started from the opposite side, so the ratio counts
    down from the high end and the LEFT child is the high one.
    """
    key = (id(n), "cut")
    hit = _cache.get(key)
    if hit is None:
        if n.below is not None and n.below.divided:
            hit = _native_cut(n.below)
        else:
            turn = _native_turn(n)
            r = _native_rect(n)
            axis = "v" if turn % 2 == 0 else "u"
            lo, hi = (r[0], r[1]) if axis == "v" else (r[2], r[3])
            d = n.division[0] if turn < 2 else 1.0 - n.division[0]
            hit = (axis, lo + d * (hi - lo), turn < 2)
        _cache[key] = hit
    return hit


def _native_rect(n: Node) -> "tuple[float, float, float, float]":
    """``(u0, u1, v0, v1)`` of ``n`` in the frame."""
    key = (id(n), "rect")
    hit = _cache.get(key)
    if hit is None:
        if n.below is not None:
            hit = _native_rect(n.below)     # walls stack: the same piece of floor
        elif n.parent is None:
            hit = _native_frame(_native(n))[3]
        else:
            u0, u1, v0, v1 = _native_rect(n.parent)
            axis, s, left_low = _native_cut(n.parent)
            low = (n.position == "l") == left_low
            if axis == "u":                 # a line along u fixes v
                hit = (u0, u1, v0, s) if low else (u0, u1, s, v1)
            else:
                hit = (u0, s, v0, v1) if low else (s, u1, v0, v1)
        _cache[key] = hit
    return hit


def native_cut(n: Node) -> "tuple[str, float, bool]":
    """``(axis, at, left is low)`` of divided native node ``n`` as a v2 file
    states it: ``at`` a fraction of the node's rectangle across the cut."""
    axis, s, left_low = _native_cut(n)
    r = _native_rect(n)
    lo, hi = (r[0], r[1]) if axis == "v" else (r[2], r[3])
    return axis, (s - lo) / (hi - lo), left_low


def polygon(n: Node) -> "list[Point]":
    """The corners of ``n``, anticlockwise: four for a quad tree, three or more
    (or none, for a cell outside the plot) for a native one. Collinear vertices
    the plot carries -- a change of street/party status along a straight side --
    are kept."""
    key = (id(n), "poly")
    hit = _cache.get(key)
    if hit is None:
        g0 = _native(n)
        if g0 is None:
            hit = [coordinate(n, i) for i in range(4)]
        else:
            from . import cells

            u, v, inner, _ = _native_frame(g0)
            rect = _native_rect(n)
            hit = cells.clip(inner, rect, u, v)
            if hit:
                # Start the list where the quad recursion would: at the corner
                # this node's turn names. Nothing scored reads which corner is
                # first (§39.95), but the search's heuristics still do -- the
                # solver and the shape-curve DP take "edge 0" to be the side a
                # cut starts from -- and they should see a native cell the way
                # round they see a quad one.
                cu, cv = ((rect[0], rect[2]), (rect[1], rect[2]),
                          (rect[1], rect[3]), (rect[0], rect[3]))[_native_turn(n)]
                first = min(range(len(hit)), key=lambda i: (
                    (hit[i][0] * u[0] + hit[i][1] * u[1] - cu) ** 2
                    + (hit[i][0] * v[0] + hit[i][1] * v[1] - cv) ** 2))
                hit = hit[first:] + hit[:first]
        _cache[key] = hit
    return hit


def _native_rect_corners(n: Node) -> "list[Point]":
    """The four corners of ``n``'s rectangle in world coordinates, from the
    corner its turn names. What a VOID cell answers with when the search's
    heuristics ask where it is: it has no polygon, but it has a place, and a
    move that would bring it back onto the plot needs to know it."""
    u, v = _native_frame(_native(n))[:2]
    u0, u1, v0, v1 = _native_rect(n)
    c = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
    t = _native_turn(n)
    return [[a * u[0] + b * v[0], a * u[1] + b * v[1]] for a, b in c[t:] + c[:t]]


def mark_voids(root: Node) -> int:
    """Set ``void`` on every leaf of a native tree that crops to nothing, and
    clear it on the rest; returns how many there are. A quad tree has none.
    Geometry must be current (the scorer calls this right after clearing the
    cache), because a cut that moves can push a cell off the plot or back on.
    """
    from . import cells

    count = 0
    if root.plot is None:
        return 0
    lvl: "Node | None" = root
    while lvl is not None:
        stack = [lvl]
        while stack:
            n = stack.pop()
            if n.divided:
                stack += [n.left, n.right]
            else:
                n.void = cells.area(polygon(n)) < cells.EMPTY_AREA
                count += n.void
        lvl = lvl.above
    return count


def is_external(bid: str) -> bool:
    """Is this boundary id a side of the plot? 'a'..'d' in a quad tree; '#0',
    '#1', ... (the plot edge's index) in a native one, where a plot may have
    any number of sides and a letter would collide with a path."""
    return bid in _EXTERNAL or bid[:1] == "#"


def quad_corners(n: Node) -> "list[Point] | None":
    """The four corners of ``n`` if it is four-cornered, else None. Status
    vertices along a straight side do not count as corners. The stair rules
    are written for a rectangle-like core and ask this first."""
    if _native(n) is None:
        return [coordinate(n, i) for i in range(4)]
    from . import cells

    c = cells.corners(polygon(n))
    return c if len(c) == 4 else None


def _level_root_of(n: Node) -> Node:
    while n.parent is not None:
        n = n.parent
    return n


def _unit(ax: float, ay: float) -> "tuple[float, float]":
    d = math.sqrt(ax * ax + ay * ay)
    return (ax / d, ay / d) if d else (1.0, 0.0)


def _reference_axes(n: Node) -> "tuple[tuple[float, float], tuple[float, float]]":
    """The plot's two orthogonal directions, from its LONGEST boundary edge.

    The owner's rule is "parallel or perpendicular to one or more outside plot
    boundaries"; where a skew plot's boundaries disagree, the longest one wins.
    Cached per level root, since it depends only on the stored plot corners.
    """
    root = _level_root_of(n)
    key = (id(root), "axes")
    hit = _cache.get(key)
    if hit is not None:
        return hit
    g0 = _native(n)
    if g0 is not None:
        result = _native_frame(g0)[:2]
        _cache[key] = result
        return result
    best = max(range(4), key=lambda i: edge_length(root, i))
    a, b = coordinate(root, best), coordinate(root, (best + 1) % 4)
    u = _unit(b[0] - a[0], b[1] - a[1])
    result = (u, (-u[1], u[0]))
    _cache[key] = result
    return result


def _orthogonal_b(n: Node) -> Point:
    """End 'b' placed so the cut runs along a plot axis, given end 'a'.

    Which of the two axes is chosen must NOT depend on the division ratios: the
    cut spans edge(0,1)->edge(3,2), so it runs along edges (1,2) and (0,3), and
    the axis nearer the mean of those two edge directions is a property of the
    node's own corners alone. Choosing by the CURRENT cut instead would let the
    axis flip as the inner loop moves ``division[0]``, making the objective
    discontinuous under Nelder-Mead/CMA. Measured over 532 corpus divisions the
    two rules pick the same axis every time, so this costs nothing.
    """
    a = coord_a(n)
    c0, c1 = coordinate(n, 0), coordinate(n, 1)
    c2, c3 = coordinate(n, 2), coordinate(n, 3)
    v1 = _unit(c2[0] - c1[0], c2[1] - c1[1])
    v2 = _unit(c3[0] - c0[0], c3[1] - c0[1])
    mean = _unit((v1[0] + v2[0]) / 2.0, (v1[1] + v2[1]) / 2.0)
    u, v = _reference_axes(n)
    axis = u if abs(mean[0] * u[0] + mean[1] * u[1]) >= abs(
        mean[0] * v[0] + mean[1] * v[1]) else v

    dx, dy = c2[0] - c3[0], c2[1] - c3[1]
    den = dx * axis[1] - dy * axis[0]
    if abs(den) < 1e-12:
        # edge(3,2) is parallel to the axis: no intersection exists. 0 of 532
        # corpus divisions hit this; keep the stored offset rather than invent.
        return _interp(c3, c2, n.division[1])
    t = ((a[0] - c3[0]) * axis[1] - (a[1] - c3[1]) * axis[0]) / den
    if not 0.0 < t < 1.0:
        # The orthogonal cut from 'a' does not reach the INTERIOR of edge(3,2):
        # it crosses the line through that edge beyond corner 2 (t > 1), before
        # corner 3 (t < 0), or exactly ON a corner (t == 0 or 1). The same
        # statement as the parallel case above -- the axis cannot be honoured
        # inside this quad -- so it takes the same answer: keep the stored
        # offset rather than invent one.
        #
        # The interval is OPEN on purpose. t == 1.0 is not a near miss to be
        # tolerated, it is the degenerate case itself: `_interp(c3, c2, 1.0)`
        # returns c2 exactly, corners 2 and 3 of the child coincide, and the
        # cell has zero width. It is reachable from ordinary geometry, not just
        # from a clamp -- the quad [(0,0),(10,0),(40,4),(35,4)] hits t == 1.0
        # at a division of exactly 0.5.
        #
        # This used to clamp into [0,1], which looked conservative and was the
        # opposite. `min`/`max` map the whole half-line onto the single worst
        # point in the range: t == 1.0 makes `_interp(c3, c2, t)` return c2
        # EXACTLY, so the child quad's corners 2 and 3 coincide, edge(2) has
        # length zero, and `angle()` divides by `2*a*b == 0`. Measured on
        # harbor-house seed 0: 5 of 21092 orthogonal cuts clamped to t >= 1,
        # and one is enough to kill a run in the bootstrap population. The
        # clamp's note said "merely slightly skew" -- true of the interior of
        # the edge, false at its endpoints (DESIGN.md §39.44).
        return _interp(c3, c2, n.division[1])
    return _interp(c3, c2, t)


def _interp(a: Point, b: Point, t: float) -> Point:
    return [a[0] * (1 - t) + b[0] * t, a[1] * (1 - t) + b[1] * t]


def coordinate(n: Node, idx: int) -> Point:
    """Corner ``idx`` (0..3) of ``n``; mirrors ``Urb::Quad::Coordinate``."""
    key = (id(n), idx)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    if _native(n) is not None:
        poly = polygon(n) or _native_rect_corners(n)
        result = poly[idx % len(poly)]
    elif n.below is not None:  # upper storey inherits geometry from below
        result = coordinate(n.below, idx)
    else:
        rid = (idx + n.rotation) % 4
        if n.parent is None:  # level root: stored, rotation-adjusted corner
            result = list(n.node[rid])
        else:
            p = n.parent
            if n.position == "l":
                result = {0: coordinate(p, 0), 1: coord_a(p), 2: coord_b(p), 3: coordinate(p, 3)}[rid]
            else:  # 'r'
                result = {0: coord_a(p), 1: coordinate(p, 1), 2: coordinate(p, 2), 3: coord_b(p)}[rid]
    _cache[key] = result
    return result


def coord_a(n: Node) -> Point:
    """End 'a' of the division line; mirrors ``Urb::Quad::Coordinate_a``."""
    key = (id(n), "a")
    hit = _cache.get(key)
    if hit is not None:
        return hit
    if n.below is not None and n.below.divided:
        result = coord_a(n.below)
    else:
        result = _interp(coordinate(n, 0), coordinate(n, 1), n.division[0])
    _cache[key] = result
    return result


def coord_b(n: Node) -> Point:
    """End 'b' of the division line; mirrors ``Urb::Quad::Coordinate_b``."""
    key = (id(n), "b")
    hit = _cache.get(key)
    if hit is not None:
        return hit
    if n.below is not None and n.below.divided:
        # Upper storeys inherit, so the derivation below runs once on the base
        # and the stack follows it -- walls stay aligned between storeys.
        result = coord_b(n.below)
    elif ORTHOGONAL_DIVISION:
        result = _orthogonal_b(n)
    else:
        result = _interp(coordinate(n, 3), coordinate(n, 2), n.division[1])
    _cache[key] = result
    return result


def usable_rectangle(n: Node) -> "tuple[float, float]":
    """The two sides of the largest frame-aligned rectangle that fits inside
    ``n`` (`cells.usable_rectangle`), cached with the coordinates.

    This is what the scorer means by a cell's WIDTH and PROPORTION (owner's
    ruling 2026-10-06, DESIGN.md §39.102). The quad formulas below --
    `length_narrowest`, the shortest of four edges, and `aspect`, the mean of
    opposite edges -- stay for the search's own heuristics; neither means
    anything once a cell can be cropped to five corners, and a room with a
    30 cm clipped corner is not 42 cm wide.
    """
    key = (id(n), "usable")
    hit = _cache.get(key)
    if hit is None:
        from . import cells

        u, v = _reference_axes(n)
        hit = cells.usable_rectangle(polygon(n), u, v)
        _cache[key] = hit
    return hit


def usable_width(n: Node) -> float:
    """Short side of the fitted rectangle."""
    return min(usable_rectangle(n))


def usable_aspect(n: Node) -> float:
    """Long side of the fitted rectangle over its short side, always >= 1."""
    a, b = usable_rectangle(n)
    return max(a, b) / min(a, b) if min(a, b) > 0 else 1e9


def n_edges(n: Node) -> int:
    """How many sides ``n`` has. Four, while every cell is a quad -- but the
    scorer asks rather than assumes, so that a cell cropped to a pentagon or a
    triangle by the plot (`homemaker-py-8b2u.4`, `cells.py`) needs this
    function changed and not every loop that walks a cell's sides. The stair
    rules are the exception and say so: a stair core is fitted as a rectangle.
    """
    return 4 if _native(n) is None else (len(polygon(n)) or 4)


def _dist(a: Point, b: Point) -> float:
    # NOT math.hypot: Urb::Math::distance_2d is sqrt(dx**2 + dy**2) and the
    # two differ in the last ULP. Boundary overlap tests feed the difference
    # of near-equal lengths into a > 0 predicate (Urb::Boundary::Overlap), so
    # a 1-ULP deviation flips adjacency decisions on exactly-touching quads.
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _triangle_area(a: Point, b: Point, c: Point) -> float:
    # Heron's formula, matching Urb::Math::triangle_area (always >= 0).
    da, db, dc = _dist(b, c), _dist(a, c), _dist(a, b)
    s = (da + db + dc) / 2
    return math.sqrt(max(0.0, s * (s - da) * (s - db) * (s - dc)))


def area(n: Node) -> float:
    """Area of quad ``n``; mirrors ``Urb::Quad::Area`` (two Heron triangles).
    A native cell's is its polygon's."""
    if _native(n) is not None:
        from . import cells

        return cells.area(polygon(n))
    c = [coordinate(n, i) for i in range(4)]
    return _triangle_area(c[0], c[1], c[2]) + _triangle_area(c[0], c[2], c[3])


def edge_length(n: Node, idx: int) -> float:
    """Length of edge from corner ``idx`` to ``idx+1`` (``Urb::Quad::Length``)."""
    return _dist(coordinate(n, idx), coordinate(n, (idx + 1) % n_edges(n)))


def angle(n: Node, idx: int) -> float:
    """Interior angle at corner ``idx`` in radians (``Urb::Quad::Angle``,
    cosine rule). Clamped acos argument — Perl leaves it unclamped but only a
    degenerate quad would push it out of [-1, 1]."""
    sides = n_edges(n)
    a = edge_length(n, idx)
    b = edge_length(n, (idx - 1) % sides)
    if a * b == 0.0:
        # A corner with a zero-length adjacent edge has no interior angle: the
        # two rays that would define it are the same ray. The cosine rule
        # divides by `2*a*b` and raised ZeroDivisionError here, taking the
        # whole run with it (DESIGN.md §39.44).
        #
        # 0.0 rather than pi/2, deliberately. Every caller is scoring how close
        # this corner is to a right angle, so pi/2 would hand a collapsed cell
        # a PERFECT score and invite the search to make more of them. 0.0 is
        # the far end of the same scale: the degenerate cell is scored as
        # maximally non-perpendicular and the search moves away from it.
        # Defence in depth -- `_orthogonal_b` no longer manufactures these --
        # but a pure-geometry primitive should not raise on a valid Node.
        return 0.0
    c = _dist(coordinate(n, (idx + 1) % sides), coordinate(n, (idx - 1) % sides))
    return math.acos(max(-1.0, min(1.0, (a * a + b * b - c * c) / (2 * a * b))))


def aspect(n: Node) -> float:
    """Plan aspect ratio, always >= 1 (``Urb::Quad::Aspect``). A native cell
    has no pair of opposite edges to average; it answers with its fitted
    rectangle, or its own rectangle if it is off the plot."""
    if _native(n) is not None:
        a, b = usable_rectangle(n)
        if min(a, b) <= 0:
            u0, u1, v0, v1 = _native_rect(n)
            a, b = u1 - u0, v1 - v0
        return max(a, b) / min(a, b) if min(a, b) > 0 else 1e9
    asp = (edge_length(n, 0) + edge_length(n, 2)) / (edge_length(n, 1) + edge_length(n, 3))
    if 0 < asp < 1:
        asp = 1 / asp
    return asp


def length_narrowest(n: Node) -> float:
    """Shortest of the four edge lengths (``Urb::Quad::Length_Narrowest``); for
    a native cell, the short side of its fitted rectangle."""
    if _native(n) is not None:
        return usable_width(n)
    return min(edge_length(n, i) for i in range(4))


# --------------------------------------------------------------------------- #
# Plot wall inset (Urb::Quad::Coordinate_Offset, used on the root in Urb::Dom).
# Positive offset moves a corner outward, negative inward. Computed per corner
# from its two neighbours along the interior-angle bisector; independent of
# rotation, so it operates directly on the stored corner order.
# --------------------------------------------------------------------------- #
def _corner_offset(prev: Point, b: Point, c: Point, offset: float) -> Point:
    side_a = _dist(b, c)
    side_b = _dist(prev, b)
    side_c = _dist(c, prev)
    cos_t = (side_a**2 + side_b**2 - side_c**2) / (2 * side_a * side_b)
    theta2 = math.acos(max(-1.0, min(1.0, cos_t))) / 2
    angle_new = math.atan2(c[1] - b[1], c[0] - b[0]) + theta2
    scale = offset / math.sin(theta2)
    return [b[0] - math.cos(angle_new) * scale, b[1] - math.sin(angle_new) * scale]


def offset_quad(corners: list[Point], offset: float) -> list[Point]:
    """Offset a 4-corner plot by ``offset`` (negative = inward)."""
    n = len(corners)
    return [_corner_offset(corners[(k - 1) % n], corners[k], corners[(k + 1) % n], offset)
            for k in range(n)]


# --------------------------------------------------------------------------- #
# Leaf-adjacency graph (Urb::Quad::Graph + Urb::Boundary)
# --------------------------------------------------------------------------- #

def boundary_id(n: Node, edge: int) -> str:
    """Boundary id of ``edge`` (0..3) of ``n``; mirrors ``Urb::Quad::Boundary_Id``.

    External plot-perimeter boundaries return one of 'a','b','c','d'.
    Internal division boundaries return the id-path of the ancestor whose
    division created that boundary line.  The left child's rid==1 and the right
    child's rid==3 both map to ``parent.id``.

    Rotation is delegated to the lowest below-link (Urb::Quad::Rotation does the
    same: ``return $self->Below->Rotation if defined $self->Below``). Upper-storey
    nodes store their own rotation in the YAML but Urb ignores it and uses the
    ground-floor counterpart's rotation instead.
    """
    g0 = _native(n)
    if g0 is not None:
        # A native cell's side is on the plot ('#k', the plot edge it lies
        # along -- a side whose status changes arrives as two, each on its
        # own) or it is an interior wall. Which cut made an interior wall is
        # not recorded: nothing native asks, the adjacency graph is built from
        # the shared walls themselves.
        poly = polygon(n)
        if not poly:
            return "interior"       # a void cell touches nothing
        a, b = poly[edge % len(poly)], poly[(edge + 1) % len(poly)]
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        inner = _native_frame(g0)[2]
        for k in range(len(inner)):
            p, q = inner[k], inner[(k + 1) % len(inner)]
            if abs(_dist(p, mid) + _dist(mid, q) - _dist(p, q)) < 1e-7:
                dx, dy = q[0] - p[0], q[1] - p[1]
                if abs(dx * (b[1] - a[1]) - dy * (b[0] - a[0])) < 1e-7 * max(1.0, _dist(p, q)):
                    return f"#{k}"
        return "interior"
    nb = n
    while nb.below is not None:
        nb = nb.below
    rid = (edge + nb.rotation) % 4
    if n.parent is None:
        return "abcd"[rid]
    if n.position == "l":
        if rid == 0:
            return boundary_id(n.parent, 0)
        elif rid == 1:
            return n.parent.id          # division line shared with the r sibling
        elif rid == 2:
            return boundary_id(n.parent, 2)
        else:
            return boundary_id(n.parent, 3)
    else:  # position == 'r'
        if rid == 0:
            return boundary_id(n.parent, 0)
        elif rid == 1:
            return boundary_id(n.parent, 1)
        elif rid == 2:
            return boundary_id(n.parent, 2)
        else:
            return n.parent.id          # division line shared with the l sibling


def centroid(n: Node) -> Point:
    """Average of the four corners; mirrors ``Urb::Quad::Centroid``. For a
    native cell, the average of its corners -- status vertices excluded, so
    that marking a change of street status does not move a room's centre."""
    if _native(n) is not None:
        from . import cells

        poly = polygon(n)
        c = cells.corners(poly) or poly
        return [sum(p[0] for p in c) / len(c), sum(p[1] for p in c) / len(c)]
    c = [coordinate(n, i) for i in range(4)]
    return [(c[0][0] + c[1][0] + c[2][0] + c[3][0]) / 4,
            (c[0][1] + c[1][1] + c[2][1] + c[3][1]) / 4]


def _edge_overlap(a: Node, edge_a: int, b: Node, edge_b: int) -> float:
    """Shared boundary width between two leaves; faithful port of
    ``Urb::Boundary::Overlap``.

    The formula is a 1-D overlap estimator: given the four pairwise distances
    between the two edge endpoints, ``len_a + len_b - max_dist`` (with clamped
    special cases).  This mirrors the Perl exactly, including the behaviour for
    below-inherited nodes where the two edges are not physically collinear but
    share the same tree-structure boundary — the formula still returns a
    positive overlap that NetworkX uses to add an adjacency edge.

    Do NOT replace with Shapely's ``intersection().length``: that returns 0 for
    non-collinear segments and would miss valid tree-level adjacencies in
    multi-storey buildings where below-inheritance shifts physical coordinates.
    """
    p_a0 = coordinate(a, edge_a)
    p_a1 = coordinate(a, (edge_a + 1) % 4)
    p_b0 = coordinate(b, edge_b)
    p_b1 = coordinate(b, (edge_b + 1) % 4)
    len_a = _dist(p_a0, p_a1)
    len_b = _dist(p_b0, p_b1)
    max_dist = max(_dist(p_a0, p_b0), _dist(p_a0, p_b1), _dist(p_a1, p_b0), _dist(p_a1, p_b1))
    if max_dist <= len_b:
        return len_a
    if max_dist <= len_a:
        return len_b
    return max(0.0, len_a + len_b - max_dist)


_EXTERNAL = frozenset("abcd")  # single-char external boundary ids


def boundary_groups(level_root: Node) -> dict[str, list[tuple[Node, int]]]:
    """Group (leaf, edge) pairs by shared internal boundary id; the data half
    of ``Urb::Quad::Calc_Boundaries`` (external 'a'-'d' boundaries excluded —
    Urb's ``Boundary::Overlap`` returns 0 for them anyway).

    Membership test uses the frozenset, NOT ``bid not in "abcd"`` — the latter
    is a substring check and silently drops the root-division boundary ('').
    """
    from collections import defaultdict

    groups: dict[str, list[tuple[Node, int]]] = defaultdict(list)
    if _native(level_root) is not None:
        return groups       # nothing native reads them; see `leaf_graph`
    for leaf in level_root.leaves():
        for edge in range(4):
            bid = boundary_id(leaf, edge)
            if bid not in _EXTERNAL:
                groups[bid].append((leaf, edge))
    return groups


def boundary_pair_overlap(contributors: list[tuple[Node, int]], a: Node, b: Node) -> float:
    """Overlap of quads ``a`` and ``b`` on one boundary's contributor list;
    mirrors ``Urb::Boundary::Overlap`` (last matching edge wins, as in the
    Perl loop). Returns 0.0 if either quad has no edge on this boundary.
    """
    edge_a = edge_b = None
    for leaf, edge in contributors:
        if leaf is a:
            edge_a = edge
        if leaf is b:
            edge_b = edge
    if edge_a is None or edge_b is None:
        return 0.0
    return _edge_overlap(a, edge_a, b, edge_b)


def is_between_2d(point: Point | None, pa: Point, pb: Point) -> bool:
    """True if point lies on segment [pa, pb]; mirrors ``Urb::Math::is_between_2d``.

    Returns False if point is None (matches Perl undef-in-array behaviour where
    ``distance_2d(undef, ...)`` returns 0, so the check only passes when the
    segment length itself is < 0.000001).
    """
    if point is None:
        la = 0.0
        lb = 0.0
    else:
        la = _dist(pa, point)
        lb = _dist(pb, point)
    length = _dist(pa, pb)
    return abs(length - la - lb) < 0.000001


def _edge_overlap_coords(
    a: Node, edge_a: int, b: Node, edge_b: int
) -> list[Point] | None:
    """Endpoints of the shared wall segment; ``[[x0,y0],[x1,y1]]`` or None.

    Projects b's edge onto a's edge direction to find the overlap interval and
    converts back to 2D.  Used to populate ``coordinates`` in ``leaf_graph``
    for stair-corner detection (``Corners_In_Use``).
    """
    p_a0 = coordinate(a, edge_a)
    p_a1 = coordinate(a, (edge_a + 1) % 4)
    p_b0 = coordinate(b, edge_b)
    p_b1 = coordinate(b, (edge_b + 1) % 4)
    dx = p_a1[0] - p_a0[0]
    dy = p_a1[1] - p_a0[1]
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-12:
        return None
    inv = 1.0 / math.sqrt(len_sq)
    ux, uy = dx * inv, dy * inv
    len_a = math.sqrt(len_sq)
    t_b0 = (p_b0[0] - p_a0[0]) * ux + (p_b0[1] - p_a0[1]) * uy
    t_b1 = (p_b1[0] - p_a0[0]) * ux + (p_b1[1] - p_a0[1]) * uy
    if t_b0 > t_b1:
        t_b0, t_b1 = t_b1, t_b0
    t_start = max(0.0, t_b0)
    t_end = min(len_a, t_b1)
    if t_start >= t_end - 1e-9:
        return None
    return [
        [p_a0[0] + t_start * ux, p_a0[1] + t_start * uy],
        [p_a0[0] + t_end * ux, p_a0[1] + t_end * uy],
    ]


def _native_facing(level_root: Node, leaves: "list[Node]",
                   door_width: float) -> "list[tuple[int, int]]":
    """Index pairs ``(i, j)``, ``i < j``, sorted, of the cells in ``leaves``
    that could share a door's width of wall (`homemaker-py-8b2u.10`).

    The floorplanner's rule: in a slicing tree two cells share a wall only
    across a cut. A shared stretch of wall lies on the boundary of both cells'
    rectangles, the rectangles do not overlap, and the line that separates
    them is the cut of the node where their paths part. So for each cut, list
    the cells of the low side that touch the line and the cells of the high
    side that touch it -- each list comes out in order along the line, because
    the tree is walked low side first -- and one pass down the two lists gives
    every pair whose rectangles overlap by a door's width. That is a superset
    of the pairs that share that much WALL (the plot's crop only ever shortens
    a cell's side), and the caller measures each one. Against testing every
    pair: about 3 n measurements in place of n^2 / 2.
    """
    index = {id(leaf): i for i, leaf in enumerate(leaves)}
    need = door_width - 1e-6
    pairs: "list[tuple[int, int]]" = []

    def touching(n: Node, fixed: int, high: bool) -> "list[tuple[float, float, int]]":
        """The live cells under ``n`` on the side of its rectangle where frame
        coordinate ``fixed`` (0 for u, 1 for v) is highest or lowest, each
        with its extent along that side, in order."""
        if not n.divided:
            i = index.get(id(n))
            if i is None:                   # a void cell, or one not asked about
                return []
            r = _native_rect(n)
            return [(r[2], r[3], i) if fixed == 0 else (r[0], r[1], i)]
        axis, _, left_low = _native_cut(n)
        low, top = (n.left, n.right) if left_low else (n.right, n.left)
        if (1 if axis == "u" else 0) == fixed:
            return touching(top if high else low, fixed, high)
        return touching(low, fixed, high) + touching(top, fixed, high)

    def walk(n: Node) -> None:
        if not n.divided:
            return
        axis, _, left_low = _native_cut(n)
        low, top = (n.left, n.right) if left_low else (n.right, n.left)
        fixed = 1 if axis == "u" else 0
        a, b = touching(low, fixed, True), touching(top, fixed, False)
        i = j = 0
        while i < len(a) and j < len(b):
            if min(a[i][1], b[j][1]) - max(a[i][0], b[j][0]) >= need:
                x, y = a[i][2], b[j][2]
                pairs.append((x, y) if x < y else (y, x))
            if a[i][1] <= b[j][1]:
                i += 1
            else:
                j += 1
        walk(low)
        walk(top)

    walk(level_root)
    pairs.sort()
    return pairs


def leaf_graph(level_root: Node, door_width: float = 1.2):  # -> nx.Graph
    """Leaf-adjacency graph for one storey; mirrors ``Urb::Quad::Graph``.

    Returns a ``networkx.Graph`` whose nodes are leaf ``Node`` objects and whose
    edges carry ``width`` (shared boundary metres), ``weight`` (centroid
    distance metres), and ``coordinates`` ([[x0,y0],[x1,y1]] wall endpoints or
    None).  Edges with width < ``door_width`` (Urb default 1.2 m) are excluded.
    External plot-perimeter boundaries ('a','b','c','d') are never edges.  A
    single-leaf storey gets one isolated vertex.
    """
    import networkx as nx

    leaves = level_root.leaves()
    if _native(level_root) is not None:
        # Two cells are neighbours if their outlines share a door's width of
        # wall. On every orthogonal design this is the graph the boundary-id
        # walk below builds, wall for wall (6,517 of them, §39.101).
        from . import cells

        G = nx.Graph()
        G.add_nodes_from(leaves)
        polys = [polygon(leaf) for leaf in leaves]
        # Only cells that face each other across a cut are measured
        # (`_native_facing`); they are added in the order an all-pairs loop
        # would reach them, so the graph is the one that loop built, down to
        # the order a cell's neighbours are listed in.
        for i, j in _native_facing(level_root, leaves, door_width):
            width, seg = cells.shared_wall(polys[i], polys[j])
            if width >= door_width:
                G.add_edge(leaves[i], leaves[j], width=width, coordinates=seg,
                           weight=_dist(centroid(leaves[i]), centroid(leaves[j])))
        return G
    groups = boundary_groups(level_root)

    G: nx.Graph = nx.Graph()
    for leaf in leaves:
        G.add_node(leaf)

    for contributors in groups.values():
        for i in range(len(contributors)):
            for j in range(i + 1, len(contributors)):
                a, edge_a = contributors[i]
                b, edge_b = contributors[j]
                if a is b:
                    continue
                width = _edge_overlap(a, edge_a, b, edge_b)
                if width >= door_width:
                    if not G.has_edge(a, b) or G[a][b]["width"] < width:
                        dist = _dist(centroid(a), centroid(b))
                        coords = _edge_overlap_coords(a, edge_a, b, edge_b)
                        G.add_edge(a, b, weight=dist, width=width, coordinates=coords)

    return G

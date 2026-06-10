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

from .dom import Node

Point = list[float]


def _interp(a: Point, b: Point, t: float) -> Point:
    return [a[0] * (1 - t) + b[0] * t, a[1] * (1 - t) + b[1] * t]


def coordinate(n: Node, idx: int) -> Point:
    """Corner ``idx`` (0..3) of ``n``; mirrors ``Urb::Quad::Coordinate``."""
    if n.below is not None:  # upper storey inherits geometry from below
        return coordinate(n.below, idx)
    rid = (idx + n.rotation) % 4
    if n.parent is None:  # level root: stored, rotation-adjusted corner
        return list(n.node[rid])
    p = n.parent
    if n.position == "l":
        return {0: coordinate(p, 0), 1: coord_a(p), 2: coord_b(p), 3: coordinate(p, 3)}[rid]
    # position == 'r'
    return {0: coord_a(p), 1: coordinate(p, 1), 2: coordinate(p, 2), 3: coord_b(p)}[rid]


def coord_a(n: Node) -> Point:
    """End 'a' of the division line; mirrors ``Urb::Quad::Coordinate_a``."""
    if n.below is not None and n.below.divided:
        return coord_a(n.below)
    return _interp(coordinate(n, 0), coordinate(n, 1), n.division[0])


def coord_b(n: Node) -> Point:
    """End 'b' of the division line; mirrors ``Urb::Quad::Coordinate_b``."""
    if n.below is not None and n.below.divided:
        return coord_b(n.below)
    return _interp(coordinate(n, 3), coordinate(n, 2), n.division[1])


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _triangle_area(a: Point, b: Point, c: Point) -> float:
    # Heron's formula, matching Urb::Math::triangle_area (always >= 0).
    da, db, dc = _dist(b, c), _dist(a, c), _dist(a, b)
    s = (da + db + dc) / 2
    return math.sqrt(max(0.0, s * (s - da) * (s - db) * (s - dc)))


def area(n: Node) -> float:
    """Area of quad ``n``; mirrors ``Urb::Quad::Area`` (two Heron triangles)."""
    c = [coordinate(n, i) for i in range(4)]
    return _triangle_area(c[0], c[1], c[2]) + _triangle_area(c[0], c[2], c[3])


def edge_length(n: Node, idx: int) -> float:
    """Length of edge from corner ``idx`` to ``idx+1`` (``Urb::Quad::Length``)."""
    return _dist(coordinate(n, idx), coordinate(n, (idx + 1) % 4))


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

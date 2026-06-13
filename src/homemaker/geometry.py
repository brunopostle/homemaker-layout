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

# Memoisation of derived coordinates. The pull-based recursion mirrors Urb but,
# uncached, re-derives ancestor/below corners exponentially with depth. Urb
# itself caches in the node and clears via Clean_Cache(); we do the same with a
# module cache keyed by node identity. Callers that mutate divisions (the
# solver) must call clear_cache(); dom.load() clears it for a fresh tree.
_cache: dict = {}


def clear_cache() -> None:
    _cache.clear()


def _interp(a: Point, b: Point, t: float) -> Point:
    return [a[0] * (1 - t) + b[0] * t, a[1] * (1 - t) + b[1] * t]


def coordinate(n: Node, idx: int) -> Point:
    """Corner ``idx`` (0..3) of ``n``; mirrors ``Urb::Quad::Coordinate``."""
    key = (id(n), idx)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    if n.below is not None:  # upper storey inherits geometry from below
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
        result = coord_b(n.below)
    else:
        result = _interp(coordinate(n, 3), coordinate(n, 2), n.division[1])
    _cache[key] = result
    return result


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
    """Area of quad ``n``; mirrors ``Urb::Quad::Area`` (two Heron triangles)."""
    c = [coordinate(n, i) for i in range(4)]
    return _triangle_area(c[0], c[1], c[2]) + _triangle_area(c[0], c[2], c[3])


def edge_length(n: Node, idx: int) -> float:
    """Length of edge from corner ``idx`` to ``idx+1`` (``Urb::Quad::Length``)."""
    return _dist(coordinate(n, idx), coordinate(n, (idx + 1) % 4))


def angle(n: Node, idx: int) -> float:
    """Interior angle at corner ``idx`` in radians (``Urb::Quad::Angle``,
    cosine rule). Clamped acos argument — Perl leaves it unclamped but only a
    degenerate quad would push it out of [-1, 1]."""
    a = edge_length(n, idx)
    b = edge_length(n, (idx + 3) % 4)
    c = _dist(coordinate(n, (idx + 1) % 4), coordinate(n, (idx + 3) % 4))
    return math.acos(max(-1.0, min(1.0, (a * a + b * b - c * c) / (2 * a * b))))


def aspect(n: Node) -> float:
    """Plan aspect ratio, always >= 1 (``Urb::Quad::Aspect``)."""
    asp = (edge_length(n, 0) + edge_length(n, 2)) / (edge_length(n, 1) + edge_length(n, 3))
    if 0 < asp < 1:
        asp = 1 / asp
    return asp


def length_narrowest(n: Node) -> float:
    """Shortest of the four edge lengths (``Urb::Quad::Length_Narrowest``)."""
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
    """Average of the four corners; mirrors ``Urb::Quad::Centroid``."""
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


def leaf_graph(level_root: Node, door_width: float = 1.2):  # -> nx.Graph
    """Leaf-adjacency graph for one storey; mirrors ``Urb::Quad::Graph``.

    Returns a ``networkx.Graph`` whose nodes are leaf ``Node`` objects and whose
    edges carry ``width`` (shared boundary metres) and ``weight`` (centroid
    distance metres).  Edges with width < ``door_width`` (Urb default 1.2 m)
    are excluded.  External plot-perimeter boundaries ('a','b','c','d') are
    never edges.  A single-leaf storey gets one isolated vertex.
    """
    import networkx as nx

    leaves = level_root.leaves()
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
                        G.add_edge(a, b, weight=dist, width=width)

    return G

"""Pitched roofs for an exported layout (`homemaker-py-6e5u`, DESIGN.md §39.119).

Urb's Perl made pitched roofs as solids. homemaker-addon wants something
else: a roof is a VOID CELL, enclosed below by the ceilings of the top rooms
and above by sloping faces, with vertical faces where it ends in a gable.
So the exporter has to work the geometry out itself, and this is it.

**The roof of an outline.** With every eave at one height and every slope at
one pitch, the roof over a polygon is its straight skeleton raised: each edge
owns the part of a plane rising inwards from it, and the planes meet in hips,
valleys and ridges. Eppstein and Erickson ("Raising roofs, crashing cycles,
and playing pool", 1999) show that this surface is the LOWER ENVELOPE of
pieces that can be written down without computing the skeleton:

* an *edge slab* for each edge: its plane over the strip standing square on
  the edge;
* a *reflex slab* at each reflex corner, for each of its two edges: the same
  plane continued past the corner, over the wedge between the edge's
  perpendicular and the valley that leaves the corner.

So each edge's roof face is the region of its slabs where no other slab is
lower -- a few polygon clips per edge (shapely), with none of the event
bookkeeping a wavefront simulation needs, and no special cases for the
many simultaneous events an orthogonal plan produces. Holes need nothing
extra: a hole's edges are edges.

**Gables.** Urb gabled an edge that lies on a party boundary. Here a gable is
made from the hipped roof, not instead of it: where such an edge's face is a
hip END -- a triangle up to the point where its two neighbours meet -- the
ridge is carried on to the wall, the neighbours each gain a triangle, and the
end is closed by a vertical face (`_gable_ends`). A party wall that runs
ALONG a roof, not across its end, keeps its slope. (Leaving a gable edge out
of the lower envelope looks simpler and is wrong: without that edge's slab
the envelope is no longer continuous, and on the first real design it left a
step in the roof beside a plot side four degrees off square.)

`tests/test_roofs.py` holds the hipped surface to an independent straight
skeleton (`bpypolyskel`, when it is installed) point for point.

Everything here is plan geometry in whatever coordinates the caller uses; the
exporter calls it in the layout's frame, where interior walls are axial.
"""

from __future__ import annotations

import math

import shapely
from shapely import set_precision
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

GRID = 1e-6          # every coordinate is snapped to this, metres
# A vertex this close to the line through its neighbours is on a straight
# side, not at a corner. It has to be this tight: homemaker-addon (OpenCascade)
# refuses a face whose corners are more than about a micron off one plane
# (measured: 1e-6 builds, 1e-5 is "the wire was not planar"), and a side's
# vertices are all on its face. A rooms document is written to a tenth of a
# millimetre, so a vertex part-way along a SKEW plot side is off the line by
# up to that and is a corner here -- between two faces a hundredth of a degree
# apart, each of them flat.
STRAIGHT = 1e-6
SHAPE = 3e-4         # ...but for judging whether a face is a triangle, this
WELD = 5e-5          # roof corners closer than this are one corner
MIN_AREA = 1e-6      # a face smaller than this is clipping dust


class RoofError(ValueError):
    """The roof of an outline could not be made to tile it."""


# --------------------------------------------------------------------------- #
# outline -> edges
# --------------------------------------------------------------------------- #
class _Edge:
    __slots__ = ("a", "b", "t", "n", "length", "gable", "ring", "k")

    def __init__(self, a, b, gable, ring, k):
        self.a, self.b = a, b
        dx, dy = b[0] - a[0], b[1] - a[1]
        self.length = math.hypot(dx, dy)
        self.t = (dx / self.length, dy / self.length)
        self.n = (-self.t[1], self.t[0])        # into the polygon: it is on the left
        self.gable, self.ring, self.k = gable, ring, k

    def rise(self, p) -> float:
        """Distance of ``p`` from this edge's line, positive inwards."""
        return (p[0] - self.a[0]) * self.n[0] + (p[1] - self.a[1]) * self.n[1]


def _rings(poly: Polygon) -> "list[list[tuple[float, float]]]":
    poly = orient(poly, 1.0)                    # outer CCW, holes CW: inside on the left
    return [list(r.coords)[:-1] for r in (poly.exterior, *poly.interiors)]


def _straighten(ring, is_gable) -> "list[tuple[tuple, tuple, bool]]":
    """The ring's sides as ``(a, b, gable)``, with runs of collinear edges
    joined into one side. A side is a gable only if every part of it is."""
    n = len(ring)
    corner = []
    for i in range(n):
        p, q, r = ring[i - 1], ring[i], ring[(i + 1) % n]
        # A corner is a vertex that stands off the line through its
        # neighbours by more than the snapping could have moved it. Judged by
        # angle instead, a vertex that was exactly on a skew side before
        # snapping comes back as a corner between two edges 1e-7 radians
        # apart, and their two all-but-identical planes have no usable line
        # of intersection.
        cross = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        corner.append(abs(cross) > STRAIGHT * max(math.hypot(r[0] - p[0], r[1] - p[1]), 1e-9))
    corners = [i for i in range(n) if corner[i]]
    if len(corners) < 3:
        raise RoofError("an outline needs three corners")
    sides = []
    for c, i in enumerate(corners):
        j = corners[(c + 1) % len(corners)]
        parts, k = [], i
        while k != j:
            parts.append((ring[k], ring[(k + 1) % n]))
            k = (k + 1) % n
        sides.append((ring[i], ring[j], all(is_gable(a, b) for a, b in parts)))
    return sides


def _edges(poly: Polygon, is_gable) -> "list[_Edge]":
    out = []
    for r, ring in enumerate(_rings(poly)):
        for k, (a, b, gable) in enumerate(_straighten(ring, is_gable)):
            out.append(_Edge(a, b, gable, r, k))
    return out


# --------------------------------------------------------------------------- #
# slabs
# --------------------------------------------------------------------------- #
def _halfplane(point, normal, reach: float) -> Polygon:
    """The half-plane ``(p - point) . normal >= 0``, as a polygon ``reach`` big."""
    nx, ny = normal
    tx, ty = -ny, nx
    x, y = point
    return Polygon([(x - tx * reach, y - ty * reach), (x + tx * reach, y + ty * reach),
                    (x + tx * reach + nx * reach, y + ty * reach + ny * reach),
                    (x - tx * reach + nx * reach, y - ty * reach + ny * reach)])


def _cone(apex, d1, d2, reach: float) -> "Polygon | None":
    """The wedge at ``apex`` between directions ``d1`` and ``d2``."""
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cross) < 1e-12:
        return None
    pts = [apex, (apex[0] + d1[0] * reach, apex[1] + d1[1] * reach),
           (apex[0] + (d1[0] + d2[0]) * reach, apex[1] + (d1[1] + d2[1]) * reach),
           (apex[0] + d2[0] * reach, apex[1] + d2[1] * reach)]
    return Polygon(pts if cross > 0 else pts[::-1])


def _slab_region(e: _Edge, prev: _Edge, nxt: _Edge, poly: Polygon, reach: float):
    """Where edge ``e``'s plane may be the roof: its strip, and past each
    reflex end the wedge out to the valley."""
    strip = _and(_and(_halfplane(e.a, e.n, reach), _halfplane(e.a, e.t, reach)),
                 _halfplane(e.b, (-e.t[0], -e.t[1]), reach))
    parts = [strip]
    for corner, other, sign in ((e.a, prev, 1.0), (e.b, nxt, -1.0)):
        # the corner is reflex if the neighbour turns AWAY from the inside
        turn = (prev.t[0] * e.t[1] - prev.t[1] * e.t[0]) if other is prev \
            else (e.t[0] * nxt.t[1] - e.t[1] * nxt.t[0])
        if turn >= -1e-12:
            continue
        valley = (e.n[0] + other.n[0], e.n[1] + other.n[1])
        norm = math.hypot(*valley)
        if norm < 1e-12:
            continue
        cone = _cone(corner, e.n, (valley[0] / norm, valley[1] / norm), reach)
        if cone is not None:
            parts.append(cone)
    return _and(_or(parts), poly)


def _lower_than(j: _Edge, e: _Edge, bounds, strict: bool) -> "Polygon | None":
    """The part of the box ``bounds`` where edge ``j``'s plane is below edge
    ``e``'s (``strict``: or equal, for two edges on one line).

    The box is clipped by the inequality directly. Building a half-plane
    around a point of the line where the two planes meet fails exactly when
    it matters: two edges a hair off parallel -- a 13 cm edge whose ends were
    each snapped a micron -- meet tens of kilometres away, and a polygon drawn
    out there covers none of the roof.
    """
    nx, ny = e.n[0] - j.n[0], e.n[1] - j.n[1]
    c = (e.a[0] * e.n[0] + e.a[1] * e.n[1]) - (j.a[0] * j.n[0] + j.a[1] * j.n[1])
    # rise_j(p) < rise_e(p)  <=>  p.(e.n - j.n) - c > 0
    minx, miny, maxx, maxy = bounds
    ring = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]
    value = [x * nx + y * ny - c for x, y in ring]
    tie = 1e-7
    if all(abs(v) <= tie for v in value):       # one plane: the earlier edge keeps it
        return None if strict else box(minx, miny, maxx, maxy)
    if all(v >= -tie for v in value):
        return box(minx, miny, maxx, maxy)
    if all(v <= tie for v in value):
        return None
    # A hip from a corner of the outline's bounding box runs at 45 degrees
    # straight through the corner of the box used here, so "on the line" has
    # to be a decision and not an accident of the last bit: such a corner is
    # ON it, and is kept once.
    value = [0.0 if abs(v) <= tie else v for v in value]
    out = []
    for i in range(4):
        (p, vp), (q, vq) = (ring[i], value[i]), (ring[(i + 1) % 4], value[(i + 1) % 4])
        if vp >= 0:
            out.append(p)
        if (vp > 0 and vq < 0) or (vp < 0 and vq > 0):
            t = vp / (vp - vq)
            out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
    if len(out) < 3:
        return None
    clipped = Polygon(out)
    return clipped if clipped.is_valid and clipped.area > 0 else None


# Every clip is done on one fixed grid (GEOS's snap-rounding overlay). Done in
# floating point, two faces that should meet along a hip instead overlap or
# gap by 1e-13, and the next operation is handed a sliver it calls invalid.
def _areal(geom):
    """The polygons of ``geom`` and nothing else: a clip that leaves two
    faces touching along a line returns that line too."""
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    return MultiPolygon([g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)])


def _and(a, b):
    return _areal(shapely.intersection(a, b, grid_size=GRID))


def _minus(a, b):
    return _areal(shapely.difference(a, b, grid_size=GRID))


def _or(parts):
    return _areal(shapely.union_all(list(parts), grid_size=GRID))


def _polygons(geom) -> "list[Polygon]":
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon) and not g.is_empty]


# --------------------------------------------------------------------------- #
# the roof of one outline
# --------------------------------------------------------------------------- #
def _tiling(poly: Polygon, edges: "list[_Edge]") -> "list[tuple[_Edge, Polygon]]":
    """Each sloping edge's roof face in plan; raises if they do not tile."""
    minx, miny, maxx, maxy = poly.bounds
    reach = 4.0 * (maxx - minx + maxy - miny) + 10.0
    around = (minx - 1.0, miny - 1.0, maxx + 1.0, maxy + 1.0)
    by_ring: dict = {}
    for e in edges:
        by_ring.setdefault(e.ring, []).append(e)
    region = {}
    for ring in by_ring.values():
        for i, e in enumerate(ring):
            region[id(e)] = _slab_region(e, ring[i - 1], ring[(i + 1) % len(ring)], poly, reach)
    sloping = list(edges)
    out = []
    for i, e in enumerate(sloping):
        face = region[id(e)]
        for k, j in enumerate(sloping):
            if j is e or face.is_empty:
                continue
            # two edges on one line share a plane: the earlier one keeps the tie
            lower = _lower_than(j, e, around, strict=k > i)
            if lower is not None:
                face = _minus(face, _and(region[id(j)], lower))
        for piece in _polygons(face):
            if piece.area > MIN_AREA:
                out.append((e, piece))
    covered = sum(p.area for _, p in out)
    if abs(covered - poly.area) > 1e-4 * max(1.0, poly.area):
        raise RoofError(f"roof faces cover {covered:.4f} m2 of an outline of {poly.area:.4f} m2")
    return out


def _with_shared_vertices(faces: "list[tuple[_Edge, Polygon]]", extra=()):
    """Every face as a ring of plan corners that its neighbours agree on.

    Two things stand between a correct tiling and a cell that closes. Faces
    meeting at a point were each clipped separately and name it a micron
    apart, so corners closer than `WELD` are made one. And where a face's
    straight edge runs past a corner of its neighbours, that corner is put
    into the edge, so both sides list the same vertices along a shared line.
    """
    canon: "list[tuple[float, float]]" = []
    cells: dict = {}

    def weld(x, y):
        key = (round(x / WELD), round(y / WELD))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for c in cells.get((key[0] + dx, key[1] + dy), ()):
                    if abs(c[0] - x) <= WELD and abs(c[1] - y) <= WELD:
                        return c
        c = (round(x, 6), round(y, 6))
        cells.setdefault(key, []).append(c)
        canon.append(c)
        return c

    for x, y in extra:
        weld(x, y)
    rings = []
    for e, p in faces:
        ring = _dedupe([weld(x, y) for x, y in orient(p, 1.0).exterior.coords[:-1]])
        rings.append((e, ring, [list(r.coords)[:-1] for r in p.interiors]))
    out = []
    for e, ring, holes in rings:
        new = []
        for i, a in enumerate(ring):
            b = ring[(i + 1) % len(ring)]
            new.append(a)
            dx, dy = b[0] - a[0], b[1] - a[1]
            length2 = dx * dx + dy * dy
            if length2 < 1e-18:
                continue
            on = []
            for c in canon:
                if c == a or c == b:
                    continue
                t = ((c[0] - a[0]) * dx + (c[1] - a[1]) * dy) / length2
                if 0 < t < 1 and abs((c[0] - a[0]) * dy - (c[1] - a[1]) * dx) \
                        < WELD * math.sqrt(length2):
                    on.append((t, c))
            new += [c for _, c in sorted(on)]
        out.append((e, _dedupe(new), holes))
    return out


def _corners(ring: list) -> list:
    """The ring without the vertices that lie along a straight side."""
    out = []
    n = len(ring)
    for i, q in enumerate(ring):
        p, r = ring[i - 1], ring[(i + 1) % n]
        cross = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        if abs(cross) > SHAPE * max(math.hypot(r[0] - p[0], r[1] - p[1]), 1e-9):
            out.append(q)
    return out


def _near(p, q, tol: float = 5e-6) -> bool:
    return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol


def _gable_ends(tiles, edges):
    """Turn hip ends into gables where an edge marked ``gable`` allows it.

    A hip END is a triangular face: the edge and one point N where the two
    neighbouring slopes meet. Those two slopes share a ridge line through N;
    carry it on to the wall, to N', give each neighbour the triangle it gains,
    and the end face is replaced by a vertical wall under the two slopes.
    Nothing else about the roof moves, and N' is on both neighbours' planes
    by construction, so the surface stays closed.

    An edge marked ``gable`` whose face is NOT such a triangle -- a party wall
    along the side of a roof, not across its end -- stays a slope. Returns
    ``(tiles, walls, left)``: the new tiling, the gable walls as ``(edge, N')``,
    and how many gable edges were left hipped.
    """
    tiles = list(tiles)
    walls, left = [], 0
    for g in (e for e in edges if e.gable):
        mine = [(i, p) for i, (e, p) in enumerate(tiles) if e is g and p is not None]
        if len(mine) != 1:
            left += 1
            continue
        index, face = mine[0]
        ring = _corners(list(orient(face, 1.0).exterior.coords)[:-1])
        if len(ring) != 3 or face.interiors:
            left += 1
            continue
        apex = [q for q in ring if not _near(q, g.a) and not _near(q, g.b)]
        if len(apex) != 1:
            left += 1
            continue
        n = apex[0]
        side = {}
        for end in (g.a, g.b):
            hip = LineString([end, n])
            share = [(i, e) for i, (e, p) in enumerate(tiles)
                     if e is not g and p is not None
                     and p.intersection(hip.buffer(2e-6)).area > 0
                     and p.exterior.intersection(hip.buffer(2e-6)).length > 0.5 * hip.length]
            if len(share) != 1:
                break
            side[end] = share[0]
        if len(side) != 2:
            left += 1
            continue
        (ia, ea), (ib, eb) = side[g.a], side[g.b]
        # the ridge: where the two neighbours' planes are equal, through N
        nx, ny = ea.n[0] - eb.n[0], ea.n[1] - eb.n[1]
        dx, dy = -ny, nx
        denom = dx * g.n[0] + dy * g.n[1]
        if abs(denom) < 1e-9:
            left += 1
            continue
        t = -g.rise(n) / denom
        foot = (n[0] + t * dx, n[1] + t * dy)
        along = (foot[0] - g.a[0]) * g.t[0] + (foot[1] - g.a[1]) * g.t[1]
        if not 1e-4 < along < g.length - 1e-4 or min(ea.rise(foot), eb.rise(foot)) <= 0:
            left += 1
            continue
        gain_a, gain_b = Polygon([g.a, foot, n]), Polygon([foot, g.b, n])
        new_a = _polygons(_or([tiles[ia][1], gain_a]))
        new_b = _polygons(_or([tiles[ib][1], gain_b]))
        if len(new_a) != 1 or len(new_b) != 1:
            left += 1
            continue
        tiles[ia], tiles[ib] = (ea, new_a[0]), (eb, new_b[0])
        tiles[index] = (g, None)
        walls.append((g, foot, min(ea.rise(foot), eb.rise(foot))))
    return [(e, p) for e, p in tiles if p is not None], walls, left


def roof(outline: Polygon, pitch_degrees: float = 35.0, eave: float = 0.0,
         is_gable=None) -> dict:
    """The pitched roof over ``outline``.

    Returns ``{"faces": [...], "apex": (x, y, z), "gables": n, "hipped": m}``:
    each face a list of ``[x, y, z]`` corners, anticlockwise seen from outside
    the roof (from above, for a slope); ``apex`` a highest point of the roof.
    ``is_gable(a, b)`` says whether the outline edge from ``a`` to ``b`` may be
    a gable end; ``gables`` is how many became one and ``hipped`` how many
    were left as slopes because the roof does not end there (`_gable_ends`).
    """
    outline = set_precision(orient(outline, 1.0), GRID)
    if outline.is_empty or not isinstance(outline, Polygon):
        raise RoofError("an outline must be one polygon")
    tan = math.tan(math.radians(pitch_degrees))
    edges = _edges(outline, is_gable or (lambda a, b: False))
    tiles = _tiling(outline, edges)
    tiles, walls, left = _gable_ends(tiles, edges)
    covered = sum(p.area for _, p in tiles)
    if abs(covered - outline.area) > 1e-4 * max(1.0, outline.area):
        raise RoofError("the gabled roof does not tile its outline")

    faces, apex = [], (0.0, 0.0, -1.0)
    height: dict = {}
    for e, ring, holes in _with_shared_vertices(
            tiles, [foot for _, foot, _ in walls]
            + [c for r in (outline.exterior, *outline.interiors) for c in r.coords]):
        if holes:                       # a face with a hole in it: not expected of a roof
            raise RoofError("a roof face has a hole")
        face = []
        for x, y in ring:
            # Each corner's height from THIS face's plane, so the face is flat
            # to the last digit. The faces meeting at a corner then agree on
            # its height to a micron, which is inside what the addon merges;
            # one shared height per corner would be tidier and is what made
            # the first export non-planar.
            # (Not clamped at the eave: a corner a micron outside its own
            # edge's line is a micron BELOW the eave on that plane, and
            # lifting it back would bend the face.)
            h = tan * e.rise((x, y))
            height.setdefault((x, y), h)
            face.append([x, y, round(eave + h, 7)])
            if h > apex[2]:
                apex = (x, y, h)
        faces.append(_dedupe(face))
    for g, foot, rise in walls:
        a, b = [round(c, 6) for c in g.a], [round(c, 6) for c in g.b]
        # anticlockwise seen from outside (the inside is on the left of a -> b)
        top = next((k for k in height if _near(k, foot, WELD)), None)
        z = height[top] if top is not None else tan * rise
        fx, fy = top if top is not None else (round(foot[0], 6), round(foot[1], 6))
        faces.append([[a[0], a[1], round(eave, 6)], [b[0], b[1], round(eave, 6)],
                      [fx, fy, round(eave + z, 6)]])
    return {"faces": [f for f in faces if len(f) >= 3],
            "apex": (apex[0], apex[1], round(eave + apex[2], 6)),
            "gables": len(walls), "hipped": left}


def _dedupe(face: list) -> list:
    out = []
    for p in face:
        if not out or p != out[-1]:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def surface(outline: Polygon, pitch_degrees: float = 35.0, is_gable=None):
    """A function ``rise(x, y)``: the roof's height above the eave at a plan
    point, read off the lower envelope directly. For tests, and for placing
    things under a roof."""
    outline = set_precision(orient(outline, 1.0), GRID)
    tan = math.tan(math.radians(pitch_degrees))
    tiles = _tiling(outline, _edges(outline, is_gable or (lambda a, b: False)))

    def rise(x: float, y: float) -> float:
        here = Point(x, y)
        for e, piece in tiles:
            if piece.distance(here) < 1e-6:
                return max(0.0, tan * e.rise((x, y)))
        raise RoofError(f"({x}, {y}) is not under the roof")

    return rise


# --------------------------------------------------------------------------- #
# roofs for a rooms document
# --------------------------------------------------------------------------- #
def outlines(room_polygons: "list[list]") -> "list[Polygon]":
    """The outlines of a set of plan polygons taken together: rooms that
    share a wall are under one roof."""
    polys = [set_precision(Polygon(p), GRID) for p in room_polygons if len(p) >= 3]
    polys = [p for p in polys if not p.is_empty and p.area > MIN_AREA]
    if not polys:
        return []
    merged = unary_union(polys)
    return [orient(p, 1.0) for p in _polygons(merged) if p.area > MIN_AREA]


def for_rooms(rooms: "list[dict]", pitch_degrees: float = 35.0,
              gables: bool = True) -> "tuple[list[dict], list[dict], list[str]]":
    """Roof faces and widgets for the rooms that have nothing over them.

    ``rooms`` are rooms-document rooms carrying ``roofed: True`` where the
    cell is on the top storey. Returns ``(faces, widgets, notes)`` in the
    document's own terms: a face is ``{"vertices": [[x, y, z], ...],
    "stylename": "default"}``, a widget ``{"position": [x, y, z], "usage":
    "void"}`` placed inside each roof so that the cell it encloses is known
    to be empty, and a note says what was done to an outline that could not
    be roofed as asked.
    """
    top = [r for r in rooms if r.get("roofed")]
    if not top:
        return [], [], []
    eaves = sorted({round(r["elevation"] + r["height"], 4) for r in top})
    faces, widgets, notes = [], [], []
    for eave in eaves:
        here = [r for r in top if round(r["elevation"] + r["height"], 4) == eave]
        party = []
        for r in here:
            v, styles = r["vertices"], r.get("face_styles") or []
            for i in range(len(v)):
                if i + 2 < len(styles) and styles[i + 2] == "blank":
                    party.append(LineString([v[i], v[(i + 1) % len(v)]]))

        def is_gable(a, b, party=party):
            seg = LineString([a, b])
            covered = sum(seg.intersection(w.buffer(1e-4)).length for w in party)
            return covered >= seg.length - 1e-3

        for outline in outlines([r["vertices"] for r in here]):
            try:
                made = roof(outline, pitch_degrees, eave, is_gable if gables else None)
            except RoofError as exc:
                notes.append(f"flat roof left over {outline.area:.1f} m2 at {eave} m: {exc}")
                continue
            if made["hipped"]:
                notes.append(f"roof at {eave} m: {made['gables']} gable end(s); "
                             f"{made['hipped']} party side(s) kept a slope, the roof "
                             "does not end there")
            faces += [{"vertices": f, "stylename": "default"} for f in made["faces"]]
            x, y, z = made["apex"]
            widgets.append({"position": [round(x, 4), round(y, 4),
                                         round((eave + z) / 2, 4)], "usage": "void"})
    return faces, widgets, notes


__all__ = ["RoofError", "roof", "surface", "outlines", "for_rooms", "MultiPolygon"]

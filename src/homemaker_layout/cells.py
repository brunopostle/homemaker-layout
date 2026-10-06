"""Native rectangle-frame geometry: the cells of a format-v2 document, computed
from the document alone (`homemaker-py-8b2u.4`, docs/dom-format-v2.md).

A v2 building is a slicing tree over the rectangle that encloses the plot in
its frame, cropped to the plot. This module does exactly that and nothing
else: split the frame rectangle by each cut, intersect each leaf rectangle
with the plot polygon. No ``Node`` tree, no ``rotation``, no ratio along a skew
edge, no orthogonal-division switch.

It is the CORE of stage 1b, not stage 1b. Nothing scores through it yet: the
scorer still reads ``geometry``'s quads, and :mod:`dom_v2` still reads a v2
file into the v1 tree. What this adds is everything that tree cannot hold --

* a plot of any number of vertices, convex or not, with collinear vertices
  kept (a side whose street/party status changes part-way is two edges);
* a ``frame.u`` that is the file's own and not re-derived from the longest edge;
* cells that crop to a triangle, a pentagon, or nothing at all;

-- together with the owner's shape score for the odd ones (DESIGN.md §39.90).
``tests/test_cells.py`` holds it to today's geometry on every orthogonal
artefact, cell for cell, which is the "bit-identical on the corpus" gate
stage 1b has to pass before the scorer is moved onto it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

Point = list[float]

EPS = 1e-9           # metres: coincident points, a line "on" an edge
EMPTY_AREA = 1e-6    # m2: below this a cell is empty (docs: "holds no area")

# The shape score (owner's ruling 2026-10-05, DESIGN.md §39.90): a clipped
# Gaussian on the usable fraction, full credit from 0.85, the fail line (0.1,
# `fitness.FAIL_THRESHOLD`) at 0.70.
SHAPE_FULL = 0.85
SHAPE_FAIL = 0.70
SHAPE_SIGMA = (SHAPE_FULL - SHAPE_FAIL) / math.sqrt(2 * math.log(10))


class CellsError(ValueError):
    """The document does not describe a building this geometry can draw."""


@dataclass
class Cell:
    storey: int
    path: str                      # route from the storey's root: 'l' low, 'h' high
    type: "str | None"
    rect: "tuple[float, float, float, float]"      # u0, u1, v0, v1 in the frame
    polygon: "list[Point]"         # world coordinates, anticlockwise; [] if empty
    share: int = 1
    co_type: "str | None" = None

    @property
    def area(self) -> float:
        return area(self.polygon)

    @property
    def empty(self) -> bool:
        return len(self.polygon) < 3 or self.area < EMPTY_AREA


@dataclass
class Layout:
    u: "tuple[float, float]"
    v: "tuple[float, float]"
    plot: "list[Point]"            # the plot as drawn (outer boundary)
    inner: "list[Point]"           # after the wall_outer inset: what cells crop to
    box: "tuple[float, float, float, float]"
    perimeter: "list[str | None]"
    storeys: "list[list[Cell]]" = field(default_factory=list)

    def cells(self) -> "list[Cell]":
        return [c for storey in self.storeys for c in storey]


# --------------------------------------------------------------------------- #
# polygons
# --------------------------------------------------------------------------- #
def area(poly: "list[Point]") -> float:
    """Unsigned area (shoelace)."""
    if len(poly) < 3:
        return 0.0
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1]
                   - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))) / 2


def _signed_area(poly) -> float:
    return sum(poly[i][0] * poly[(i + 1) % len(poly)][1]
               - poly[(i + 1) % len(poly)][0] * poly[i][1]
               for i in range(len(poly))) / 2


def inset(poly: "list[Point]", d: float) -> "list[Point]":
    """`poly` (anticlockwise) with every edge moved `d` inward.

    Each vertex goes to the meeting point of its two moved edges. Where the
    edges are collinear -- a vertex that only marks a change of status along a
    straight side -- there is no meeting point and the vertex simply moves
    inward with the side, so it SURVIVES: dropping it would erase the status
    change (docs/dom-format-v2.md, Perimeter). Reflex corners work the same
    way as convex ones, which `geometry.offset_quad`'s bisector does not.
    """
    n = len(poly)
    lines = []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < EPS:
            raise CellsError(f"plot vertices {i} and {(i + 1) % n} coincide")
        nx, ny = -dy / length, dx / length          # inward, for anticlockwise
        lines.append(((a[0] + nx * d, a[1] + ny * d), (dx / length, dy / length)))
    out = []
    for i in range(n):
        (p, r), (q, s) = lines[i - 1], lines[i]
        cross = r[0] * s[1] - r[1] * s[0]
        if abs(cross) < 1e-12:                       # collinear: slide with the side
            nx, ny = -s[1], s[0]
            out.append([poly[i][0] + nx * d, poly[i][1] + ny * d])
            continue
        t = ((q[0] - p[0]) * s[1] - (q[1] - p[1]) * s[0]) / cross
        out.append([p[0] + t * r[0], p[1] + t * r[1]])
    return out


def clip(poly, rect, u, v) -> "list[Point]":
    """`poly` intersected with the frame rectangle `rect` (Sutherland-Hodgman).

    Vertices of `poly` inside the rectangle are kept as they are, collinear
    ones included; only exactly repeated points are dropped. The rectangle is
    convex, so this is exact for a convex plot and for any plot whose
    intersection with the rectangle is one piece. A plot concave enough to
    cross a cell twice gives the two pieces joined along the rectangle's edge,
    with the right area.
    """
    pts = [(p[0] * u[0] + p[1] * u[1], p[0] * v[0] + p[1] * v[1]) for p in poly]
    u0, u1, v0, v1 = rect
    for axis, bound, keep_ge in ((0, u0, True), (0, u1, False),
                                 (1, v0, True), (1, v1, False)):
        out = []
        for i, cur in enumerate(pts):
            prev = pts[i - 1]
            cin = cur[axis] >= bound - EPS if keep_ge else cur[axis] <= bound + EPS
            pin = prev[axis] >= bound - EPS if keep_ge else prev[axis] <= bound + EPS
            if cin != pin:
                t = (bound - prev[axis]) / (cur[axis] - prev[axis])
                out.append((prev[0] + t * (cur[0] - prev[0]),
                            prev[1] + t * (cur[1] - prev[1])))
            if cin:
                out.append(cur)
        pts = out
        if not pts:
            return []
    keep = []
    for p in pts:
        if not keep or math.dist(p, keep[-1]) > EPS:
            keep.append(p)
    if len(keep) > 1 and math.dist(keep[0], keep[-1]) <= EPS:
        keep.pop()
    if len(keep) < 3:
        return []
    return [[q[0] * u[0] + q[1] * v[0], q[0] * u[1] + q[1] * v[1]] for q in keep]


def corners(poly: "list[Point]") -> "list[Point]":
    """`poly` without its collinear vertices: the shape, not the statuses."""
    out = []
    n = len(poly)
    for i, p in enumerate(poly):
        a, b = poly[i - 1], poly[(i + 1) % n]
        cross = (p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])
        if abs(cross) > EPS:
            out.append(p)
    return out


# --------------------------------------------------------------------------- #
# the shape score
# --------------------------------------------------------------------------- #
def usable_rectangle(poly, u=(1.0, 0.0), v=(0.0, 1.0),
                     grid: int = 48) -> "tuple[float, float]":
    """``(extent along u, extent along v)`` of the largest frame-aligned
    rectangle inside the convex cell `poly`; ``(0, 0)`` for an empty one.

    Exact up to the grid: for a convex cell the lower boundary is convex and
    the upper concave, so the tallest rectangle over [x0, x1] is fixed by its
    two ends, and every vertex is a candidate end.
    """
    pts = [(p[0] * u[0] + p[1] * u[1], p[0] * v[0] + p[1] * v[1]) for p in poly]
    if area(pts) < EMPTY_AREA:
        return 0.0, 0.0
    xs = sorted({x for x, _ in pts})
    lo, hi = xs[0], xs[-1]
    cand = sorted(set(xs) | {lo + (hi - lo) * i / grid for i in range(grid + 1)})
    n = len(pts)

    def extent(x):
        ys = []
        for i in range(n):
            (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % n]
            if min(x1, x2) - 1e-12 <= x <= max(x1, x2) + 1e-12:
                if abs(x2 - x1) < 1e-12:
                    ys += [y1, y2]
                else:
                    ys.append(y1 + (y2 - y1) * (x - x1) / (x2 - x1))
        return (min(ys), max(ys)) if ys else (0.0, 0.0)

    ext = [extent(x) for x in cand]
    best = (0.0, 0.0, 0.0)
    for i, x0 in enumerate(cand):
        for j in range(i + 1, len(cand)):
            h = min(ext[i][1], ext[j][1]) - max(ext[i][0], ext[j][0])
            if h > 0 and (cand[j] - x0) * h > best[0]:
                best = ((cand[j] - x0) * h, cand[j] - x0, h)
    return best[1], best[2]


def usable_fraction(poly, u=(1.0, 0.0), v=(0.0, 1.0), grid: int = 48) -> float:
    """The largest frame-aligned rectangle inside the cell, over the cell's
    area (DESIGN.md §39.90; owner: "some five sided spaces are actually quads
    and some are awkward pentagons that are only good for garden space").

    A rectangle scores 1, and so does a rectangle carrying a collinear
    street/party vertex; a lightly clipped corner a little under 1; a wedge or
    a triangle 0.5.
    """
    a = area(poly)
    if a < EMPTY_AREA:
        return 0.0
    du, dv = usable_rectangle(poly, u, v, grid)
    return min(1.0, du * dv / a)


def shape_quality(fraction: float) -> float:
    """The quality factor for a usable fraction: 1 from 0.85 up, 0.1 (the fail
    line) at 0.70, a Gaussian between and below."""
    if fraction >= SHAPE_FULL:
        return 1.0
    return math.exp(-((SHAPE_FULL - fraction) ** 2) / (2 * SHAPE_SIGMA ** 2))


# --------------------------------------------------------------------------- #
# document -> cells
# --------------------------------------------------------------------------- #
def build(doc: dict) -> Layout:
    """Every cell of a parsed format-v2 document."""
    from .dom_v2 import FORMAT, VERSION

    if doc.get("format") != FORMAT or doc.get("version") != VERSION:
        raise CellsError("not a homemaker-dom version 2 document")
    if "blocks" in doc:
        raise CellsError("`blocks` is reserved and not implemented")
    plot = [[float(p[0]), float(p[1])] for p in doc["plot"]]
    if len(plot) < 3:
        raise CellsError("a plot needs at least three vertices")
    if _signed_area(plot) <= 0:
        raise CellsError("the plot must be listed anticlockwise")
    perimeter = list(doc.get("perimeter") or [None] * len(plot))
    if len(perimeter) != len(plot):
        raise CellsError("`perimeter` must have one entry per plot edge")
    wall_outer = float(doc["wall_outer"]) if doc.get("wall_outer") is not None else 0.25

    fu = doc.get("frame", {}).get("u")
    if fu is None:
        raise CellsError("v2 file has no frame.u")
    norm = math.hypot(float(fu[0]), float(fu[1]))
    if norm < EPS:
        raise CellsError("frame.u is the zero vector")
    u = (float(fu[0]) / norm, float(fu[1]) / norm)
    v = (-u[1], u[0])

    inner = inset(plot, wall_outer)
    pu = [p[0] * u[0] + p[1] * u[1] for p in inner]
    pv = [p[0] * v[0] + p[1] * v[1] for p in inner]
    box = (min(pu), max(pu), min(pv), max(pv))
    layout = Layout(u, v, plot, inner, box, perimeter)

    below: "dict[str, tuple[str, float]]" = {}      # path -> (axis, position)
    for si, storey in enumerate(doc.get("storeys") or []):
        cuts: "dict[str, tuple[str, float]]" = {}
        cells: "list[Cell]" = []

        def walk(spec, rect, path, si=si, cuts=cuts, cells=cells, below=below):
            where = f"storey {si} {path or 'root'}"
            if not isinstance(spec, dict):
                raise CellsError(f"{where}: a node must be a mapping")
            if "cell" in spec:
                kind = None if spec["cell"] is None else str(spec["cell"])
                cells.append(Cell(si, path, kind, tuple(rect),
                                  clip(inner, rect, u, v),
                                  int(spec.get("share") or 1),
                                  spec.get("co_type")))
                return
            if "low" not in spec or "high" not in spec:
                raise CellsError(f"{where}: a node is a `cell` or has `low` and `high`")
            if path in below:
                if "cut" in spec or "at" in spec:
                    raise CellsError(f"{where}: the storey below is cut here, so "
                                     "this storey inherits it and must not "
                                     "write `cut`/`at`")
                axis, s = below[path]
            else:
                if spec.get("cut") not in ("u", "v") or "at" not in spec:
                    raise CellsError(f"{where}: a cut needs `cut: u|v` and `at`")
                at = float(spec["at"])
                if not 0.0 < at < 1.0:
                    raise CellsError(f"{where}: `at` is {at}, outside (0, 1)")
                axis = spec["cut"]
                lo, hi = (rect[2], rect[3]) if axis == "u" else (rect[0], rect[1])
                s = lo + at * (hi - lo)
            cuts[path] = (axis, s)
            low, high = list(rect), list(rect)
            if axis == "u":                 # a line ALONG u fixes v
                low[3] = high[2] = s
            else:
                low[1] = high[0] = s
            walk(spec["low"], low, path + "l")
            walk(spec["high"], high, path + "h")

        if "tree" not in storey:
            raise CellsError(f"storey {si} has no `tree`")
        walk(storey["tree"], list(box), "")
        layout.storeys.append(cells)
        below = cuts
    return layout


def edge_sides(cell: Cell, layout: Layout) -> "list[int | None]":
    """For each edge of the cell's polygon, the index of the plot edge it lies
    on, or None for an interior wall. A side whose status changes part-way
    arrives as two edges, each on its own plot edge."""
    out: "list[int | None]" = []
    poly, inner = cell.polygon, layout.inner
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        hit = None
        for k in range(len(inner)):
            p, q = inner[k], inner[(k + 1) % len(inner)]
            if abs(math.dist(p, mid) + math.dist(mid, q) - math.dist(p, q)) < 1e-7:
                dx, dy = q[0] - p[0], q[1] - p[1]
                ex, ey = b[0] - a[0], b[1] - a[1]
                if abs(dx * ey - dy * ex) < 1e-7 * max(1.0, math.hypot(dx, dy)):
                    hit = k
                    break
        out.append(hit)
    return out


# --------------------------------------------------------------------------- #
# shared walls
# --------------------------------------------------------------------------- #
def shared_wall(a: "list[Point]", b: "list[Point]"):
    """The longest stretch of boundary two cell polygons share:
    ``(length, [p, q])``, or ``(0.0, None)`` if they share none.

    Two edges share a stretch when they lie on one line and their spans along
    it overlap. Edges that only meet end to end share nothing -- the overlap is
    floored at EPS, which is the whole of `homemaker-py-khgi` in one line.
    """
    best = (0.0, None)
    for i in range(len(a)):
        p, q = a[i], a[(i + 1) % len(a)]
        dx, dy = q[0] - p[0], q[1] - p[1]
        length = math.hypot(dx, dy)
        if length < EPS:
            continue
        ux, uy = dx / length, dy / length
        for k in range(len(b)):
            r, s = b[k], b[(k + 1) % len(b)]
            # both ends of the other edge on this edge's line?
            if abs((r[0] - p[0]) * uy - (r[1] - p[1]) * ux) > 1e-7 or \
                    abs((s[0] - p[0]) * uy - (s[1] - p[1]) * ux) > 1e-7:
                continue
            t0 = (r[0] - p[0]) * ux + (r[1] - p[1]) * uy
            t1 = (s[0] - p[0]) * ux + (s[1] - p[1]) * uy
            lo, hi = max(0.0, min(t0, t1)), min(length, max(t0, t1))
            if hi - lo > max(EPS, best[0]):
                best = (hi - lo, [[p[0] + lo * ux, p[1] + lo * uy],
                                  [p[0] + hi * ux, p[1] + hi * uy]])
    return best


def adjacency(storey: "list[Cell]", door_width: float = 1.2):
    """``[(i, j, width, [p, q]), ...]``: every pair of non-empty cells on one
    storey sharing at least a door's width of wall."""
    out = []
    live = [(i, c) for i, c in enumerate(storey) if not c.empty]
    for x, (i, a) in enumerate(live):
        for j, b in live[x + 1:]:
            # rectangles that do not touch cannot share a wall
            if a.rect[0] > b.rect[1] + EPS or b.rect[0] > a.rect[1] + EPS \
                    or a.rect[2] > b.rect[3] + EPS or b.rect[2] > a.rect[3] + EPS:
                continue
            width, seg = shared_wall(a.polygon, b.polygon)
            if width >= door_width:
                out.append((i, j, width, seg))
    return out

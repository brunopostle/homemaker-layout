"""SVG trace + boundary ``.dom`` -> full slicing-tree ``.dom`` (homemaker-py-2g7.1).

Ground-truth problem: every non-empty ``.dom`` in this repo is evolution
output, so nobody has ever measured what a *known-good human design* scores
under ``fitness.py``. This module builds one from a hand trace instead of
requiring a hand-authored YAML tree (impractical) or hand-drawn room shapes
(don't line up between storeys or with each other on a rough sketch).

Trace format (see ``DESIGN.md`` sec 37.x for the full write-up):

* A "boundary" ``.dom`` file supplies everything geometric that ISN'T a
  guillotine-cut topology: the plot outline (level 0's ``node``), per-storey
  ``height``/``elevation``, ``wall_inner``/``wall_outer``, ``perimeter``.
  It has no ``division``/``type`` — ``dom.load()`` parses it as-is. Urb's own
  model requires every storey to share the ground-floor footprint exactly
  (``geometry.coordinate`` always derives an upper level root from the level
  below), so there is exactly one outline, not one per storey.
* An SVG file supplies the topology: one Inkscape layer per storey, named
  ``storey-0``, ``storey-1``, ... Each layer holds only straight open cut
  lines (``<line>`` or a 2-point ``<path d="M.. L..">``) and text labels
  (room type codes). No closed room shapes are ever drawn — a room's outline
  is *derived*, not traced, which is what makes this robust to a rough
  sketch (lines that overlap slightly, undershoot a corner, or don't quite
  align between storeys all fall within a tolerance).

Composition works by mirroring ``geometry.py``'s own division-line algebra:
starting from the plot quad, recursively look for a traced line that spans
the current quad edge-to-edge (a "guillotine cut" test with a snapping
tolerance), split into two child quads via the exact corner formulas
``geometry.coordinate``/``coord_a``/``coord_b`` use, and recurse. A region
with interior lines but none spanning it is not representable as a guillotine
partition — reported via ``NonSlicible`` naming the region, per the bead's
acceptance criteria, rather than silently guessed at.

Traced cut *positions* only need to be roughly right: ``refine()`` calls
``solver.solve_ratios(..., strip=False)`` to slide them to the best fit for
the programme's target dimensions afterward, keeping the traced topology
fixed.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .dom import Node, levels, link

Point = tuple[float, float]

_SVG_NS = "http://www.w3.org/2000/svg"
_INK_NS = "http://www.inkscape.org/namespaces/inkscape"
_STOREY_RE = re.compile(r"^storey-(\d+)$")


def _qn(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


@dataclass
class StoreyTrace:
    lines: list[tuple[Point, Point]] = field(default_factory=list)
    labels: list[tuple[Point, str]] = field(default_factory=list)


class NonSlicible(Exception):
    """A traced region has interior cut lines but none spans it edge-to-edge
    — not representable as a guillotine slicing tree."""

    def __init__(self, storey: int, corners: list[Point]):
        self.storey = storey
        self.corners = corners
        cx = sum(p[0] for p in corners) / 4
        cy = sum(p[1] for p in corners) / 4
        super().__init__(
            f"storey {storey}: region around ({cx:.2f}, {cy:.2f}) "
            f"(corners {corners}) has cut lines that don't fully divide it "
            "into two — not a guillotine partition"
        )


class LabelError(Exception):
    """A leaf region has zero or more than one room label."""

    def __init__(self, storey: int, corners: list[Point], labels: list[str]):
        self.storey = storey
        self.corners = corners
        self.labels = labels
        cx = sum(p[0] for p in corners) / 4
        cy = sum(p[1] for p in corners) / 4
        super().__init__(
            f"storey {storey}: leaf region around ({cx:.2f}, {cy:.2f}) has "
            f"{len(labels)} label(s) {labels!r}, expected exactly 1"
        )


# --------------------------------------------------------------------------- #
# SVG parsing
# --------------------------------------------------------------------------- #

Matrix = tuple[float, float, float, float, float, float]  # a b c d e f
_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mat_mul(m1: Matrix, m2: Matrix) -> Matrix:
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _apply(m: Matrix, p: Point) -> Point:
    a, b, c, d, e, f = m
    return (a * p[0] + c * p[1] + e, b * p[0] + d * p[1] + f)


_TRANSFORM_RE = re.compile(r"(\w+)\s*\(([^)]*)\)")


def _parse_transform(s: str | None) -> Matrix:
    if not s:
        return _IDENTITY
    m = _IDENTITY
    for name, args in _TRANSFORM_RE.findall(s):
        nums = [float(x) for x in re.split(r"[,\s]+", args.strip()) if x]
        if name == "translate":
            part: Matrix = (1, 0, 0, 1, nums[0], nums[1] if len(nums) > 1 else 0.0)
        elif name == "scale":
            sx = nums[0]
            sy = nums[1] if len(nums) > 1 else sx
            part = (sx, 0, 0, sy, 0, 0)
        elif name == "matrix":
            part = (nums[0], nums[1], nums[2], nums[3], nums[4], nums[5])
        elif name == "rotate":
            theta = math.radians(nums[0])
            cos_t, sin_t = math.cos(theta), math.sin(theta)
            rot: Matrix = (cos_t, sin_t, -sin_t, cos_t, 0, 0)
            if len(nums) == 3:
                cx, cy = nums[1], nums[2]
                part = _mat_mul(_mat_mul((1, 0, 0, 1, cx, cy), rot), (1, 0, 0, 1, -cx, -cy))
            else:
                part = rot
        else:
            continue  # skewX/skewY: not needed for straight hand traces
        m = _mat_mul(m, part)
    return m


_PATH_CMD_RE = re.compile(r"([MLZmlz])\s*([^MLZmlz]*)")


def _parse_path_line(d: str) -> tuple[Point, Point] | None:
    """A straight 2-point path ``M x,y L x,y`` (absolute only); None if this
    isn't a simple straight segment (curves, more than 2 points, ...)."""
    pts: list[Point] = []
    for cmd, args in _PATH_CMD_RE.findall(d):
        if cmd.upper() == "Z":
            continue
        if cmd not in ("M", "L"):
            return None
        nums = [float(x) for x in re.split(r"[,\s]+", args.strip()) if x]
        if len(nums) != 2:
            return None
        pts.append((nums[0], nums[1]))
    if len(pts) != 2:
        return None
    return pts[0], pts[1]


def _walk(el: ET.Element, xf: Matrix, storey: StoreyTrace) -> None:
    xf = _mat_mul(xf, _parse_transform(el.get("transform")))
    tag = el.tag.rsplit("}", 1)[-1]
    if tag == "line":
        p1 = _apply(xf, (float(el.get("x1")), float(el.get("y1"))))
        p2 = _apply(xf, (float(el.get("x2")), float(el.get("y2"))))
        storey.lines.append((p1, p2))
    elif tag == "path":
        d = el.get("d") or ""
        pts = _parse_path_line(d)
        if pts is None:
            raise ValueError(f"unsupported non-straight-2-point cut path: {d!r}")
        storey.lines.append((_apply(xf, pts[0]), _apply(xf, pts[1])))
    elif tag == "text":
        x, y = el.get("x"), el.get("y")
        tspan = el.find(_qn(_SVG_NS, "tspan"))
        if tspan is not None and tspan.get("x") is not None:
            x, y = tspan.get("x"), tspan.get("y")
        text = "".join(el.itertext()).strip()
        if x is not None and y is not None and text:
            storey.labels.append((_apply(xf, (float(x), float(y))), text))
    for child in el:
        _walk(child, xf, storey)


def parse_svg(path: str, scale: float = 1.0) -> list[StoreyTrace]:
    """Parse ``storey-N`` Inkscape layers into per-storey traces, storey 0
    first. Layers must be flat (not nested inside one another)."""
    root = ET.parse(path).getroot()
    root_xf = _parse_transform(root.get("transform"))
    storeys: dict[int, StoreyTrace] = {}
    for g in root.iter(_qn(_SVG_NS, "g")):
        if g.get(_qn(_INK_NS, "groupmode")) != "layer":
            continue
        m = _STOREY_RE.match((g.get(_qn(_INK_NS, "label")) or "").strip())
        if not m:
            continue
        trace = storeys.setdefault(int(m.group(1)), StoreyTrace())
        _walk(g, root_xf, trace)
    if not storeys:
        raise ValueError(f"{path}: no 'storey-N' Inkscape layers found")
    result = [storeys.get(i, StoreyTrace()) for i in range(max(storeys) + 1)]
    if scale != 1.0:
        result = [
            StoreyTrace(
                lines=[
                    ((p[0] * scale, p[1] * scale), (q[0] * scale, q[1] * scale))
                    for p, q in t.lines
                ],
                labels=[((p[0] * scale, p[1] * scale), s) for p, s in t.labels],
            )
            for t in result
        ]
    return result


# --------------------------------------------------------------------------- #
# Geometry: mirrors geometry.py's division-line algebra (coordinate/coord_a/
# coord_b) so composed rotation+division values reproduce these exact corners
# when the engine re-derives them top-down.
# --------------------------------------------------------------------------- #


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _interp(a: Point, b: Point, t: float) -> Point:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _nearest_on_segment(p: Point, a: Point, b: Point) -> tuple[Point, float]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return a, 0.0
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length_sq
    t_clamped = max(0.0, min(1.0, t))
    return (a[0] + t_clamped * dx, a[1] + t_clamped * dy), t_clamped


def _near_edge(p: Point, a: Point, b: Point, tol: float) -> float | None:
    """Clamped projection parameter (0=a, 1=b) if p is within tol of segment
    a-b, else None."""
    nearest, t = _nearest_on_segment(p, a, b)
    return t if _dist(p, nearest) <= tol else None


def _side(p: Point, a: Point, b: Point) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _find_span(
    corners: list[Point], lines: list[tuple[Point, Point]], tol: float
) -> tuple[int, tuple[float, float], tuple[Point, Point]] | None:
    """Best line spanning ``corners`` edge-to-edge on either axis: axis 0 =
    edges (0,1)&(3,2), axis 1 = edges (1,2)&(0,3) — mirrors the two edge
    pairs ``geometry.coord_a``/``coord_b`` can address via ``rotation``."""
    axes = (
        (0, corners[0], corners[1], corners[3], corners[2]),
        (1, corners[1], corners[2], corners[0], corners[3]),
    )
    best = None
    best_err = None
    for axis, ea0, ea1, eb0, eb1 in axes:
        for p, q in lines:
            for p1, p2 in ((p, q), (q, p)):
                t0 = _near_edge(p1, ea0, ea1, tol)
                t1 = _near_edge(p2, eb0, eb1, tol)
                if t0 is None or t1 is None:
                    continue
                err = _dist(p1, _interp(ea0, ea1, t0)) + _dist(p2, _interp(eb0, eb1, t1))
                if best_err is None or err < best_err:
                    best_err = err
                    best = (axis, (t0, t1), (p, q))
    return best


def _build(
    storey: int,
    corners: list[Point],
    lines: list[tuple[Point, Point]],
    labels: list[tuple[Point, str]],
    tol: float,
) -> Node:
    span = _find_span(corners, lines, tol)
    if span is None:
        if not lines:
            texts = [text for _, text in labels]
            if len(texts) != 1:
                raise LabelError(storey, corners, texts)
            leaf = Node()
            leaf.type = texts[0]
            return leaf
        raise NonSlicible(storey, corners)

    axis, (t0, t1), chosen = span
    idx = lines.index(chosen)
    other_lines = lines[:idx] + lines[idx + 1 :]

    if axis == 0:
        coord_a = _interp(corners[0], corners[1], t0)
        coord_b = _interp(corners[3], corners[2], t1)
        left_corners = [corners[0], coord_a, coord_b, corners[3]]
        right_corners = [coord_a, corners[1], corners[2], coord_b]
        rotation = 0
    else:
        coord_a = _interp(corners[1], corners[2], t0)
        coord_b = _interp(corners[0], corners[3], t1)
        left_corners = [corners[1], coord_a, coord_b, corners[0]]
        right_corners = [coord_a, corners[2], corners[3], coord_b]
        rotation = 1

    ref_side = _side(left_corners[0], coord_a, coord_b)

    def is_left(p: Point) -> bool:
        return (_side(p, coord_a, coord_b) >= 0) == (ref_side >= 0)

    left_lines, right_lines = [], []
    for p, q in other_lines:
        mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        (left_lines if is_left(mid) else right_lines).append((p, q))

    left_labels, right_labels = [], []
    for pt, text in labels:
        (left_labels if is_left(pt) else right_labels).append((pt, text))

    node = Node()
    node.rotation = rotation
    node.division = [t0, t1]
    node.left = _build(storey, left_corners, left_lines, left_labels, tol)
    node.right = _build(storey, right_corners, right_lines, right_labels, tol)
    return node


# --------------------------------------------------------------------------- #
# Compose
# --------------------------------------------------------------------------- #


def compose(boundary_root: Node, storeys: list[StoreyTrace], tol: float = 0.15) -> Node:
    """Fill in ``division``/``left``/``right`` on each level of
    ``boundary_root`` (as loaded by ``dom.load()``) from the traced storeys,
    and return the fully-linked, re-composed root."""
    level_roots = levels(boundary_root)
    if len(storeys) != len(level_roots):
        raise ValueError(
            f"boundary dom has {len(level_roots)} storey(s), trace has {len(storeys)}"
        )

    # A human traces against the plot's visible (outer wall face) boundary,
    # not the wall_outer-inset working quad dom.load() computes -- so match
    # against node_file (the raw corners as authored), same frame the file's
    # author drew the boundary quad in.
    plot = level_roots[0].node_file or level_roots[0].node
    if plot is None or len(plot) != 4:
        raise ValueError("boundary dom's level-0 root must have a 4-corner 'node'")
    corners = [(float(p[0]), float(p[1])) for p in plot]

    for i, (level_root, trace) in enumerate(zip(level_roots, storeys)):
        built = _build(i, corners, trace.lines, trace.labels, tol)
        level_root.division = built.division
        level_root.left = built.left
        level_root.right = built.right
        level_root.rotation = built.rotation
        level_root.type = built.type
        if i == 0:
            # Every storey above sees level 0's own *rotation-adjusted*
            # corners (geometry.coordinate() always derives an upper root
            # from the level below via the below-link, using level 0's
            # final rotation) -- not necessarily plot's raw file order.
            corners = [
                (float(plot[(k + level_root.rotation) % 4][0]),
                 float(plot[(k + level_root.rotation) % 4][1]))
                for k in range(4)
            ]

    link(boundary_root)
    from . import geometry

    geometry.clear_cache()
    return boundary_root


def refine(root: Node, programme_dir: str) -> None:
    """Slide the traced cuts to the best fit for the programme's target
    dimensions, keeping the traced topology fixed -- trace precision only
    needs to get the structure right, not the exact ratios."""
    from . import solver
    from .programme import load_programme_dir

    solver.solve_ratios(root, load_programme_dir(programme_dir), strip=False)

"""`homemaker-py-8b2u.4`, step 2: can the scorer's per-room measures and its
adjacency graph be taken from native cells, and what moves if they are?

The scorer reads a leaf through a handful of `geometry` functions written for
quads: `area` (two Heron triangles), `length_narrowest` (the shortest of four
EDGES), `aspect` (opposite edge pairs), and `leaf_graph` (pairs of leaves on
one tree boundary whose edges overlap by a door width). A cropped cell can be
a pentagon with a 30 cm edge where its corner was clipped, so "shortest edge"
and "opposite edges" have to become something that means the same for any
cell. The candidate is the USABLE RECTANGLE -- the largest frame-aligned
rectangle inside the cell, the one the shape score is already built on:

    area         the polygon's own (unchanged)
    width        the usable rectangle's short side
    proportion   its long side over its short side

This measures, on every orthogonal artefact, how far those are from today's on
the cells today's geometry draws (all quads); what the corpus scores under
them; and whether the native adjacency graph is today's graph.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_8b2u4_measures.py
"""

from __future__ import annotations

import collections
import importlib.util
import statistics
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from homemaker_layout import cells, dom, geometry as g  # noqa: E402


def _rt():
    spec = importlib.util.spec_from_file_location(
        "_rt", REPO / "experiments" / "diag_8b2u2_roundtrip.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def quad(leaf):
    return [g.coordinate(leaf, i) for i in range(4)]


def usable_width(leaf) -> float:
    u, v = g._reference_axes(leaf)
    return min(cells.usable_rectangle(quad(leaf), u, v))


def usable_aspect(leaf) -> float:
    u, v = g._reference_axes(leaf)
    a, b = cells.usable_rectangle(quad(leaf), u, v)
    return max(a, b) / min(a, b) if min(a, b) > 0 else 1.0


def _frame_points(leaf):
    u, v = g._reference_axes(leaf)
    return [(p[0] * u[0] + p[1] * u[1], p[0] * v[0] + p[1] * v[1]) for p in quad(leaf)]


def _extents(leaf):
    pts = _frame_points(leaf)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return max(xs) - min(xs), max(ys) - min(ys)


def bbox_width(leaf) -> float:
    return min(_extents(leaf))


def bbox_aspect(leaf) -> float:
    a, b = _extents(leaf)
    return max(a, b) / min(a, b)


def chord_width(leaf) -> float:
    """Mean extent: the area over the extent across it, the smaller of the two."""
    a, b = _extents(leaf)
    area = cells.area(quad(leaf))
    return min(area / a, area / b)


def chord_aspect(leaf) -> float:
    """Mean chord along the long axis over the extent across it -- what
    today's (e0+e2)/(e1+e3) amounts to for a cell cropped on one side."""
    a, b = _extents(leaf)
    area = cells.area(quad(leaf))
    x = (area / b) / b if a >= b else (area / a) / a
    return x if x >= 1 else 1 / x


def moments_aspect(leaf) -> float:
    """Ratio of the cell's spreads along the two frame axes (second moments)."""
    import math
    pts = _frame_points(leaf)
    n = len(pts)
    a = cx = cy = 0.0
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        c = x0 * y1 - x1 * y0
        a += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    a /= 2
    cx, cy = cx / (6 * a), cy / (6 * a)
    ixx = iyy = 0.0
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        x0, x1, y0, y1 = x0 - cx, x1 - cx, y0 - cy, y1 - cy
        c = x0 * y1 - x1 * y0
        ixx += (y0 * y0 + y0 * y1 + y1 * y1) * c
        iyy += (x0 * x0 + x0 * x1 + x1 * x1) * c
    su, sv = math.sqrt(abs(iyy / 12 / a)), math.sqrt(abs(ixx / 12 / a))
    return max(su, sv) / min(su, sv)


# Every way tried of saying "width" and "proportion" of a cell that need not
# be a quad. The first of each is the candidate; the rest are what it was
# weighed against (DESIGN.md §39.101).
WIDTHS = {"usable rectangle": usable_width, "bounding box": bbox_width,
          "mean chord": chord_width}
ASPECTS = {"usable rectangle": usable_aspect, "bounding box": bbox_aspect,
           "second moments": moments_aspect, "mean chord / extent": chord_aspect}


def match(root, layout) -> dict:
    """{leaf: cell} by storey, type and corners."""
    import math
    out, rest = {}, list(layout.cells())
    for li, lvl in enumerate(dom.levels(root)):
        for leaf in lvl.leaves():
            q = quad(leaf)
            for c in rest:
                k = cells.corners(c.polygon)
                if c.storey == li and c.type == leaf.type and len(k) == 4 \
                        and all(min(math.dist(p, x) for x in q) < 1e-6 for p in k):
                    out[leaf] = c
                    rest.remove(c)
                    break
    return out


def main() -> int:
    g.ORTHOGONAL_DIVISION = True
    rt = _rt()
    rel = collections.defaultdict(list)
    graph = collections.Counter()
    score = collections.defaultdict(collections.Counter)
    today_w, today_a = g.length_narrowest, g.aspect
    for p, prog in rt.corpus():
        root = dom.load(str(p))
        layout = cells.build(yaml.safe_load(dom.dumps(root, version=2)))
        pair = match(root, layout)
        index = {id(c): i for s in layout.storeys for i, c in enumerate(s)}
        for li, lvl in enumerate(dom.levels(root)):
            for leaf in lvl.leaves():
                rel["area"].append(abs(pair[leaf].area - g.area(leaf)) / g.area(leaf))
                w0, a0 = today_w(leaf), today_a(leaf)
                for name, fn in WIDTHS.items():
                    rel["width: " + name].append(abs(fn(leaf) - w0) / w0)
                for name, fn in ASPECTS.items():
                    rel["proportion: " + name].append(abs(fn(leaf) - a0) / a0)
            G = g.leaf_graph(lvl)
            today = {frozenset((index[id(pair[a])], index[id(pair[b])])): d["width"]
                     for a, b, d in G.edges(data=True)}
            native = {frozenset((i, j)): w
                      for i, j, w, _ in cells.adjacency(layout.storeys[li])}
            graph["walls today"] += len(today)
            graph["walls native"] += len(native)
            graph["only today"] += len(set(today) - set(native))
            graph["only native"] += len(set(native) - set(today))
            graph["same pair, other width"] += sum(
                abs(today[k] - native[k]) > 1e-6 for k in set(today) & set(native))
        g.clear_cache()
        s0, f0 = rt.score(root, prog)
        for kind, cands in (("width", WIDTHS), ("proportion", ASPECTS)):
            for name, fn in cands.items():
                if kind == "width":
                    g.length_narrowest = fn
                else:
                    g.aspect = fn
                try:
                    s, f = rt.score(root, prog)
                finally:
                    g.length_narrowest, g.aspect = today_w, today_a
                row = score[f"{kind}: {name}"]
                row["moved"] += rt.differs(s, s0, 1e-9)
                row["over 1%"] += abs(s / s0 - 1) > 0.01
                row["f0"] += len(f0)
                row["f1"] += len(f)

    n = len(rel["area"])
    print(f"{n} cells; area differs from today's by at most "
          f"{100 * max(rel['area']):.6f}%")
    print("adjacency:", dict(graph), "\n")
    print(f"{'against today\'s quad formula':32} {'same':>5} {'median':>8} {'p99':>7} "
          f"{'max':>7}   scores moved (>1%)   fails")
    for key in [k for k in rel if k != "area"]:
        v, r = rel[key], score[key]
        print(f"{key:32} {100 * sum(x < 1e-9 for x in v) / n:4.0f}% "
              f"{100 * statistics.median(v):7.3f}% {100 * sorted(v)[int(.99 * n)]:6.2f}% "
              f"{100 * max(v):6.1f}%   {r['moved']:3d} ({r['over 1%']:3d})          "
              f"{r['f0']} -> {r['f1']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

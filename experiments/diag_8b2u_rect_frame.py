"""`homemaker-py-8b2u`: is the rectangle-frame pivot a REPARAMETERISATION?

The owner's proposal: subdivide a rectangle that encloses the plot, aligned by
the longest-boundary heuristic, and crop the cells to the plot before scoring.
With `HOMEMAKER_ORTHOGONAL_DIVISION` on, every cut is already an axial line, so
every cell should already be (axis-aligned rectangle) intersected with (plot).
If that holds exactly, the pivot changes how cuts are PARAMETERISED -- a ratio
along a skew edge becomes a position in a rectangle -- and not which buildings
exist, and every corpus artefact translates rather than being thrown away.

`--translate` (experiment 1) tests that, round trip:

  1. forward: each cut, as `geometry` computes it, becomes (axis, position in
     the parent's RECTANGLE, which side holds the left child) -- nothing else;
  2. rebuild: from those numbers alone, split the plot's bounding rectangle
     recursively and clip each leaf rectangle to the plot polygon;
  3. compare every rebuilt cell with `geometry`'s own cell: same area, same
     corners.

It also counts the cases that cannot translate: a cut `_orthogonal_b` could not
make axial (it falls back to the stored offset when the axial line misses the
far edge) is a SKEW cut, which the rectangle frame cannot express.

`--crop-census` (experiment 3) asks what a FREE crop would produce: the same
trees, but with each cut's position taken over its parent's RECTANGLE rather
than its clipped cell -- so cells near a skew edge can become triangles or
pentagons, or vanish. Triangles and pentagons are accepted but scored down
(owner's ruling, 2026-10-04); this counts how often they would arise.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_8b2u_rect_frame.py --translate
"""

from __future__ import annotations

import argparse
import collections
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from homemaker_layout import dom, geometry as g  # noqa: E402

PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
CORPUS = "coldstart-*+orth-500000-s*.dom"
AXIAL_TOL = 1e-7          # |sin| of a cut's angle to its axis
MATCH_TOL = 1e-6          # metres, corner to corner


# --------------------------------------------------------------------------- #
# polygon helpers
# --------------------------------------------------------------------------- #
def clip(poly, lo_u, hi_u, lo_v, hi_v, u, v):
    """Sutherland-Hodgman clip of `poly` to the (u, v)-rectangle."""
    def proj(p):
        return (p[0] * u[0] + p[1] * u[1], p[0] * v[0] + p[1] * v[1])

    def back(q):
        return [q[0] * u[0] + q[1] * v[0], q[0] * u[1] + q[1] * v[1]]

    pts = [proj(p) for p in poly]
    for axis, bound, keep_ge in ((0, lo_u, True), (0, hi_u, False),
                                 (1, lo_v, True), (1, hi_v, False)):
        out = []
        for i, cur in enumerate(pts):
            prev = pts[i - 1]
            cin = cur[axis] >= bound if keep_ge else cur[axis] <= bound
            pin = prev[axis] >= bound if keep_ge else prev[axis] <= bound
            if cin != pin:
                t = (bound - prev[axis]) / (cur[axis] - prev[axis])
                out.append((prev[0] + t * (cur[0] - prev[0]),
                            prev[1] + t * (cur[1] - prev[1])))
            if cin:
                out.append(cur)
        pts = out
        if not pts:
            return []
    return [back(q) for q in pts]


def dedupe(poly, tol=MATCH_TOL):
    out = []
    for p in poly:
        if not out or math.dist(p, out[-1]) > tol:
            out.append(p)
    if len(out) > 1 and math.dist(out[0], out[-1]) <= tol:
        out.pop()
    # drop collinear points: a clip along an edge can leave one
    keep = []
    for i, p in enumerate(out):
        a, b = out[i - 1], out[(i + 1) % len(out)]
        cross = (p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])
        if abs(cross) > 1e-9:
            keep.append(p)
    return keep


def area(poly):
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1]
                   - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))) / 2


def same_polygon(a, b):
    if abs(area(a) - area(b)) > 1e-6 * max(1.0, area(a)):
        return False
    return (all(min(math.dist(p, q) for q in b) <= 1e-5 for p in a)
            and all(min(math.dist(p, q) for q in a) <= 1e-5 for p in b))


# --------------------------------------------------------------------------- #
# forward map and rebuild
# --------------------------------------------------------------------------- #
def frame(level):
    u, v = g._reference_axes(level)
    plot = [g.coordinate(level, i) for i in range(4)]
    pu = [p[0] * u[0] + p[1] * u[1] for p in plot]
    pv = [p[0] * v[0] + p[1] * v[1] for p in plot]
    return u, v, plot, (min(pu), max(pu), min(pv), max(pv))


def forward(level):
    """{node id: (axis, t, left_is_low)} for every cut, or a SKEW marker."""
    u, v, _, box = frame(level)
    cuts, skew = {}, []

    def walk(n, rect):
        if not n.divided:
            return
        a, b = g.coord_a(n), g.coord_b(n)
        d = (b[0] - a[0], b[1] - a[1])
        L = math.hypot(*d) or 1.0
        # a cut ALONG u holds v constant, and splits the rectangle in v
        along_u = abs(d[0] * v[0] + d[1] * v[1]) / L <= AXIAL_TOL
        along_v = abs(d[0] * u[0] + d[1] * u[1]) / L <= AXIAL_TOL
        if not (along_u or along_v):
            skew.append(n.id or "root")
            return
        k = 1 if along_u else 0                     # coordinate the cut fixes
        ax = v if along_u else u
        s = a[0] * ax[0] + a[1] * ax[1]
        lo, hi = (rect[2], rect[3]) if k else (rect[0], rect[1])
        t = (s - lo) / (hi - lo)
        c0 = g.coordinate(n, 0)
        left_low = (c0[0] * ax[0] + c0[1] * ax[1]) < s
        cuts[n.id] = (k, t, left_low)
        low = list(rect)
        high = list(rect)
        if k:
            low[3] = high[2] = s
        else:
            low[1] = high[0] = s
        walk(n.left, low if left_low else high)
        walk(n.right, high if left_low else low)

    walk(level, list(box))
    return cuts, skew


def rebuild(level, cuts, free=False):
    """Leaf polygons from the cut table alone: split the box, clip to the plot.

    `free=False` reproduces today's geometry. `free=True` is the pivot's crop:
    the same positions, but nothing stops a cell falling partly or wholly
    outside the plot."""
    u, v, plot, box = frame(level)
    out = {}

    def walk(n, rect):
        if not n.divided:
            out[n.id] = dedupe(clip(plot, *rect, u, v))
            return
        k, t, left_low = cuts[n.id]
        lo, hi = (rect[2], rect[3]) if k else (rect[0], rect[1])
        s = lo + t * (hi - lo)
        low, high = list(rect), list(rect)
        if k:
            low[3] = high[2] = s
        else:
            low[1] = high[0] = s
        walk(n.left, low if left_low else high)
        walk(n.right, high if left_low else low)

    walk(level, list(box))
    return out


def translate(paths, sabotage=None) -> int:
    """`sabotage` is the negative control: "nudge" moves one cut per level by
    1e-4 of its range, "flip" swaps one cut's sides. Either MUST be caught."""
    tot = collections.Counter()
    for p in paths:
        root = dom.load(str(p))
        dom.link(root)
        g.clear_cache()
        row = collections.Counter()
        for level in dom.levels(root):
            cuts, skew = forward(level)
            row["skew cuts"] += len(skew)
            if skew:
                continue
            if sabotage and cuts:
                key = sorted(cuts)[len(cuts) // 2]
                k, t, low = cuts[key]
                cuts[key] = (k, t + 1e-4, low) if sabotage == "nudge" else (k, t, not low)
            rebuilt = rebuild(level, cuts)
            for leaf in level.leaves():
                truth = dedupe([g.coordinate(leaf, i) for i in range(4)])
                row["cells"] += 1
                row["identical" if same_polygon(rebuilt[leaf.id], truth)
                    else "DIFFERENT"] += 1
        tot.update(row)
        if row["DIFFERENT"] or row["skew cuts"]:
            print(f"  {p.parent.name}/{p.name}: {dict(row)}")
    print(f"\n{len(paths)} artefacts, {tot['cells']} cells: {tot['identical']} rebuilt "
          f"identically, {tot['DIFFERENT']} different; {tot['skew cuts']} skew cut(s)")
    return 0 if tot["DIFFERENT"] == 0 and tot["skew cuts"] == 0 else 1


def shape_class(poly, u, v, sliver=1.0) -> str:
    """empty / triangle / quad / pentagon / 6+gon, with 'sliver' for a cell whose
    narrow extent along the frame axes is under `sliver` metres."""
    if len(poly) < 3 or area(poly) < 1e-6:
        return "empty"
    pu = [p[0] * u[0] + p[1] * u[1] for p in poly]
    pv = [p[0] * v[0] + p[1] * v[1] for p in poly]
    if min(max(pu) - min(pu), max(pv) - min(pv)) < sliver:
        return "sliver"
    return {3: "triangle", 4: "quad", 5: "pentagon"}.get(len(poly), "6+gon")


def crop_census(paths, draws: int, seed: int) -> int:
    import random
    rng = random.Random(seed)
    regimes = {"uniform": lambda t: rng.uniform(0.02, 0.98),
               "nudge 0.05": lambda t: min(0.98, max(0.02, t + rng.uniform(-0.05, 0.05)))}
    for regime, draw in regimes.items():
        tally = collections.Counter()
        per_prog = collections.defaultdict(collections.Counter)
        for p in paths:
            root = dom.load(str(p))
            dom.link(root)
            g.clear_cache()
            for level in dom.levels(root):
                cuts, skew = forward(level)
                if skew:
                    continue
                u, v, _, _ = frame(level)
                for _ in range(draws):
                    free = {k: (ax, draw(t), low) for k, (ax, t, low) in cuts.items()}
                    for poly in rebuild(level, free).values():
                        c = shape_class(poly, u, v)
                        tally[c] += 1
                        per_prog[p.parent.name][c] += 1
        n = sum(tally.values())
        order = ("quad", "pentagon", "triangle", "6+gon", "sliver", "empty")
        print(f"\n{regime}: {n} cells over {draws} draws per storey of {len(paths)} artefacts")
        print("  ALL            " + "  ".join(f"{c} {100 * tally[c] / n:5.1f}%" for c in order))
        for prog, t in sorted(per_prog.items()):
            m = sum(t.values())
            print(f"  {prog:15}" + "  ".join(f"{c} {100 * t[c] / m:5.1f}%" for c in order))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--translate", action="store_true")
    ap.add_argument("--crop-census", action="store_true")
    ap.add_argument("--draws", type=int, default=20)
    ap.add_argument("--corpus", default=CORPUS)
    ap.add_argument("--self-test", choices=("nudge", "flip"),
                    help="negative control for --translate: sabotage one cut per "
                         "level; the run must then report DIFFERENT cells")
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--include-e4r", action="store_true",
                    help="also the 72 programme-house e4r A/B artefacts")
    args = ap.parse_args(argv)
    g.ORTHOGONAL_DIVISION = True
    paths = [p for name in (args.programme or PROGRAMMES)
             for p in sorted((REPO / "examples" / name).glob(args.corpus))]
    if args.include_e4r:
        paths += sorted((REPO / "experiments" / "results" / "e4r").glob("e4r-arm*.dom"))
    if args.translate:
        rc = translate(paths, args.self_test)
        if args.self_test:
            print("self-test: control " + ("fired" if rc else "DID NOT FIRE"))
            return 0 if rc else 1
        return rc
    if args.crop_census:
        return crop_census(paths, args.draws, 0)
    ap.error("choose --translate or --crop-census")


if __name__ == "__main__":
    raise SystemExit(main())

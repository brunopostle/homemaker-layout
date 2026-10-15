"""`homemaker-py-2g7.13.1`: the "wings of light" catalogue -- every basic parti
of a single-storey building, found by enumeration.

The owner's proposal (2026-10-15): the plans that work -- L, C/Z, E, F, O (one
court), 8 (two courts), b (a court and a wing) ... -- are few, each comes in
several slicing trees that draw the same outline but offer different
possibilities (a C as one long wing with the rest subdivided, or two long wings
and a link), and the right one depends on the scale of the plot. Find them with
a minimal programme -- inside and outside only -- at a ladder of plot sizes,
and use them to seed the search.

**The rule is the scorer's own, and it is scale-free.** `fitness.py`
cannot score a minimal programme whole (with one usage it still asks for a
stair, circulation and access), but its daylight test is one line: a cell
fails crinkliness when its floor area exceeds 1.62 x lit wall length x storey
height, a lit wall being one on an outdoor cell or an open plot side (a
private or party side gives none). That is A / (L h), unchanged when plan and
height scale together -- an L for a 12 m plot at 3 m storeys is the L for a
24 m plot at 6 m (owner, 2026-10-15) -- so lengths here are in storey heights
and the catalogue is enumerated ONCE. It also survives subdivision: cutting a
cell lit on two opposite walls, either way, gives cells at the parent's ratio,
so a plan whose wings pass leaves rooms that can pass -- but only a WING: a
fat cell lit round its edge passes A / (L h) whole and buries the rooms cut
from its middle. So the test is the scorer's number applied pointwise:
every built point within 1.62 h of a lit wall of its own cell. That implies
the area rule, and it is what guarantees the cell divides into single-aspect
rooms 1.62 h deep at most, each of which passes.

Beyond daylight, only what the scorer would also refuse: a built cell under
``b_min`` wide, an outdoor cell under ``o_min`` (width_outside, 2.3 m), a
building in two pieces. A tree's CAPACITY on a plot is the largest built
fraction at which all of that holds; a project wants the trees whose capacity
reaches the cover its ground floor needs, on a plot of its own P / h. That is
the filter -- nothing here ranks one parti above another (§39.144 tried, and
it took a ruling nobody had made).

An earlier version of this tool scored a daylight model of its own (light
depth, court width, enclosure, envelope); §39.144 records what it showed.

**The trees.** A plan is an n-ary slicing tree: a node cuts its rectangle
into k >= 2 strips across one axis, children alternate axis (so a chain of
parallel cuts is ONE node -- (A|B)|C and A|(B|C) are the same walls and are
listed once), leaves are B (built) or O (outside). Two rules make a tree
minimal without merging different trees that draw one outline (the owner's
point): adjacent sibling leaves differ in label, and every cut separates some
B from some O. Trees are canonical under the square's eight symmetries; on a
plot each is evaluated in every orientation the plot distinguishes (two on an
open rectangle, eight once its sides differ), and reported as the best.

**The ratios** live on a grid of ``res`` storey heights: each node's strips
are whole cells summing to its span, hill-climbed from several starts to the
largest feasible cover.

    python experiments/wings_catalogue.py --leaves 6 --plots 4x4 8x8 12x8
    ... --sides open,party,open,party   (south, east, north, west)
"""

from __future__ import annotations

import argparse
import functools
import itertools
import sys
from dataclasses import dataclass

import numpy as np

# ---------------------------------------------------------------- trees ----
# A tree is "B", "O", or (axis, (child, ...)) with axis "V" (cuts across x:
# strips side by side, left to right) or "H" (strips bottom to top).


def compositions(n: int, k: int):
    """Ordered ways to write n as k positive parts."""
    if k == 1:
        yield (n,)
        return
    for first in range(1, n - k + 2):
        for rest in compositions(n - first, k - 1):
            yield (first,) + rest


@functools.lru_cache(maxsize=None)
def shapes(n: int, axis: str | None) -> tuple:
    """Unlabelled n-ary slicing trees with n leaves whose root does not cut on
    ``axis`` (None: either). A leaf is ".". """
    out = [] if n > 1 else ["."]
    if n == 1:
        return tuple(out)
    other = {"V": "H", "H": "V"}
    for ax in ("V", "H"):
        if ax == axis:
            continue
        for k in range(2, n + 1):
            for parts in compositions(n, k):
                for kids in itertools.product(*(shapes(p, ax) for p in parts)):
                    out.append((ax, kids))
    del other
    return tuple(out)


def labellings(t):
    if t == ".":
        yield "B"
        yield "O"
        return
    ax, kids = t
    for labs in itertools.product(*(list(labellings(c)) for c in kids)):
        yield (ax, labs)


def labels(t) -> set:
    if isinstance(t, str):
        return {t}
    return set().union(*(labels(c) for c in t[1]))


def minimal(t) -> bool:
    if isinstance(t, str):
        return True
    _ax, kids = t
    if labels(t) != {"B", "O"}:
        return False
    for a, b in zip(kids, kids[1:]):
        if isinstance(a, str) and a == b:
            return False
    return all(minimal(c) for c in kids)


def transform(t, mx: bool, my: bool, tr: bool):
    """Mirror x, mirror y, then transpose (swap axes)."""
    if isinstance(t, str):
        return t
    ax, kids = t
    kids = tuple(transform(c, mx, my, tr) for c in kids)
    if (ax == "V" and mx) or (ax == "H" and my):
        kids = kids[::-1]
    if tr:
        ax = {"V": "H", "H": "V"}[ax]
    return (ax, kids)


GROUP = [(mx, my, tr) for tr in (False, True) for mx in (False, True)
         for my in (False, True)]


def text(t) -> str:
    if isinstance(t, str):
        return t
    return t[0] + "(" + " ".join(text(c) for c in t[1]) + ")"


def canonical(t):
    return min((transform(t, *g) for g in GROUP), key=text)


def catalogue(max_leaves: int) -> list:
    seen = {}
    for n in range(2, max_leaves + 1):
        for s in shapes(n, None):
            for t in labellings(s):
                if minimal(t):
                    c = canonical(t)
                    seen.setdefault(text(c), c)
    return sorted(seen.values(), key=lambda t: (n_leaves(t), text(t)))


def n_leaves(t) -> int:
    return 1 if isinstance(t, str) else sum(n_leaves(c) for c in t[1])


def nodes(t) -> list:
    """Internal nodes in pre-order (the order sizes are listed in)."""
    if isinstance(t, str):
        return []
    out = [t]
    for c in t[1]:
        out += nodes(c)
    return out


# ------------------------------------------------------------ geometry ----
# Every length is in units of the storey height h. Crinkliness is A / (L h)
# for floor area A and lit wall length L, so a plan scaled by k with h scaled
# by k scores the same (the owner's point, 2026-10-15): the catalogue is
# enumerated once, and a project picks from it by its own P / h.

K_LIT = 1.6202   # A <= K_LIT * L * h at the fail edge (fitness.py, §38.3/§39.16)


@dataclass
class Plot:
    nx: int          # grid cells across (x)
    ny: int          # grid cells up (y)
    res: float       # storey heights a grid cell
    open: tuple      # (south, east, north, west): True if the side gives light

    @property
    def label(self):
        return (f"{self.nx * self.res:g}h x {self.ny * self.res:g}h "
                + "".join("o" if o else "p" for o in self.open))


def draw(t, sizes: dict, x0, y0, x1, y1, out: list):
    """Leaves as (label, x0, y0, x1, y1) in grid cells. ``sizes`` maps id(node)
    to its strips' widths."""
    if isinstance(t, str):
        out.append((t, x0, y0, x1, y1))
        return
    ax, kids = t
    edges = np.concatenate([[0], np.cumsum(sizes[id(t)])])
    for c, a, b in zip(kids, edges, edges[1:]):
        if ax == "V":
            draw(c, sizes, x0 + a, y0, x0 + b, y1, out)
        else:
            draw(c, sizes, x0, y0 + a, x1, y0 + b, out)


def shared(a, b) -> int:
    """Length of wall two rectangles share, in grid cells."""
    _la, ax0, ay0, ax1, ay1 = a
    _lb, bx0, by0, bx1, by1 = b
    if ax1 == bx0 or bx1 == ax0:
        return max(0, min(ay1, by1) - max(ay0, by0))
    if ay1 == by0 or by1 == ay0:
        return max(0, min(ax1, bx1) - max(ax0, bx0))
    return 0


def check(leaves, plot: Plot, b_min: float, o_min: float):
    """(built fraction, violation) of a plan. Violation is 0 when every built
    cell passes the scorer's crinkliness edge and is at least ``b_min`` wide,
    every outdoor cell at least ``o_min`` wide, and the building is one piece;
    otherwise a positive measure of how far it is from that, in h^2."""
    s, e, n, w = plot.open
    B = [lf for lf in leaves if lf[0] == "B"]
    O = [lf for lf in leaves if lf[0] == "O"]
    r = plot.res
    bad = 0.0
    reach = max(1, int(K_LIT / r + 1e-9))  # grid cells a lit wall reaches
    for lf in B:
        _l, x0, y0, x1, y1 = lf
        # every point within K_LIT h of a lit wall of its own cell: then the
        # cell divides into rooms lit on one side and K_LIT h deep at most,
        # each of which passes -- the area rule alone lets a fat cell lit
        # round its edge pass while the rooms cut from its middle are buried
        cover = np.zeros((x1 - x0, y1 - y0), bool)
        sides = {"W": [(y0, y1)] if (x0 == 0 and w) else [],
                 "E": [(y0, y1)] if (x1 == plot.nx and e) else [],
                 "S": [(x0, x1)] if (y0 == 0 and s) else [],
                 "N": [(x0, x1)] if (y1 == plot.ny and n) else []}
        for _o, ox0, oy0, ox1, oy1 in O:
            if ox1 == x0:
                sides["W"].append((max(y0, oy0), min(y1, oy1)))
            if ox0 == x1:
                sides["E"].append((max(y0, oy0), min(y1, oy1)))
            if oy1 == y0:
                sides["S"].append((max(x0, ox0), min(x1, ox1)))
            if oy0 == y1:
                sides["N"].append((max(x0, ox0), min(x1, ox1)))
        for side, ivs in sides.items():
            for a, b in ivs:
                if b <= a:
                    continue
                if side == "W":
                    cover[:reach, a - y0:b - y0] = True
                elif side == "E":
                    cover[-reach:, a - y0:b - y0] = True
                elif side == "S":
                    cover[a - x0:b - x0, :reach] = True
                else:
                    cover[a - x0:b - x0, -reach:] = True
        bad += (~cover).sum() * r * r
        short, long_ = sorted((x1 - x0, y1 - y0))
        bad += max(0.0, b_min - short * r) * long_ * r
    for lf in O:
        _l, x0, y0, x1, y1 = lf
        short, long_ = sorted((x1 - x0, y1 - y0))
        bad += max(0.0, o_min - short * r) * long_ * r
    # one building: the built cells' adjacency graph is connected
    if len(B) > 1:
        seen, todo = {0}, [0]
        while todo:
            i = todo.pop()
            for j in range(len(B)):
                if j not in seen and shared(B[i], B[j]) > 0:
                    seen.add(j)
                    todo.append(j)
        for j in range(len(B)):
            if j not in seen:
                _l, x0, y0, x1, y1 = B[j]
                bad += (x1 - x0) * (y1 - y0) * r * r
    built = sum((x1 - x0) * (y1 - y0) for _l, x0, y0, x1, y1 in B)
    return built / (plot.nx * plot.ny), bad


def initial_sizes(t, span_x, span_y, rng) -> dict:
    sizes = {}

    def rec(t, sx, sy):
        if isinstance(t, str):
            return
        ax, kids = t
        span = sx if ax == "V" else sy
        k = len(kids)
        if span < k:
            raise ValueError("plot too small for this tree")
        wts = rng.dirichlet(np.ones(k)) * (span - k)
        parts = np.floor(wts).astype(int) + 1
        parts[np.argmax(wts - np.floor(wts))] += span - parts.sum()
        sizes[id(t)] = parts
        for c, p in zip(kids, parts):
            rec(c, p if ax == "V" else sx, sy if ax == "V" else p)
    rec(t, span_x, span_y)
    return sizes


def respan(t, sizes, sx, sy):
    """Rescale every node below to its (possibly changed) span, keeping
    proportions: called after a move changes a strip's width."""
    if isinstance(t, str):
        return
    ax, kids = t
    span = sx if ax == "V" else sy
    p = sizes[id(t)]
    if p.sum() != span:
        k = len(p)
        if span < k:
            raise ValueError("a strip is narrower than the strips inside it")
        wts = p / p.sum() * (span - k)
        q = np.floor(wts).astype(int) + 1
        q[np.argmax(wts - np.floor(wts))] += span - q.sum()
        sizes[id(t)] = p = q
    for c, wd in zip(kids, p):
        respan(c, sizes, wd if ax == "V" else sx, sy if ax == "V" else wd)


def optimise(t, plot: Plot, b_min, o_min, rng, starts=6, max_steps=600,
             coverage=None):
    """Hill-climb a tree's strip widths. Without ``coverage``: the largest
    built fraction at which every rule holds (its CAPACITY on this plot).
    With it: the feasible plan nearest that fraction. Returns (key, built
    fraction, violation, sizes) for the best start, or None if the plot is too
    small to draw the tree at all."""
    inner = nodes(t)

    def key(sizes):
        out = []
        draw(t, sizes, 0, 0, plot.nx, plot.ny, out)
        frac, bad = check(out, plot, b_min, o_min)
        aim = -abs(frac - coverage) if coverage is not None else frac
        return (-bad, aim), frac, bad

    best = None
    for _ in range(starts):
        try:
            sizes = initial_sizes(t, plot.nx, plot.ny, rng)
        except ValueError:
            return None
        cur = key(sizes)
        step = max(1, max(plot.nx, plot.ny) // 6)
        steps = 0
        while step >= 1 and steps < max_steps:
            improved = False
            moves = [(nd, i, sg) for nd in inner for i in range(len(nd[1]) - 1)
                     for sg in (step, -step)]
            for j in rng.permutation(len(moves)):
                nd, i, sg = moves[j]
                p = sizes[id(nd)]
                if p[i] + sg < 1 or p[i + 1] - sg < 1:
                    continue
                trial = {k: v.copy() for k, v in sizes.items()}
                trial[id(nd)][i] += sg
                trial[id(nd)][i + 1] -= sg
                try:
                    respan(t, trial, plot.nx, plot.ny)
                except ValueError:
                    continue
                steps += 1
                val = key(trial)
                if val[0] > cur[0]:
                    sizes, cur, improved = trial, val, True
            if not improved:
                step //= 2
        if best is None or cur[0] > best[0]:
            best = (*cur, sizes)
    return best


def orientations(plot: Plot) -> list:
    """The symmetries of the square that this plot does NOT make equivalent.

    A plan transformed by g, on plot P, scores as the plan itself on the plot
    g^-1(P). Two orientations are the same question when they pull P back to
    the same plot -- the same dimensions and the same open sides -- so an open
    square leaves one, an open rectangle two, and a plot whose sides all
    differ eight."""
    out, seen = [], set()
    for g in GROUP:
        mx, my, tr = g
        s, e, n, w = plot.open
        nx, ny = plot.nx, plot.ny
        # g^-1 = transpose first, then the mirrors (each its own inverse)
        if tr:
            s, e, n, w = w, n, e, s
            nx, ny = ny, nx
        if mx:
            e, w = w, e
        if my:
            s, n = n, s
        key = (nx, ny, s, e, n, w)
        if key not in seen:
            seen.add(key)
            out.append(g)
    return out


def ascii_plan(t, sizes, plot: Plot, width=24) -> list[str]:
    out = []
    draw(t, sizes, 0, 0, plot.nx, plot.ny, out)
    g = np.full((plot.nx, plot.ny), " ")
    for lab, x0, y0, x1, y1 in out:
        g[x0:x1, y0:y1] = "#" if lab == "B" else "."
    step = max(1, plot.nx // width)
    return ["".join(g[x, y] for x in range(0, plot.nx, step))
            for y in range(plot.ny - 1, -1, -step)]


def parse_plot(spec: str, sides: str, res: float) -> Plot:
    w, h = (float(v) for v in spec.split("x"))
    flags = tuple(s.strip() == "open" for s in sides.split(","))
    assert len(flags) == 4, "--sides wants south,east,north,west"
    return Plot(round(w / res), round(h / res), res, flags)


def stable_rng(*parts) -> np.random.Generator:
    import hashlib
    h = hashlib.sha1("|".join(map(str, parts)).encode()).digest()
    return np.random.default_rng(int.from_bytes(h[:8], "big"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leaves", type=int, default=6)
    ap.add_argument("--plots", nargs="+", default=["4x4", "6x6", "8x8", "10x10", "12x12"],
                    help="plot sizes in storey heights (8x8 is 24 m at h = 3 m)")
    ap.add_argument("--sides", default="open,open,open,open",
                    help="south,east,north,west: open or party (no light)")
    ap.add_argument("--res", type=float, default=None,
                    help="grid, in storey heights (default: 1/32 of the plot's "
                         "longer side, at least 0.25)")
    ap.add_argument("--b-min", type=float, default=1.0,
                    help="narrowest built cell, in h (3 m at h = 3 m)")
    ap.add_argument("--o-min", type=float, default=0.77,
                    help="narrowest outdoor cell, in h (width_outside 2.3 m at h = 3 m)")
    ap.add_argument("--starts", type=int, default=6)
    ap.add_argument("--top", type=int, default=8, help="outlines shown per plot")
    ap.add_argument("--width", type=int, default=16, help="ascii plan width")
    ap.add_argument("--json", default=None, help="write the catalogue here")
    ap.add_argument("--count", action="store_true",
                    help="only count the catalogue by leaf number")
    args = ap.parse_args(argv)

    cat = catalogue(args.leaves)
    by_n: dict = {}
    for t in cat:
        by_n[n_leaves(t)] = by_n.get(n_leaves(t), 0) + 1
    print("canonical minimal trees by leaves:", by_n, "total", len(cat), flush=True)
    if args.count:
        return 0

    record = {"b_min": args.b_min, "o_min": args.o_min, "k_lit": K_LIT,
              "sides": args.sides, "plots": {}}
    for spec in args.plots:
        res = args.res or max(0.25, max(float(v) for v in spec.split("x")) / 32)
        plot = parse_plot(spec, args.sides, res)
        gs = orientations(plot)
        rows = []
        for t in cat:
            best = None
            for g in gs:
                tt = transform(t, *g)
                r = optimise(tt, plot, args.b_min, args.o_min,
                             stable_rng(text(tt), spec), starts=args.starts)
                if r and r[2] == 0 and (best is None or r[1] > best[0]):
                    best = (r[1], r[3], tt, t)
            if best:
                rows.append(best)
        rows.sort(key=lambda r: (-r[0], n_leaves(r[2]), text(r[2])))
        groups: dict = {}
        for r in rows:
            plan = "\n".join(ascii_plan(r[2], r[1], plot, args.width))
            groups.setdefault(plan, []).append(r)
        record["plots"][spec] = [
            {"tree": text(c), "capacity": round(float(f), 4)} for f, _s, _tt, c in rows]
        caps = [r[0] for r in rows]
        print(f"\nplot {plot.label}: {len(rows)} of {len(cat)} trees can be built "
              f"all lit ({len(gs)} orientation(s) tried); capacity "
              f"{max(caps, default=0):.0%} best, {np.median(caps) if caps else 0:.0%} "
              f"median; {len(groups)} outlines", flush=True)
        for plan, rs in list(groups.items())[:args.top]:
            print(f"  capacity {rs[0][0]:.0%}, {len(rs)} tree(s): "
                  + ", ".join(text(r[2]) for r in rs[:3])
                  + (f" ... +{len(rs) - 3}" if len(rs) > 3 else ""))
            for line in plan.split("\n"):
                print("        " + line)
    if args.json:
        import json
        with open(args.json, "w") as fh:
            json.dump(record, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

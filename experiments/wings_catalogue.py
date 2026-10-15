"""`homemaker-py-2g7.13.1`: the "wings of light" catalogue -- every basic parti
of a single-storey building, found by enumeration.

The owner's proposal (2026-10-15): the plans that work -- L, C/Z, E, F, O (one
court), 8 (two courts), b (a court and a wing) ... -- are few, each comes in
several slicing trees that draw the same outline but offer different
possibilities (a C as one long wing with the rest subdivided, or two long wings
and a link), and the right one depends on the scale of the plot. Find them with
a minimal programme -- inside and outside only -- at a ladder of plot sizes,
and use them to seed the search.

**Why not the scorer.** `fitness.py` on a one-usage programme still demands a
stair (`staircase_min: 0` reads as 1), circulation and access: a bare L fails
all three. So this scores the one thing the parti is FOR, daylight, in terms
taken from Alexander (107 Wings of Light, 106 Positive Outdoor Space):

* a FACADE is a built edge that sees an open plot side, or looks across
  outdoor space at least ``court`` metres deep before meeting a wall (a
  building or a party wall);
* a built point is LIT if it is within ``depth`` metres of a facade of its own
  cell (cell-local, so light does not jump a slot to the next wing);
* a built cell narrower than ``wing_min`` is a sliver and lights nothing;
* only one connected building counts; any other piece is unlit.

* outdoor space is USABLE where a ``court`` x ``court`` square of it fits
  (a morphological opening); the rest is a slot or a sliver, and wasted.

score = lit - unlit - wasted outdoor, in m2, less twice the miss on
``coverage`` (the built fraction of the plot) when one is asked for, less
``envelope`` m2 a metre of external wall, plus ``enclosure`` m2 a metre of
usable outdoor edge held by building or party wall. Daylight and coverage
alone do NOT rank plans: at half cover, 23 outlines on an open 18 m square and
36 on a 24 m one are all lit with nothing wasted. The last two terms are the
candidate tie-breakers, economy and positive outdoor space, both off unless
asked for. Without it the parti is the
densest building that is all lit, and on a plot under two light depths across
that is simply the whole plot; a coverage is what makes a garden worth keeping.

The answer is not one tree but the PORTFOLIO within ``tol`` m2 of the best,
grouped by the outline they draw: different trees drawing one outline are
listed under it, since they are different seeds.

**The trees.** A plan is an n-ary slicing tree: a node cuts its rectangle
into k >= 2 strips across one axis, children alternate axis (so a chain of
parallel cuts is ONE node -- (A|B)|C and A|(B|C) are the same walls and are
listed once), leaves are B (built) or O (outside). Two rules make a tree
minimal without merging different trees that draw one outline (the owner's
point): adjacent sibling leaves differ in label, and every cut separates some
B from some O. Trees are canonical under the square's eight symmetries; on a
plot each is evaluated in every orientation the plot distinguishes (two on an
open rectangle, eight once its sides differ), and reported as the best.

**The ratios** live on a grid of ``res`` metres: each node's strips are whole
cells summing to its span, improved by hill-climbing (move one cell between
neighbouring strips) from several starts.

    python experiments/wings_catalogue.py --leaves 6 --plots 12x12 24x24 36x24
    ... --sides open,open,party,party   (south, east, north, west)
"""

from __future__ import annotations

import argparse
import functools
import itertools
import sys
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

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

@dataclass
class Plot:
    nx: int          # cells across (x)
    ny: int          # cells up (y)
    res: float       # metres a cell
    open: tuple      # (south, east, north, west): True if light comes in

    @property
    def label(self):
        return (f"{self.nx * self.res:g}x{self.ny * self.res:g} "
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


def runs(o: np.ndarray, axis: int, reverse: bool) -> tuple[np.ndarray, np.ndarray]:
    """For every cell, how many O cells lie beyond it in the direction, and
    whether that run of O reaches the plot edge."""
    a = np.moveaxis(o, axis, 0)
    if reverse:
        a = a[::-1]
    n = np.zeros(a.shape, int)
    edge = np.zeros(a.shape, bool)
    cnt = np.zeros(a.shape[1:], int)
    reach = np.ones(a.shape[1:], bool)
    for i in range(a.shape[0] - 1, -1, -1):
        n[i] = cnt
        edge[i] = reach
        cnt = np.where(a[i], cnt + 1, 0)
        reach = np.where(a[i], reach, False)
    if reverse:
        n, edge = n[::-1], edge[::-1]
    return np.moveaxis(n, 0, axis), np.moveaxis(edge, 0, axis)


def edges_between(a: np.ndarray, b: np.ndarray, plot: Plot, b_outside: bool) -> int:
    """Grid edges between a cell of ``a`` and a cell of ``b``; with
    ``b_outside``, an ``a`` cell on a plot side counts too, once per side that
    is open (``b_outside`` True) -- or party (False)."""
    n = (a[1:, :] & b[:-1, :]).sum() + (a[:-1, :] & b[1:, :]).sum()
    n += (a[:, 1:] & b[:, :-1]).sum() + (a[:, :-1] & b[:, 1:]).sum()
    s, e, nn, w = plot.open
    for side_open, line in ((s, a[:, 0]), (e, a[-1, :]), (nn, a[:, -1]), (w, a[0, :])):
        if side_open == b_outside:
            n += line.sum()
    return int(n)


def score(leaves, plot: Plot, depth: float, court: float, wing_min: float,
          coverage: float | None = None, envelope: float = 0.0,
          enclosure: float = 0.0):
    """(score, lit m2, built m2, wasted outdoor m2) of a plan drawn as ``leaves``."""
    built = np.zeros((plot.nx, plot.ny), bool)
    for lab, x0, y0, x1, y1 in leaves:
        if lab == "B":
            built[x0:x1, y0:y1] = True
    o = ~built
    court_n = court / plot.res
    # facing[d]: the cell's neighbour in direction d is light, d = +x, +y, -x, -y
    # plot sides: +x east (1), +y north (2), -x west (3), -y south (0)
    side_of = {(0, False): 1, (1, False): 2, (0, True): 3, (1, True): 0}
    lightfrom = {}
    for axis in (0, 1):
        for rev in (False, True):
            n, edge = runs(o, axis, rev)
            ok = np.where(edge, plot.open[side_of[axis, rev]] | (n >= court_n),
                          n >= court_n)
            lightfrom[axis, rev] = ok
    lit = np.zeros_like(built)
    depth_n = depth / plot.res
    wing_n = wing_min / plot.res
    for lab, x0, y0, x1, y1 in leaves:
        if lab != "B" or min(x1 - x0, y1 - y0) < wing_n:
            continue
        src = np.zeros((x1 - x0, y1 - y0), bool)
        src[-1, :] |= lightfrom[0, False][x1 - 1, y0:y1]
        src[0, :] |= lightfrom[0, True][x0, y0:y1]
        src[:, -1] |= lightfrom[1, False][x0:x1, y1 - 1]
        src[:, 0] |= lightfrom[1, True][x0:x1, y0]
        if not src.any():
            continue
        # distance from a facade cell's outer face: a facade cell is half a
        # cell from its wall, so the edt (centre to centre) plus 0.5
        d = ndimage.distance_transform_edt(~src) + 0.5
        lit[x0:x1, y0:y1] = d <= depth_n
    comp, k = ndimage.label(built)
    if k > 1:
        big = np.argmax(np.bincount(comp.ravel())[1:]) + 1
        lit &= comp == big
    a = plot.res ** 2
    lit_m2 = lit.sum() * a
    built_m2 = built.sum() * a
    # outdoor space is usable where a court x court square of it fits
    k = max(1, round(court_n))
    usable = ndimage.binary_opening(o, structure=np.ones((k, k), bool))
    waste_m2 = (o & ~usable).sum() * a
    val = lit_m2 - (built_m2 - lit_m2) - waste_m2
    if envelope:
        # external wall: built against outdoor space or an open plot side
        val -= envelope * edges_between(built, o, plot, True) * plot.res
    if enclosure:
        # usable outdoor space held by the building or by a party wall
        val += enclosure * edges_between(usable, built, plot, False) * plot.res
    if coverage is not None:
        # weight 2: at 1, a m2 built past the target is lit and costs nothing
        val -= 2 * abs(built_m2 - coverage * plot.nx * plot.ny * a)
    return val, lit_m2, built_m2, waste_m2


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
        w = rng.dirichlet(np.ones(k)) * (span - k)
        parts = np.floor(w).astype(int) + 1
        parts[np.argmax(w - np.floor(w))] += span - parts.sum()
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
        w = p / p.sum() * (span - k)
        q = np.floor(w).astype(int) + 1
        q[np.argmax(w - np.floor(w))] += span - q.sum()
        sizes[id(t)] = p = q
    for c, w in zip(kids, p):
        respan(c, sizes, w if ax == "V" else sx, sy if ax == "V" else w)


def optimise(t, plot: Plot, depth, court, wing_min, rng, starts=4, max_steps=400,
             coverage=None, envelope=0.0, enclosure=0.0):
    """Best (score, lit, built, waste, sizes) for tree ``t`` on ``plot``."""
    best = None
    inner = nodes(t)

    def evaluate(sizes):
        out = []
        draw(t, sizes, 0, 0, plot.nx, plot.ny, out)
        return score(out, plot, depth, court, wing_min, coverage, envelope, enclosure)

    for _ in range(starts):
        try:
            sizes = initial_sizes(t, plot.nx, plot.ny, rng)
        except ValueError:
            return None
        cur = evaluate(sizes)
        step = max(1, max(plot.nx, plot.ny) // 8)
        steps = 0
        while step >= 1 and steps < max_steps:
            improved = False
            moves = [(n, i, s) for n in inner for i in range(len(n[1]) - 1)
                     for s in (step, -step)]
            for j in rng.permutation(len(moves)):
                n, i, s = moves[j]
                p = sizes[id(n)]
                if p[i] + s < 1 or p[i + 1] - s < 1:
                    continue
                trial = {k: v.copy() for k, v in sizes.items()}
                trial[id(n)][i] += s
                trial[id(n)][i + 1] -= s
                respan(t, trial, plot.nx, plot.ny)
                steps += 1
                val = evaluate(trial)
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
    rows = []
    for y in range(plot.ny - 1, -1, -step):
        rows.append("".join(g[x, y] for x in range(0, plot.nx, step)))
    return rows


def parse_plot(spec: str, sides: str, res: float) -> Plot:
    w, h = (float(v) for v in spec.split("x"))
    flags = tuple(s.strip() == "open" for s in sides.split(","))
    assert len(flags) == 4, "--sides wants south,east,north,west"
    return Plot(round(w / res), round(h / res), res, flags)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--leaves", type=int, default=6)
    ap.add_argument("--plots", nargs="+", default=["12x12", "18x18", "24x24", "30x30"])
    ap.add_argument("--sides", default="open,open,open,open",
                    help="south,east,north,west: open or party")
    ap.add_argument("--res", type=float, default=1.0)
    ap.add_argument("--depth", type=float, default=6.0,
                    help="metres a facade lights (a two-sided wing is twice this)")
    ap.add_argument("--court", type=float, default=6.0,
                    help="outdoor depth a facade needs to see to count as lit")
    ap.add_argument("--wing-min", type=float, default=4.0)
    ap.add_argument("--starts", type=int, default=4)
    ap.add_argument("--coverage", type=float, default=None,
                    help="built fraction of the plot to aim at (default: none)")
    ap.add_argument("--envelope", type=float, default=0.0,
                    help="m2 charged per metre of external wall (party walls free)")
    ap.add_argument("--enclosure", type=float, default=0.0,
                    help="m2 credited per metre of usable outdoor edge held by "
                         "building or party wall (Alexander 106)")
    ap.add_argument("--tol", type=float, default=5.0,
                    help="m2 below the best still reported")
    ap.add_argument("--width", type=int, default=24, help="ascii plan width")
    ap.add_argument("--top", type=int, default=8, help="outlines shown")
    ap.add_argument("--count", action="store_true",
                    help="only count the catalogue by leaf number")
    args = ap.parse_args(argv)

    cat = catalogue(args.leaves)
    by_n = {}
    for t in cat:
        by_n[n_leaves(t)] = by_n.get(n_leaves(t), 0) + 1
    print("canonical minimal trees by leaves:", by_n, "total", len(cat), flush=True)
    if args.count:
        return 0

    for spec in args.plots:
        plot = parse_plot(spec, args.sides, args.res)
        gs = orientations(plot)
        rows = []
        for t in cat:
            best = None
            for g in gs:
                tt = transform(t, *g)
                rng = np.random.default_rng(
                    int.from_bytes(text(tt).encode()[-8:].rjust(8, b"_"), "big") % 2**32)
                r = optimise(tt, plot, args.depth, args.court, args.wing_min, rng,
                             starts=args.starts, coverage=args.coverage,
                             envelope=args.envelope, enclosure=args.enclosure)
                if r and (best is None or r[0] > best[0]):
                    best = (*r, tt)
            if best:
                rows.append(best)
        rows.sort(key=lambda r: (-r[0], n_leaves(r[-1]), text(r[-1])))
        top = rows[0][0]
        keep = [r for r in rows if r[0] >= top - args.tol]
        groups: dict = {}
        for r in keep:
            plan = "\n".join(ascii_plan(r[-1], r[-2], plot, args.width))
            groups.setdefault(plan, []).append(r)
        print(f"\nplot {plot.label}, coverage {args.coverage}: {len(rows)} trees x "
              f"{len(gs)} orientation(s); {len(keep)} within {args.tol:g} m2 of "
              f"the best, drawing {len(groups)} outline(s)", flush=True)
        for plan, rs in list(groups.items())[:args.top]:
            sc, lit, built, waste = rs[0][:4]
            print(f"  score {sc:6.0f}: lit {lit:.0f} of {built:.0f} m2 built, "
                  f"{waste:.0f} m2 outdoor wasted; {len(rs)} tree(s):")
            for r in rs[:6]:
                print(f"      {n_leaves(r[-1])} leaves  {text(r[-1])}")
            if len(rs) > 6:
                print(f"      ... and {len(rs) - 6} more")
            for line in plan.split("\n"):
                print("        " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

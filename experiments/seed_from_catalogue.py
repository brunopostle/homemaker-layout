"""`homemaker-py-2g7.13.1`: seed a project from the wings-of-light catalogue.

The owner (2026-10-15): "find all the likely seed layouts that are generically
possible and feed them into every project (maybe with some filtering)".
`wings_catalogue.py` enumerates the parti once, in storey heights; this takes
a project and

1. reads its plot as a rectangle in storey heights -- the frame's two side
   lengths over the storey height -- with a side giving light unless the
   brief calls it ``private`` or ``fortified`` (what `area_outside` reads);
2. asks the cover its ground floor needs at each storey count the brief
   allows: the programme's room area, plus a circulation share, over storeys
   and plot;
3. sizes every catalogue tree, in every orientation the plot distinguishes,
   to the feasible plan nearest that cover (every built point within 1.62 h of
   a lit wall, the scorer's own number) -- the FILTER -- keeping one tree per
   outline drawn;
4. draws each survivor on the project's real plot as a quad tree (a run of
   parallel strips becomes a chain of cuts), stacks the storeys with the
   courts open to the sky, fills the built cells with the programme's rooms by
   the constructor's own growth, assignment and sizing (as
   `diag_2g7131_footprint.py` refilled hand2a's wings), and tunes it briefly;
5. reports them ranked, and with ``--write`` saves the best as
   ``wings-<rank>.dom`` for `homemaker-evolve` to warm-start from.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/seed_from_catalogue.py \\
        --programme harbor-house --leaves 6 --max-seeds 40 --budget 200 --write 3
"""

from __future__ import annotations

import argparse
import copy
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

import wings_catalogue as wc  # noqa: E402
from diag_2g713_seed_storeys import constructor_kwargs, family, rng_for  # noqa: E402
from diag_2g7131_footprint import grow  # noqa: E402

from homemaker_layout import dom, genome, geometry, innerloop, operators, programme  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402
from homemaker_layout.fitness_cmd import load_config  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DARK = {"private", "fortified"}


def plot_of(init: dom.Node, res_cells: int = 32):
    """The plot as a catalogue `Plot`: corner 0 -> 1 is x (side a, "south"),
    1 -> 2 is y (side b, "east"); opposite sides averaged."""
    c = [np.array(geometry.coordinate(init, i)) for i in range(4)]
    w = (np.linalg.norm(c[1] - c[0]) + np.linalg.norm(c[2] - c[3])) / 2
    d = (np.linalg.norm(c[2] - c[1]) + np.linalg.norm(c[3] - c[0])) / 2
    h = float(init.height or 3.0)
    per = init.perimeter or {}
    lit = tuple((str(per.get(k) or "").lower() not in DARK) for k in "abcd")
    res = max(0.25, max(w, d) / h / res_cells)
    return wc.Plot(round(w / h / res), round(d / h / res), res, lit), (w, d, h)


def frame_axes(init: dom.Node):
    c = [np.array(geometry.coordinate(init, i)) for i in range(4)]
    x = c[1] - c[0]
    x /= np.linalg.norm(x)
    return x, np.array([-x[1], x[0]])


def to_quad(t, sizes, lvl: dom.Node, root: dom.Node, axes) -> None:
    """Draw catalogue tree ``t`` (with strip widths ``sizes``) into the
    undivided storey node ``lvl``. A k-strip node becomes a chain: the first
    strip cut off, the rest cut again on the same axis. Each cut's rotation is
    whichever of the four puts the first strip on the low side of the axis."""
    if isinstance(t, str):
        lvl.type = "O" if t == "O" else "C"
        return
    ax, kids = t
    widths = list(sizes[id(t)])
    axis = axes[0] if ax == "V" else axes[1]
    node = lvl
    for i, kid in enumerate(kids[:-1]):
        f = float(widths[i] / sum(widths[i:]))  # numpy floats do not dump to YAML
        node.type = None
        node.division = [f, f]
        node.left, node.right = dom.Node(type="C"), dom.Node(type="C")
        best = None
        for rot in range(4):
            node.rotation = rot
            dom.link(root)
            geometry.clear_cache()
            gap = (np.dot(geometry.centroid(node.right), axis)
                   - np.dot(geometry.centroid(node.left), axis))
            if best is None or gap > best[0]:
                best = (gap, rot)
        node.rotation = best[1]
        dom.link(root)
        geometry.clear_cache()
        to_quad(kid, sizes, node.left, root, axes)
        node = node.right
    to_quad(kids[-1], sizes, node, root, axes)


def buckets(reqs, n_storeys: int, rng) -> list[list[str]]:
    """The constructor's partition of rooms over storeys (level-bound rooms to
    their storey, the rest round-robin over a shuffled order)."""
    prog = operators._programme_codes(reqs)
    out: list[list[str]] = [[] for _ in range(n_storeys)]
    free = []
    for code, req in prog.items():
        for _ in range(req.count):
            if req.level is not None and req.level < n_storeys:
                out[req.level].append(code)
            else:
                free.append(code)
    free = [free[i] for i in rng.permutation(len(free))]
    for i, code in enumerate(free):
        out[i % n_storeys].append(code)
    return out


def build_seed(init, t, sizes, reqs, n_storeys, rng, kw) -> dom.Node:
    root = copy.deepcopy(init)
    root.above = None
    dom.link(root)
    to_quad(t, sizes, root, root, frame_axes(init))
    dom.link(root)
    while len(dom.levels(root)) < n_storeys:
        top = dom.levels(root)[-1]
        dup = genome._copy_storey(top)
        dup.height = top.height
        top.above = dup
    dom.link(root)
    for lvl, rooms in zip(dom.levels(root), buckets(reqs, n_storeys, rng)):
        wings = [lf for lf in lvl.leaves() if lf.type != "O"]
        n_circ = max(1, -(-len(rooms) // kw["circ_divisor"]))
        # +1: the assignment always places one O in scope; it goes back to C
        scope = grow(lvl, wings, len(rooms) + n_circ + 1, rng)
        operators._assign_adjacency_aware(
            lvl, rooms, reqs, rng, interior_outside=True, n_outside=1,
            scope=set(scope))
        for lf in scope:
            if lf.type == "O":
                lf.type = "C"
        dom.link(root)
        for w in wings:
            if w.divided:
                operators._size_divisions_from_targets(w, reqs)
        dom.link(root)
    return operators._finalise(root)


def needed_cover(reqs, conf, plot_m2: float, circ_share: float) -> dict:
    prog = operators._programme_codes(reqs)
    area = sum(r.size * r.count for r in prog.values() if r.size) * (1 + circ_share)
    lo = int(conf.get("storey_minimum") or 1)
    hi = int(conf.get("storey_limit") or lo)
    return {n: area / n / plot_m2 for n in range(lo, hi + 1)}


def parse_tree(s: str):
    """The inverse of `wings_catalogue.text`: "H(B V(B O))" -> a tree."""
    pos = 0

    def node():
        nonlocal pos
        c = s[pos]
        pos += 1
        if c in "BO":
            return c
        assert s[pos] == "("
        pos += 1
        kids = []
        while s[pos] != ")":
            if s[pos] == " ":
                pos += 1
                continue
            kids.append(node())
        pos += 1
        return (c, tuple(kids))
    return node()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", default="harbor-house")
    ap.add_argument("--leaves", type=int, default=6)
    ap.add_argument("--storeys", type=int, nargs="*", default=None,
                    help="storey counts to seed (default: all the brief allows)")
    ap.add_argument("--circ-share", type=float, default=0.25,
                    help="circulation added to the room area when asking the cover")
    ap.add_argument("--tol", type=float, default=0.05,
                    help="how far from the needed cover a plan may land")
    ap.add_argument("--b-min", type=float, default=1.0)
    ap.add_argument("--o-min", type=float, default=0.77)
    ap.add_argument("--max-seeds", type=int, default=40,
                    help="filtered plans built and tuned, fewest leaves first")
    ap.add_argument("--budget", type=int, default=200)
    ap.add_argument("--starts", type=int, default=4,
                    help="hill-climb starts per tree and orientation")
    ap.add_argument("--write", type=int, default=0, help="save the best N seeds")
    ap.add_argument("--only", nargs="+", default=None, metavar="N:TREE",
                    help="build just these plans, as printed (e.g. '3:H(B V(B O))'), "
                         "skipping the enumeration; sizing and building are "
                         "deterministic, so this reproduces a ranked run's seeds")
    args = ap.parse_args(argv)
    if not geometry.ORTHOGONAL_DIVISION:
        print("set HOMEMAKER_ORTHOGONAL_DIVISION=1", file=sys.stderr)
        return 2

    prog = REPO / "examples" / args.programme
    conf, cost = load_config(prog)
    fit = Fitness(conf, cost)
    reqs = programme.load_programme_dir(str(prog))
    init = dom.load(str(prog / "init.dom"))
    plot, (w, d, h) = plot_of(init)
    covers = needed_cover(reqs, conf, w * d, args.circ_share)
    if args.storeys:
        covers = {n: covers.get(n, list(covers.values())[0] * min(covers) / n)
                  for n in args.storeys}
    kw = constructor_kwargs()
    print(f"{args.programme}: plot {w:.1f} x {d:.1f} m, storey {h:g} m -> "
          f"{plot.label}; cover needed " +
          ", ".join(f"{n} storeys {c:.0%}" for n, c in covers.items()), flush=True)

    plans = []
    if args.only:
        for spec in args.only:
            n_s, txt = spec.split(":", 1)
            n, tt = int(n_s), parse_tree(txt)
            assert wc.text(tt) == txt, (txt, wc.text(tt))
            r = wc.optimise(tt, plot, args.b_min, args.o_min,
                            wc.stable_rng(txt, args.programme, n),
                            starts=args.starts, coverage=covers[n])
            plans.append((n, wc.n_leaves(tt), txt, tt, r[3], r[1],
                          "\n".join(wc.ascii_plan(tt, r[3], plot, 16))))
    cat = [] if args.only else wc.catalogue(args.leaves)
    gs = wc.orientations(plot)
    for n, cover in ({} if args.only else covers).items():
        if cover > 0.98:
            continue
        seen = set()
        for t in cat:
            for g in gs:
                tt = wc.transform(t, *g)
                r = wc.optimise(tt, plot, args.b_min, args.o_min,
                                wc.stable_rng(wc.text(tt), args.programme, n),
                                starts=args.starts, coverage=cover)
                if not r or r[2] > 0 or abs(r[1] - cover) > args.tol:
                    continue
                outline = "\n".join(wc.ascii_plan(tt, r[3], plot, 16))
                if outline in seen:
                    continue
                seen.add(outline)
                plans.append((n, wc.n_leaves(tt), wc.text(tt), tt, r[3], r[1], outline))
        print(f"  {n} storeys: {len(seen)} outlines pass the filter", flush=True)
    if not args.only:
        plans.sort(key=lambda p: (p[1], p[0], p[2]))
        plans = plans[:args.max_seeds]

    rows = []
    for i, (n, nl, txt, tt, sizes, frac, outline) in enumerate(plans):
        rng = rng_for(args.programme, txt, n)
        root = build_seed(init, tt, sizes, reqs, n, rng, kw)
        geometry.clear_cache()
        raw = len(fit.score_with_fails(root)[1])
        res = innerloop.optimise(root, str(prog), budget=args.budget, method="nm")
        geometry.clear_cache()
        _s, fails = fit.score_with_fails(root)
        rows.append((len(fails), res.fitness, n, txt, outline, root, list(fails), raw, frac))
        print(f"  [{i + 1}/{len(plans)}] {n} storeys, {txt}: cover {frac:.0%}, "
              f"{raw} fails raw -> {len(fails)} tuned", flush=True)

    rows.sort(key=lambda r: (r[0], -r[1]))
    print(f"\n{len(rows)} seeds, {args.budget} inner-loop evaluations each; "
          f"tuned fails median {statistics.median(r[0] for r in rows) if rows else 0}")
    for k, (nf, sc, n, txt, outline, root, fails, raw, frac) in enumerate(rows[:8]):
        fam = Counter(family(f) for f in fails)
        print(f"  #{k + 1}: {nf} fails, score {sc:.3g}, {n} storeys, {txt}, cover {frac:.0%}")
        print("      " + ", ".join(f"{a} {b}" for a, b in fam.most_common(6)))
        for line in outline.split("\n"):
            print("        " + line)
    for k, r in enumerate(rows[:args.write]):
        out = prog / f"wings-{k + 1}.dom"
        dom.dump(r[5], str(out))
        print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

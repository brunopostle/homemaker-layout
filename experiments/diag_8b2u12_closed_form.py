"""Closed-form ratios for a fixed topology, against the 80-evaluation inner loop
(`homemaker-py-8b2u.12`).

In a slicing tree over a rectangle, the ratio at a cut that gives the two
sides the areas they are owed is closed-form: what the low side is owed over
what both are. No iteration, no evaluation. A search spends ~80 evaluations a
child on Nelder-Mead instead. This measures how much of that the arithmetic
already has, on frozen topologies: every tracked orthogonal coldstart design,
converted to a native tree, its ratios thrown away.

**What a cell is owed.** A room: its programme `size` (times its share, for a
shared leaf). Circulation and outdoor cells have no size in the programme, and
that is the closed form's one guess, so it is made two ways:

  closed   each storey's spare area -- the plot less that storey's rooms --
           split equally between its circulation and outdoor cells, none
           owed less than a square of its class's minimum width
  closedO  circulation is owed that square and no more; the outdoor cells
           split the spare (all of them do, on a storey with no outdoor cell)

Where storeys stack on one cut, a side is owed the MOST any storey wants of
it (`--stack mean` takes the average).

Starts, each followed by N evaluations of the inner loop the search uses
(`innerloop.optimise`, Nelder-Mead), N in 0, 10, 20, 40, 80:

  half    every ratio 0.5                 a new topology today
  closed  the closed form                 the arithmetic
  closedO the closed form, second guess
  solver  `solver.solve_ratios` from 0.5  today's dimensioner: least squares on
                                          area, width and proportion. It
                                          iterates, but calls no scorer
  cf+sol  the same, started from `closed`

The solver is stopped at `--solver-nfev` function evaluations (default 100).
Left at its own limit of 4,000 it usually converges in seconds, but the first
run of this experiment sat for more than twenty minutes inside ONE call on
maple-court and was abandoned at 41 designs of 48; its fail counts for those
41 are in DESIGN.md §39.109 beside the capped ones. A step that takes seconds
or half an hour is not one a search can call per child, and the cap is part
of what is being measured.

and `R`, the design as committed: the ratios 500k evaluations of search found.
N evaluations INCLUDE scoring the start, so N = 0 is the start itself scored
once for the table and N = 10 is the start plus nine moves.

A fail count is the number to read; a score is 0.5 ** fails times a quotient,
so it is given as log2(score / R's score).

    PYTHONPATH=src python experiments/diag_8b2u12_closed_form.py
    PYTHONPATH=src python experiments/diag_8b2u12_closed_form.py --self-test
"""

from __future__ import annotations

import argparse
import copy
import math
import sys
import time
from pathlib import Path

from homemaker_layout import (cells, dom, dom_v2, geometry, innerloop, programme,
                              solver)
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
BUDGETS = (0, 10, 20, 40, 80)
ARMS = ("half", "closed", "closedO", "solver", "cf+sol")


# --------------------------------------------------------------------------- #
# the closed form
# --------------------------------------------------------------------------- #
def owed(root, reqs, conf, stack: str = "max", outside_absorbs: bool = False) -> dict:
    """``{id(node): area owed}`` for every node of every storey."""
    g0 = geometry._native(root)
    plot_area = (cells.area(geometry._native_frame(g0)[2]) if g0 is not None
                 else geometry.area(dom.levels(root)[0]))     # a quad tree's plot
    target: dict = {}
    for lvl in dom.levels(root):
        leaves = lvl.leaves()
        generic = [lf for lf in leaves if lf.type not in reqs]
        rooms = sum(reqs[lf.type].size * max(1, lf.share) for lf in leaves if lf.type in reqs)
        floor = {id(lf): (solver._generic_min_width(lf, conf) or 1.2) ** 2 for lf in generic}
        takers = generic
        if outside_absorbs and any(dom.is_outside(lf) for lf in generic):
            takers = [lf for lf in generic if dom.is_outside(lf)]
        rest = sum(floor[id(lf)] for lf in generic if lf not in takers)
        spare = (plot_area - rooms - rest) / len(takers) if takers else 0.0
        for lf in leaves:
            if lf.type in reqs:
                target[id(lf)] = reqs[lf.type].size * max(1, lf.share)
            else:
                target[id(lf)] = max(spare, floor[id(lf)]) if lf in takers else floor[id(lf)]

    out: dict = {}

    def want(n) -> float:
        if id(n) in out:
            return out[id(n)]
        own = (want(n.left) + want(n.right)) if n.divided else target.get(id(n), 0.0)
        above = dom._above_node(n)
        if above is not None:
            up = want(above)
            own = max(own, up) if stack == "max" else (own + up) / 2
        out[id(n)] = own
        return own

    for lvl in dom.levels(root):
        want(lvl)
    return out


def closed_form(root, reqs, conf, stack: str = "max", outside_absorbs: bool = False) -> None:
    """Write the closed-form ratio into every cut that draws a wall. A ratio
    is the LEFT child's share of the node, whichever way the cut is turned."""
    w = owed(root, reqs, conf, stack, outside_absorbs)
    for b in solver.free_branches(root):
        lo, hi = w[id(b.left)], w[id(b.right)]
        r = lo / (lo + hi) if lo + hi > 0 else 0.5
        r = min(1 - solver._EPS, max(solver._EPS, r))
        b.division = [r, r]
    geometry.clear_cache()


# --------------------------------------------------------------------------- #
# the experiment
# --------------------------------------------------------------------------- #
def corpus(programmes, pattern):
    for name in programmes:
        prog = REPO / "examples" / name
        for p in sorted(prog.glob(pattern)):
            yield prog, p


def native(path):
    geometry.ORTHOGONAL_DIVISION = True
    root = dom_v2.to_native(dom.load(str(path)))
    geometry.ORTHOGONAL_DIVISION = False
    geometry.clear_cache()
    dom.link(root)
    return root


def half(root):
    for b in solver.free_branches(root):
        b.division = [0.5, 0.5]
    geometry.clear_cache()


def boundary_share(root) -> float:
    """Share of cells with a side on the plot: where a rectangle's area is not
    its ratio's to give."""
    n = on = 0
    for lvl in dom.levels(root):
        for lf in lvl.leaves():
            n += 1
            on += any(geometry.is_external(geometry.boundary_id(lf, e))
                      for e in range(geometry.n_edges(lf)))
    return on / n if n else 0.0


def run(programmes, pattern, stack, budgets=BUDGETS, limit=None, nfev=100, checkpoint=None):
    import pickle

    rows = []
    if checkpoint and Path(checkpoint).exists():
        rows = pickle.loads(Path(checkpoint).read_bytes())
        print(f"  resuming: {len(rows)} designs already in {checkpoint}", file=sys.stderr)
    done = {(r["programme"], r["name"]) for r in rows}
    for prog, p in corpus(programmes, pattern):
        if (prog.name, p.name) in done:
            continue
        if limit is not None and sum(r["programme"] == prog.name for r in rows) >= limit:
            continue
        fit = Fitness(*load_config(prog))
        reqs = programme.load_programme_dir(str(prog))
        conf = fit._conf

        def score(r):
            geometry.clear_cache()
            s, f = fit.score_with_fails(copy.deepcopy(r))
            geometry.clear_cache()
            return s, len(f)

        base = native(p)
        row = {"programme": prog.name, "name": p.name, "R": score(base),
               "dof": len(solver.free_branches(base)), "boundary": boundary_share(base)}
        for arm in ARMS:
            start = copy.deepcopy(base)
            dom.link(start)
            t0 = time.process_time()
            if arm in ("half", "solver"):
                half(start)
            else:
                closed_form(start, reqs, conf, stack, outside_absorbs=arm == "closedO")
            if arm in ("solver", "cf+sol"):
                try:
                    res = solver.solve_ratios(start, reqs, strip=False, conf=conf,
                                              max_nfev=nfev)
                    row[arm, "nfev"] = res.nfev
                    row[arm, "capped"] = res.status == 0
                except Exception:           # it may refuse a tree
                    row[arm, "raised"] = True
            row[arm, "setup_s"] = time.process_time() - t0
            for n in budgets:
                r = copy.deepcopy(start)
                dom.link(r)
                if n:
                    innerloop.optimise(r, str(prog), x0=None, budget=n)
                row[arm, n] = score(r)
        rows.append(row)
        if checkpoint:
            Path(checkpoint).write_bytes(pickle.dumps(rows))
        print(f"  {prog.name}/{p.name.replace('coldstart-', '')}: R {row['R'][1]} fails; "
              + "; ".join(f"{a} " + "/".join(str(row[a, n][1]) for n in budgets)
                          for a in ARMS), file=sys.stderr, flush=True)
    return rows


def _log2(a: float, b: float) -> float:
    return math.log2(a / b) if a > 0 and b > 0 else float("nan")


def report(rows, budgets=BUDGETS) -> None:
    arms = ARMS
    groups = list(dict.fromkeys(r["programme"] for r in rows)) + ["ALL"]
    print("\nTotal fails (and mean log2 of score over the committed design's)\n")
    print(f"{'programme':<16} {'n':>3} {'cuts':>5} {'on plot':>7} {'R':>5}  {'start':<7}"
          + "".join(f"{'N=' + str(n):>14}" for n in budgets))
    for g in groups:
        sel = [r for r in rows if g == "ALL" or r["programme"] == g]
        for k, arm in enumerate(arms):
            head = (f"{g:<16} {len(sel):3d} {sum(r['dof'] for r in sel) / len(sel):5.0f} "
                    f"{100 * sum(r['boundary'] for r in sel) / len(sel):6.0f}% "
                    f"{sum(r['R'][1] for r in sel):5d}") if k == 0 else " " * 41
            cols = []
            for n in budgets:
                fails = sum(r[arm, n][1] for r in sel)
                logs = [_log2(r[arm, n][0], r["R"][0]) for r in sel]
                logs = [x for x in logs if x == x]
                cols.append(f"{fails:6d} ({sum(logs) / len(logs):+6.1f})" if logs else f"{fails:6d}")
            print(f"{head}  {arm:<7}" + "".join(f"{c:>14}" for c in cols))
    print("\nShare of the way from `half` scored cold to the committed design, in fails:"
          "\n0% is every ratio at 0.5, 100% is what 500k evaluations of search found.\n")
    print(f"{'programme':<16} {'start':<7}" + "".join(f"{'N=' + str(n):>8}" for n in budgets))
    for g in groups:
        sel = [r for r in rows if g == "ALL" or r["programme"] == g]
        f = lambda arm, n: sum(r[arm, n][1] for r in sel)     # noqa: E731
        gap = f("half", 0) - sum(r["R"][1] for r in sel)
        for k, arm in enumerate(arms):
            print(f"{g if k == 0 else '':<16} {arm:<7}" + "".join(
                f"{100 * (f('half', 0) - f(arm, n)) / gap:7.0f}%" if gap else f"{'-':>8}"
                for n in budgets))
    print("\nmean CPU time to make the start, per design: " + ", ".join(
        f"{a} {1e3 * sum(r[a, 'setup_s'] for r in rows) / len(rows):.1f} ms" for a in arms[1:]))
    for a in ("solver", "cf+sol"):
        ok = [r for r in rows if (a, "nfev") in r]
        print(f"{a}: raised on {sum(bool(r.get((a, 'raised'))) for r in rows)} designs, stopped "
              f"at the cap on {sum(r[a, 'capped'] for r in ok)} of {len(ok)}, "
              f"mean {sum(r[a, 'nfev'] for r in ok) / max(1, len(ok)):.0f} function evaluations, "
              f"longest {max((r[a, 'setup_s'] for r in rows), default=0):.0f} s")
    print("\nDesign by design against `half` + 80 evaluations (fewer fails / the same / more):")
    for arm, n in (("closed", 0), ("closedO", 0), ("closed", 20), ("closedO", 20),
                   ("solver", 0), ("cf+sol", 0), ("solver", 20), ("cf+sol", 20)):
        w = sum(r[arm, n][1] < r["half", 80][1] for r in rows)
        t = sum(r[arm, n][1] == r["half", 80][1] for r in rows)
        print(f"  {arm:<7} N={n:<2}  {w:3d} / {t:3d} / {len(rows) - w - t:3d}")


def self_test() -> int:
    """The closed form must do what it says where it can be checked exactly:
    on a rectangular plot every cell is a rectangle, so every room gets its
    programme area times one common factor. And the check must fire: with one
    ratio moved, it does not."""
    prog = REPO / "examples" / "programme-house"
    reqs = programme.load_programme_dir(str(prog))
    tree = {"cut": "u", "at": 0.5,
            "low": {"cut": "v", "at": 0.5, "low": {"cell": "l1"}, "high": {"cell": "t2"}},
            "high": {"cut": "v", "at": 0.5, "low": {"cell": "b1"},
                     "high": {"cut": "u", "at": 0.5, "low": {"cell": "b2"}, "high": {"cell": "t1"}}}}
    doc = {"format": "homemaker-dom", "version": 2, "frame": {"u": [1.0, 0.0]},
           "plot": [[0, 0], [14, 0], [14, 9], [0, 9]], "wall_outer": 0.0, "wall_inner": 0.08,
           "storeys": [{"elevation": 0.0, "height": 3.0, "tree": tree}]}

    def spread(nudge=0.0):
        root = dom_v2.from_document(doc, native=True)
        dom.link(root)
        closed_form(root, reqs, {})
        if nudge:
            b = solver.free_branches(root)[-1]
            b.division = [b.division[0] + nudge] * 2
            geometry.clear_cache()
        k = [geometry.area(lf) / reqs[lf.type].size for lf in root.leaves()]
        return max(k) / min(k) - 1

    exact, moved = spread(), spread(0.05)
    ok = exact < 1e-9 and moved > 0.01
    print(f"self-test {'PASSED' if ok else 'FAILED'}: areas off their owed proportions by "
          f"{exact:.2g} (want 0), and by {moved:.2g} with one ratio moved (want > 0.01)")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default="coldstart-*+orth-500000-s*.dom")
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--stack", choices=("max", "mean"), default="max")
    ap.add_argument("--limit", type=int, help="designs per programme")
    ap.add_argument("--solver-nfev", type=int, default=100,
                    help="stop solve_ratios after this many function evaluations")
    ap.add_argument("--checkpoint", metavar="FILE",
                    help="keep finished designs here and resume from it")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    geometry.ORTHOGONAL_DIVISION = False
    if a.self_test:
        return self_test()
    rows = run(a.programme or PROGRAMMES, a.corpus, a.stack, limit=a.limit,
               nfev=a.solver_nfev, checkpoint=a.checkpoint)
    report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

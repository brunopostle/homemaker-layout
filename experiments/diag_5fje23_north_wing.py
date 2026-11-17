"""Can the search's own moves turn the health-centre winner's north wing the
way the owner drew it (`homemaker-py-5fje.23`, DESIGN.md §39.240)?

The owner, 2026-11-17, on §39.239's winner: the north wing's corridor is too
wide because the manager's office shares its strip, cut the same way as the
wing's top-level division; turn that division so the office takes the whole
east end of the wing, and the corridor and the treatment room can each be as
wide as they need.

Every rotate, pivot and pivot3 the operators can make on a branch inside
``--node`` (and, with ``--pairs``, every pair of them) is applied to the
design, its ratios re-tuned with the inner loop, and scored. Printed per move:
fails, score, and the usable width of the cells the owner named. A move that
reaches the owner's plan shows ``mo1`` spanning the wing's depth.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_5fje23_north_wing.py \\
        [--design D.dom] [--node lrr] [--budget 300] [--pairs]
"""
import argparse
import copy
import sys
import time
from pathlib import Path

from homemaker_layout import dom, geometry, innerloop, operators
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parent.parent
DESIGN = REPO / "experiments/results/halving-health-rulings/drawings/winner-one-5.dom"
PROG = REPO / "examples/health-centre"
WATCH = ("mo1", "tr1", "C")


def moves(root, under):
    """(label, function applying it in place to a copy's levels)."""
    lvls = dom.levels(root)
    out = []
    sub = lvls[0].by_id(under)
    stack = [sub]
    while stack:
        n = stack.pop()
        if not n.divided:
            continue
        stack += [n.left, n.right]
        for t in (1, 2, 3):
            out.append((f"rotate {n.id}+{t}", ("rot", n.id, t)))
        if operators._pivotable(lvls, 0, n):
            out.append((f"pivot {n.id}", ("piv", n.id)))
        for side, span in operators._pivot3_options(lvls, 0, n):
            out.append((f"pivot3 {n.id} {side}{span}", ("p3", n.id, side, span)))
    return out


def apply(root, mv):
    lvls = dom.levels(root)
    n = lvls[0].by_id(mv[1])
    if n is None or not n.divided:
        return False
    if mv[0] == "rot":
        n.rotation = (n.rotation + mv[2]) % 4
    elif mv[0] == "piv":
        if not operators._pivotable(lvls, 0, n):
            return False
        operators._pivot(lvls, 0, n)
    else:
        if (mv[2], mv[3]) not in operators._pivot3_options(lvls, 0, n):
            return False
        operators._pivot3(lvls, 0, n, mv[2], mv[3])
    dom.link(root)
    geometry.clear_cache()
    return True


def watch(root):
    out = []
    for lf in dom.levels(root)[0].by_id(ARGS.node).leaves():
        if lf.type in WATCH:
            out.append(f"{lf.type}:{geometry.usable_width(lf):.2f}x{geometry.area(lf):.0f}")
    return " ".join(out)


def score(fit, root, budget):
    r = innerloop.optimise(root, str(PROG), budget=budget)
    geometry.clear_cache()
    s, f = fit.score_with_fails(root)
    return s, list(f)


def main():
    global ARGS
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--design", default=str(DESIGN))
    ap.add_argument("--node", default="lrr")
    ap.add_argument("--budget", type=int, default=300)
    ap.add_argument("--pairs", action="store_true")
    ARGS = a = ap.parse_args()
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    fit = Fitness(*load_config(PROG))
    base = dom.load(a.design)
    dom.link(base)
    geometry.clear_cache()
    s0, f0 = fit.score_with_fails(base)
    print(f"as committed\t{len(f0)}\t{s0:.4g}\t{watch(base)}\t{'; '.join(f0)}")
    ctl = copy.deepcopy(base)
    s, f = score(fit, ctl, a.budget)
    print(f"re-tuned, no move\t{len(f)}\t{s:.4g}\t{watch(ctl)}\t{'; '.join(f)}", flush=True)
    seqs = [[m] for m in moves(base, a.node)]
    if a.pairs:
        seqs = [[m1, m2] for m1 in moves(base, a.node) for m2 in moves(base, a.node) if m1 != m2] + seqs
    t0 = time.process_time()
    for seq in seqs:
        c = copy.deepcopy(base)
        dom.link(c)
        geometry.clear_cache()
        if not all(apply(c, mv) for _, mv in seq):
            continue
        s, f = score(fit, c, a.budget)
        print(f"{' + '.join(lbl for lbl, _ in seq)}\t{len(f)}\t{s:.4g}\t{watch(c)}\t{'; '.join(f)}",
              flush=True)
    print(f"# {len(seqs)} sequences, {time.process_time() - t0:.0f} s CPU")


if __name__ == "__main__":
    main()

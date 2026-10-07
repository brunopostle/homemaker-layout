"""How many slicing trees draw one layout? (`homemaker-py-8b2u.15`)

A slicing tree is not a unique name for a set of cells. Two redundancies are
structural, and on a native tree both can be counted exactly:

  association  k parallel cuts in a row -- a node cut along one axis whose
               child is cut along the same axis -- make k+1 strips, and any
               bracketing of them is the same strips: Catalan(k) trees.
  turn         a cut started from the opposite side, with its children
               swapped and its ratio complemented, is the same cut: 2 per
               cut. (`rotation` 0 and 2, or 1 and 3.)

A third -- two perpendicular cuts that happen to cross at one point, which
either may be the parent of -- needs two ratios to coincide exactly and is
not counted.

For every orthogonal coldstart artefact, per storey as the storey is drawn
(inherited cuts included): the cuts, the runs of parallel cuts and their
lengths, and the number of trees that draw the same cells, as a power of two.
`genome.signature`, the search's only notion of "the same topology", tells
none of them apart.

    PYTHONPATH=src python experiments/diag_8b2u15_redundancy.py
    PYTHONPATH=src python experiments/diag_8b2u15_redundancy.py --self-test
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from homemaker_layout import dom, dom_v2, genome, geometry, operators, solver

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")


def catalan(k: int) -> int:
    return math.comb(2 * k, k) // (k + 1)


def runs(level_root) -> "list[int]":
    """Lengths (in cuts) of the maximal runs of parallel cuts on one storey."""
    out: list = []

    def strips(n, axis) -> int:
        """Cuts in the run through ``n`` along ``axis``; other subtrees are
        walked as runs of their own."""
        if not n.divided:
            return 0
        a = geometry._native_cut(n)[0]
        if a != axis:
            walk(n)
            return 0
        return 1 + strips(n.left, axis) + strips(n.right, axis)

    def walk(n) -> None:
        if not n.divided:
            return
        axis = geometry._native_cut(n)[0]
        out.append(1 + strips(n.left, axis) + strips(n.right, axis))

    walk(level_root)
    return out


def native(path):
    geometry.ORTHOGONAL_DIVISION = True
    root = dom_v2.to_native(dom.load(str(path)))
    geometry.ORTHOGONAL_DIVISION = False
    geometry.clear_cache()
    dom.link(root)
    return root


def census() -> None:
    print(f"{'programme':<16} {'designs':>7} {'cuts/storey':>12} {'in a run of 2+':>15} "
          f"{'longest run':>12} | trees per layout, log2: {'association':>12} {'turn':>6} {'both':>6}")
    for name in PROGRAMMES:
        c = Counter()
        longest = 0
        per_design = []
        for p in sorted((REPO / "examples" / name).glob("coldstart-*+orth-500000-s*.dom")):
            root = native(p)
            assoc = turn = 0.0
            for lvl in dom.levels(root):
                rs = runs(lvl)
                c["storeys"] += 1
                c["cuts"] += sum(rs)
                c["in runs"] += sum(r for r in rs if r >= 2)
                longest = max(longest, max(rs, default=0))
                assoc += sum(math.log2(catalan(r)) for r in rs)
            # a turn is a gene of an OWNED cut; inherited ones have none
            turn = float(len(solver.free_branches(root)))
            per_design.append((assoc, turn))
            c["designs"] += 1
        n = c["designs"]
        a = sum(x for x, _ in per_design) / n
        t = sum(y for _, y in per_design) / n
        print(f"{name:<16} {n:7d} {c['cuts'] / c['storeys']:12.1f} "
              f"{100 * c['in runs'] / c['cuts']:14.0f}% {longest:12d} | "
              f"{'':>23} {a:12.1f} {t:6.1f} {a + t:6.1f}")
    print("\n`association` counts storeys separately, so it overstates a little where an"
          "\nupper storey inherits a run it could not re-bracket on its own.")


def self_test() -> int:
    """The count against trees whose answer is known, and against the one
    operator that re-brackets: `mutate_reassociate` must change the signature
    and keep the same rooms in the same four strips -- that IS the redundancy."""
    def doc(tree):
        return {"format": "homemaker-dom", "version": 2, "frame": {"u": [1.0, 0.0]},
                "plot": [[0, 0], [20, 0], [20, 10], [0, 10]], "wall_outer": 0.0,
                "wall_inner": 0.08, "storeys": [{"elevation": 0.0, "height": 3.0, "tree": tree}]}

    leaf = lambda t: {"cell": t}                                    # noqa: E731
    strips4 = {"cut": "v", "at": 0.25, "low": leaf("a1"), "high": {
        "cut": "v", "at": 1 / 3, "low": leaf("a2"), "high": {
            "cut": "v", "at": 0.5, "low": leaf("a3"), "high": leaf("a4")}}}
    grid = {"cut": "v", "at": 0.5,
            "low": {"cut": "u", "at": 0.5, "low": leaf("a1"), "high": leaf("a2")},
            "high": {"cut": "u", "at": 0.5, "low": leaf("a3"), "high": leaf("a4")}}
    a = runs(dom_v2.from_document(doc(strips4), native=True))
    b = sorted(runs(dom_v2.from_document(doc(grid), native=True)))
    ok = a == [3] and catalan(3) == 5 and b == [1, 1, 1]

    root = dom_v2.from_document(doc(strips4), native=True)
    dom.link(root)
    moved = same = 0
    for seed in range(20):
        geometry.clear_cache()
        child, desc = operators.mutate_reassociate(root, np.random.default_rng(seed), ["a1"])
        if "noop" in desc:
            continue
        moved += genome.signature(child) != genome.signature(root)
        same += sorted(lf.type for lf in child.leaves()) == sorted(lf.type for lf in root.leaves())
    ok = ok and moved > 0 and same == moved
    print("self-test", "PASSED" if ok else "FAILED", f"-- runs {a} and {b}; "
          f"reassociate gave {moved} new signatures over the same cells' types")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    geometry.ORTHOGONAL_DIVISION = False
    return self_test() if a.self_test else (census() or 0)


if __name__ == "__main__":
    sys.exit(main())

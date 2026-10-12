"""`homemaker-py-w4e`: what would `mutate_core_undivide` do if it could fire?

§39.79's census found the operator declined 960 draws of 960. Its precondition
asks for a path OWNED on two or more storeys, and under below-inheritance a
path is owned on exactly one. The bead left two remedies -- delete the
operator, or repair the precondition -- and said to read the second carefully
before choosing. This is that reading, as a measurement.

The operator's docstring: "Reverse of core_divide: merge a C sub-core back
into a single C leaf on all floors." `core_divide` turns a `C` leaf that
stacks on 2+ storeys into `C | <some type>` on each of them. So there are TWO
things between the code and its docstring, not one:

  precondition  it reads `_owned_branches`; what `core_divide` leaves behind
                is a path DIVIDED on 2+ storeys, owned on the lowest
  result        the merged cell takes the type of a ROOM child if there is
                one (`keep[0]`), and `C` only when neither child is a room.
                The docstring says a single C leaf

Three variants, the operator copied here so that `src/` is not touched:

  shipped   `operators.mutate_core_undivide` as it is
  divided   the precondition repaired, the result as written
  restore   the precondition repaired, and the merged cell typed `C`

Two settings, the second being the state a search actually offers the move
(§39.75: an answer changed twenty-fold on that distinction):

  --converged    each corpus artefact as committed
  --after-divide each artefact after one `core_divide` -- the move this one
                 exists to reverse

Per (variant, setting): how often it fires; whether an intact stair shaft
survives (`operators._shaft_paths`); the change in fails, child scored as it
stands; and, after `core_divide`, whether the tree is the parent again
(`genome.signature`, which ignores ratios).

    PYTHONPATH=src python experiments/diag_w4e_core_undivide.py [--draws 8]
    PYTHONPATH=src python experiments/diag_w4e_core_undivide.py --self-test
"""

from __future__ import annotations

import argparse
import copy
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from homemaker_layout import dom, genome, geometry, operators, programme
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
VARIANTS = ("shipped", "divided", "restore")


def core_undivide(root, rng, types, *, restore_c: bool):
    """`operators.mutate_core_undivide` with its precondition reading every
    DIVIDED node rather than every owned one, and optionally the docstring's
    result."""
    child = copy.deepcopy(root)
    lvls = dom.levels(child)
    parent_paths: dict = {}
    for li, lvl in enumerate(lvls):
        for n in operators._level_nodes(lvl):
            if (n.divided and n.left.type == dom.GENERIC_STAIR
                    and not n.left.divided and not n.right.divided):
                parent_paths.setdefault(n.id or "", []).append(li)
    core_parents = [(p, lis) for p, lis in parent_paths.items() if len(lis) >= 2]
    if not core_parents:
        return operators._finalise(child), "core_undivide noop"
    path, level_indices = operators._pick(rng, core_parents)
    for li in level_indices:
        node = lvls[li].by_id(path)
        if node is None or not node.divided:
            continue
        if restore_c:
            node.type = dom.GENERIC_STAIR
        else:
            keep = [t for t in (node.left.type, node.right.type)
                    if t and not dom.is_generic(t)]
            node.type = keep[0] if keep else (node.left.type or str(operators._pick(rng, types)))
        dom.hand_cut_up(node)
        node.division = None
        node.left = node.right = None
    return operators._finalise(child), f"core_undivide {path} ({len(level_indices)} floors)"


def apply(variant, root, rng, types):
    if variant == "shipped":
        return operators.mutate_core_undivide(root, rng, types)
    return core_undivide(root, rng, types, restore_c=variant == "restore")


def artefacts(pattern):
    for name in PROGRAMMES:
        prog = REPO / "examples" / name
        fit = Fitness(*load_config(prog))
        reqs = programme.load_programme_dir(str(prog))
        for p in sorted(prog.glob(pattern)):
            geometry.clear_cache()
            # the form a search mutates: dead fields synchronised (genome.py)
            root = genome.decode(genome.encode(dom.load(str(p))))
            dom.link(root)
            yield name, root, fit, sorted(reqs) + ["C", "O"]


def fails(fit, root) -> int:
    geometry.clear_cache()
    n = len(fit.score_with_fails(copy.deepcopy(root))[1])
    geometry.clear_cache()
    return n


def shafts(root) -> int:
    geometry.clear_cache()
    return len(operators._shaft_paths(dom.levels(root)))


def census(pattern: str, draws: int, after_divide: bool) -> dict:
    out = {v: Counter() for v in VARIANTS}
    for name, base, fit, types in artefacts(pattern):
        for seed in range(draws):
            parent = base
            if after_divide:
                parent, desc = operators.mutate_core_divide(
                    base, np.random.default_rng(1000 + seed), types)
                if "noop" in desc:
                    for v in VARIANTS:
                        out[v]["no core to divide"] += 1
                    continue
            f0, s0 = fails(fit, parent), shafts(parent)
            for v in VARIANTS:
                c = out[v]
                c["draws"] += 1
                child, desc = apply(v, parent, np.random.default_rng(seed), types)
                if "noop" in desc:
                    continue
                c["fired"] += 1
                s1, f1 = shafts(child), fails(fit, child)
                c["had a shaft"] += s0 > 0
                c["emptied"] += s0 > 0 and s1 == 0
                c["fewer shafts"] += s1 < s0
                c["d_fails"] += f1 - f0
                c["better"] += f1 < f0
                c["worse"] += f1 > f0
                if after_divide:
                    c["parent again"] += genome.signature(child) == genome.signature(base)
                    c["d_fails_vs_base"] += f1 - fails(fit, base)
    return out


def show(title: str, res: dict, after_divide: bool) -> None:
    print(f"\n=== {title} ===")
    head = (f"{'variant':<9} {'draws':>6} {'fired':>6} {'had shaft':>10} {'emptied':>8} "
            f"{'fewer':>6} {'mean d fails':>13} {'better':>7} {'worse':>6}")
    print(head + (f" {'parent again':>13} {'d fails vs before divide':>25}" if after_divide else ""))
    for v in VARIANTS:
        c = res[v]
        n = c["fired"]
        row = (f"{v:<9} {c['draws']:6d} {n:6d} {c['had a shaft']:10d} {c['emptied']:8d} "
               f"{c['fewer shafts']:6d} "
               + (f"{c['d_fails'] / n:+13.2f}" if n else f"{'-':>13}")
               + f" {c['better']:7d} {c['worse']:6d}")
        if after_divide:
            row += (f" {c['parent again']:13d} "
                    + (f"{c['d_fails_vs_base'] / n:+25.2f}" if n else f"{'-':>25}"))
        print(row)
    skipped = res[VARIANTS[0]]["no core to divide"]
    if skipped:
        print(f"({skipped} draws had no stacked C leaf for core_divide to divide)")


def self_test() -> int:
    """Each variant must do what its name says on a tree where the answer is
    known: two storeys, a `C | b1` pair at one path on both. `shipped` must
    decline; `divided` must fire and leave a room where the stair was;
    `restore` must fire and leave a `C` leaf on both storeys."""
    def building():
        def storey():
            return dom.Node(division=[0.5, 0.5],
                            left=dom.Node(type="l1"),
                            right=dom.Node(division=[0.5, 0.5], left=dom.Node(type="E"),
                                           right=dom.Node(type="b1")))
        root = storey()
        root.above = storey()
        dom.link(root)
        return root

    got = {}
    for v in VARIANTS:
        child, desc = apply(v, building(), np.random.default_rng(0), ["b1", "C", "O"])
        got[v] = ("noop" in desc, [lvl.by_id("r").type for lvl in dom.levels(child)])
    want = {"shipped": (True, [None, None]), "divided": (False, ["b1", "b1"]),
            "restore": (False, ["E", "E"])}
    ok = got == want
    print("self-test", "PASSED" if ok else f"FAILED: {got}")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default="coldstart-*+orth-500000-s*.dom")
    ap.add_argument("--draws", type=int, default=8)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    geometry.ORTHOGONAL_DIVISION = True
    if a.self_test:
        return self_test()
    show("converged: each artefact as committed",
         census(a.corpus, a.draws, after_divide=False), False)
    show("after one core_divide: the state this move exists to reverse",
         census(a.corpus, a.draws, after_divide=True), True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

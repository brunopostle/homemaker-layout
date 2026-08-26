"""A/B the `crinkliness_mode` repairs against the circulation-deletion incentive.

Evidence for `homemaker-py-ssz` / `homemaker-py-2v1` (DESIGN.md §38.6). The
test: on a constructed layout, delete each unpinned circulation/outside leaf
(by undividing its parent, which merges it into its sibling) and re-score. A
healthy objective should not pay you to do that.

Reports the count of deletions that still improve the score, and the median
score ratio, per mode. Splitting the rows by whether the deleted leaf was
buried or lit is what separates the two mechanisms:

* buried leaves are rewarded because ``quality_uncrinkliness`` returns a hard
  0.0, so they contribute zero value (§38.1);
* **lit** leaves are rewarded because ``value_circulation`` (50) is one sixth
  of ``value_inside`` (300), so merging corridor into room is a flat ×6 gain
  against a ×0.5 connectivity penalty (§38.2 refinement) — which no
  ``crinkliness_mode`` can touch.

.. warning::

   **The premise of this test is RETRACTED — see §38.2 and §38.8.** The ×6-vs-
   ×0.5 arithmetic assumed severing the spine costs one connectivity fail;
   measured, the connectivity count is unchanged in every rewarded deletion, so
   this script is not measuring what its docstring says. It is kept because the
   per-mode buried/lit split is still a useful description of what each mode
   touches, but a mode does **not** pass or fail on these numbers. The A/B that
   decides `ssz` is ``experiments/ab_ssz_search.py`` (fixed-budget search,
   scored under the stock objective).

Usage::

    python experiments/ab_crinkliness_mode_ssz.py
    python experiments/ab_crinkliness_mode_ssz.py --seeds 5 --progdir examples/maple-court
"""

from __future__ import annotations

import argparse
import copy

import numpy as np

from homemaker_layout import dom as dom_mod
from homemaker_layout import driver, fitness, geometry
from homemaker_layout import graph as graph_mod
from homemaker_layout import operators, programme

MODES = ("urb", "floor", "compact_ok", "exempt_circulation",
         "usage_daylight")


def make_fitness(progdir: str, mode: str) -> fitness.Fitness:
    """Evaluator matching ``driver.search``'s defaults, with one mode override."""
    overrides = dict(driver._overrides_for(
        leaf_sharing=True, superpose=False, max_share=None, conn_grade=False,
        collapse_insearch=True, multi_use=False) or {})
    overrides["crinkliness_mode"] = mode
    conf, cost = fitness.load_config(progdir, overrides=overrides)
    return fitness.Fitness(conf, cost)


def constructed_seed(progdir: str, seed: int) -> dom_mod.Node:
    reqs = programme.load_programme_dir(progdir)
    return operators.constructive_topology(
        dom_mod.load(f"{progdir}/init.dom"), reqs, np.random.default_rng(seed),
        sorted(reqs) + ["C", "O"],
        min_storeys=programme.storey_minimum(progdir),
        adjacency_aware=True, proportion_aware=True, circ_divisor=3,
        leaf_sharing=True, leaf_share_factor=3, depth_balanced=True,
        interior_outside=True, outside_divisor=3)


def unpinned_leaves(fit: fitness.Fitness, root: dom_mod.Node) -> list[tuple]:
    """(level, id, type, exposed_area) for circulation/outside leaves — the ones
    no missing-space cascade pins in place."""
    tree = copy.deepcopy(root)
    geometry.clear_cache()
    dom_mod.canonicalize_shares(tree)
    fit.preprocess_building(tree)
    dom_mod.merge_divided(tree)
    geometry.clear_cache()
    graphs = graph_mod.build_graphs(tree, fit.conf("door_width") or 1.2)

    out = []
    for li, lvl in enumerate(dom_mod.levels(tree)):
        for leaf in lvl.leaves():
            if dom_mod.is_outside(leaf) and not dom_mod.is_covered(leaf):
                continue
            # §39.4: generic structural types are EXACT `C`/`O`/`S`, never a
            # first-character prefix -- `cr1` is a programme room. This script
            # predates that rule and its original `type[:1].upper() in ("C","O")`
            # test swept programme rooms into the "unpinned" set, which is one
            # reason the §38.6 numbers do not reproduce.
            if not dom_mod.is_generic(leaf.type):
                continue
            out.append((li, leaf.id, leaf.type,
                        fit.area_outside(leaf, graphs[li], {})))
    return out


def delete_leaf(root: dom_mod.Node, li: int, lid: str) -> "dom_mod.Node | None":
    """Undivide the leaf's parent, merging it into its sibling. None if the cut
    is inherited (not owned at this storey) or the sibling is itself divided."""
    cand = copy.deepcopy(root)
    lvls = dom_mod.levels(cand)
    if li >= len(lvls):
        return None
    node = lvls[li].by_id(lid)
    if node is None or node.parent is None:
        return None
    parent = node.parent
    if parent.below is not None and parent.below.divided:
        return None
    sibling = parent.right if parent.left is node else parent.left
    if sibling is None or sibling.divided:
        return None
    parent.division = None
    parent.left = parent.right = None
    parent.type = sibling.type
    dom_mod.link(cand)
    geometry.clear_cache()
    return cand


def run(progdir: str, seeds: int) -> None:
    print(f"programme: {progdir}, {seeds} constructed seeds")
    print("a healthy objective rewards NO deletions\n")
    header = f"{'mode':<20}{'buried':<14}{'lit':<14}{'all':<14}median x"
    print(header)
    print("-" * len(header))

    for mode in MODES:
        fit = make_fitness(progdir, mode)
        counts = {"buried": [0, 0], "lit": [0, 0]}
        ratios = []
        for s in range(seeds):
            root = constructed_seed(progdir, s)
            base, _ = fit.score_with_fails(copy.deepcopy(root))
            for li, lid, _typ, exposed in unpinned_leaves(fit, root):
                cand = delete_leaf(root, li, lid)
                if cand is None:
                    continue
                score, _ = fit.score_with_fails(copy.deepcopy(cand))
                bucket = "buried" if exposed == 0 else "lit"
                counts[bucket][1] += 1
                ratios.append(score / base)
                if score > base:
                    counts[bucket][0] += 1
        tot = [counts["buried"][0] + counts["lit"][0],
               counts["buried"][1] + counts["lit"][1]]
        median = sorted(ratios)[len(ratios) // 2] if ratios else float("nan")
        buried = "%d/%d" % tuple(counts["buried"])
        lit = "%d/%d" % tuple(counts["lit"])
        both = "%d/%d" % tuple(tot)
        print(f"{mode:<20}{buried:<14}{lit:<14}{both:<14}x{median:.2f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--progdir", default="examples/harbor-house")
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args()
    run(args.progdir, args.seeds)


if __name__ == "__main__":
    main()

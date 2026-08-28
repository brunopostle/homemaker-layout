"""Are the crinkliness failures the objective emits real defects? (`homemaker-py-ssz`)

Not an A/B. This asks a correctness question the search cannot answer: of the
`crinkliness` failures the GLOBAL-target objective reports -- one daylight
requirement for every space, which is what the engine did before §38.10 -- how
many are on a space that does not want daylight at all?

A `crinkliness` fail says "this leaf has too little exposed wall for its area".
For anything occupied day to day that is a real defect. For a cupboard, a store
or a plant room it is not.

**The classification is read from the corpus, not guessed here.** A fail counts
as a non-defect exactly when that space declares `crinkliness: none` in its own
`patterns.config`. An earlier version of this script inferred it from `usage:`
instead and got a much larger, wrong answer -- it exempted corridors, WCs,
laundries and reception, none of which the owner exempts (DESIGN.md §38.11).
Corridors, courtyards and every occupied room want daylight.

Usage::

    python experiments/audit_crinkliness_truth.py
    python experiments/audit_crinkliness_truth.py --seeds 5
    python experiments/audit_crinkliness_truth.py --dom examples/harbor-house/generated.dom
"""

from __future__ import annotations

import argparse
import collections
import copy
from pathlib import Path

import numpy as np

from homemaker_layout import dom as dom_mod
from homemaker_layout import driver, fitness, geometry
from homemaker_layout import graph as graph_mod
from homemaker_layout import operators, programme

CORPUS = ["examples/harbor-house", "examples/maple-court", "examples/health-centre"]

# Ruled by the project owner: only rooms that are not occupied from day to day
# -- a cupboard, a store, a plant room -- do without daylight. Corridors need
# it. So does everything else: WCs, laundries, reception, waiting rooms,
# offices, consulting rooms. Which spaces those are is read from the configs
# themselves (a declared `crinkliness: none`), never inferred here.


def stock_fitness(progdir: str) -> fitness.Fitness:
    """Stock objective -- `crinkliness_mode` left at its "urb" default."""
    ov = dict(driver._overrides_for(
        leaf_sharing=True, superpose=False, max_share=None, conn_grade=False,
        collapse_insearch=True, multi_use=False) or {})
    conf, cost = fitness.load_config(progdir, overrides=ov)
    return fitness.Fitness(conf, cost)


def constructed(progdir: str, s: int) -> dom_mod.Node:
    reqs = programme.load_programme_dir(progdir)
    return operators.constructive_topology(
        dom_mod.load(f"{progdir}/init.dom"), reqs, np.random.default_rng(s),
        sorted(reqs) + ["C", "O"], min_storeys=programme.storey_minimum(progdir),
        adjacency_aware=True, proportion_aware=True, circ_divisor=3,
        leaf_sharing=True, leaf_share_factor=3, depth_balanced=True,
        interior_outside=True, outside_divisor=3)


def audit(fit: fitness.Fitness, root: dom_mod.Node) -> collections.Counter:
    """label -> count over the leaves that fail under ONE GLOBAL daylight target.

    Each is labelled with the leaf's usage, and marked exempt when that space
    declares `crinkliness: none` -- i.e. when the failure the old objective
    emitted was not a defect.
    """
    tree = copy.deepcopy(root)
    geometry.clear_cache()
    dom_mod.canonicalize_shares(tree)
    fit.preprocess_building(tree)
    dom_mod.merge_divided(tree)
    geometry.clear_cache()
    graphs = graph_mod.build_graphs(tree, fit.conf("door_width") or 1.2)

    out: collections.Counter = collections.Counter()
    for li, lvl in enumerate(dom_mod.levels(tree)):
        groups = geometry.boundary_groups(lvl)
        for leaf in lvl.leaves():
            if dom_mod.is_outside(leaf) and not dom_mod.is_covered(leaf):
                continue
            # the PRE-§38.10 objective: one global target for every leaf
            crink = fit.crinkliness(leaf, graphs[li], groups)
            if crink:
                distance, sigma = fit.conf("uncrinkliness")
                q = fitness.gaussian(1 / crink, 1.0, distance, sigma)
            else:
                q = 0.0
            if q >= fitness.FAIL_THRESHOLD:
                continue                       # not a failure even then
            label = fit.usage_of(leaf) or f"<generic {leaf.type}>"
            if fit.crinkliness_params(leaf) is None:
                label += "  [declares crinkliness: none]"
            out[label] += 1
    return out


def report(label: str, tally: collections.Counter) -> tuple[int, int]:
    total = sum(tally.values())
    real = sum(n for u, n in tally.items() if "crinkliness: none" not in u)
    print(f"=== {label}: {total} crinkliness fails")
    if not total:
        print("    none\n")
        return 0, 0
    for usage, n in tally.most_common():
        verdict = ("not a defect -- not occupied day to day"
                   if "crinkliness: none" in usage else "REAL DEFECT")
        print(f"    {usage:<44}{n:>4}   {verdict}")
    print(f"    -> {total - real}/{total} ({100 * (total - real) / total:.0f}%) "
          f"are reported against spaces that do not want daylight\n")
    return real, total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--corpus", nargs="+", default=CORPUS)
    ap.add_argument("--dom", nargs="*", default=[],
                    help="also audit these evolved .dom files (programme dir inferred)")
    args = ap.parse_args()

    print("Stock objective. Every fail classified by the leaf's declared usage.\n")
    grand_real = grand_total = 0

    for progdir in args.corpus:
        fit = stock_fitness(progdir)
        tally: collections.Counter = collections.Counter()
        for s in range(args.seeds):
            tally += audit(fit, constructed(progdir, s))
        r, t = report(f"{Path(progdir).name} ({args.seeds} constructed seeds)", tally)
        grand_real += r
        grand_total += t

    for dom_path in args.dom:
        progdir = str(Path(dom_path).parent)
        fit = stock_fitness(progdir)
        r, t = report(f"{dom_path} (evolved)", audit(fit, dom_mod.load(dom_path)))
        grand_real += r
        grand_total += t

    if grand_total:
        print(f"OVERALL: {grand_total - grand_real}/{grand_total} "
              f"({100 * (grand_total - grand_real) / grand_total:.0f}%) of the "
              f"crinkliness failures the objective reports are not defects.")


if __name__ == "__main__":
    main()

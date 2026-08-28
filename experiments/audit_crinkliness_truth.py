"""Are the crinkliness failures the objective emits real defects? (`homemaker-py-ssz`)

Not an A/B. This asks a correctness question the search cannot answer: of the
`crinkliness` failures the STOCK objective reports, how many are on a space
that architecturally wants daylight at all?

A `crinkliness` fail says "this leaf has too little exposed wall for its area".
For a bedroom or a living room that is a real defect. For a broom cupboard, a
WC, a plant room, an internal corridor or a covered courtyard it is not -- those
are ordinary buried architecture, and the fail is an artefact of applying one
daylight requirement to every space regardless of use (DESIGN.md §38.8).

Every fail is classified by the leaf's DECLARED `usage:` (§39.7), so nothing
here rests on how a code is spelled.

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

# Ruled by the project owner: everything a person occupies wants a window --
# WCs and bathrooms included, reception/waiting/foyer included, offices and
# consulting rooms included. Only stores, plant, records and laundry do not,
# together with the generic structural types (a corridor has its own
# `uncrinkliness_circulation` target; a courtyard is not a room).
NO_DAYLIGHT = {"utility"}


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
    """usage -> count, over the leaves that emit a stock `crinkliness` fail."""
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
            if fit.quality_uncrinkliness(leaf, graphs[li], groups) >= fitness.FAIL_THRESHOLD:
                continue                       # not a failure
            out[fit.usage_of(leaf) or f"<generic {leaf.type}>"] += 1
    return out


def report(label: str, tally: collections.Counter) -> tuple[int, int]:
    total = sum(tally.values())
    real = sum(n for u, n in tally.items() if u not in NO_DAYLIGHT
               and not u.startswith("<generic"))
    print(f"=== {label}: {total} crinkliness fails")
    if not total:
        print("    none\n")
        return 0, 0
    for usage, n in tally.most_common():
        exempt = usage in NO_DAYLIGHT or usage.startswith("<generic")
        verdict = ("not a defect -- no daylight wanted" if exempt
                   else "REAL DEFECT")
        print(f"    {usage:<18}{n:>4}   {verdict}")
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

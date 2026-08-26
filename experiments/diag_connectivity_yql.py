"""Why does `level N not connected` persist? (`homemaker-py-yql`, DESIGN.md §39.9)

`homemaker-py-2v1` closed NULL: severing a level's circulation is already
punished, so the fail is not something the search is paid to create. This asks
the follow-on question — is a connected layout **rarely constructed**, or
**constructed and then lost**?

`level N not connected` fires from `graph.connected_circulation`, which keeps
only the generic circulation leaves (`C`/`S`) and asks whether *they* form one
connected component. It runs on `graph_circ`, i.e. AFTER
`graph.has_circulation` has trimmed edges, so §39.7's usage change can in
principle reach it — report (b) measures whether it did.

Three reports:

  construct  what fraction of constructed seeds start connected, per level
  cost       the same, prefix-inferred usages vs declared (the §39.7 cost)
  survive    from a CONNECTED layout, how often does one mutation break
             connectivity, and would the outer comparator keep the mutant

Usage::

    python experiments/diag_connectivity_yql.py construct
    python experiments/diag_connectivity_yql.py cost
    python experiments/diag_connectivity_yql.py survive --seeds 40
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

import numpy as np

from homemaker_layout import dom as dom_mod
from homemaker_layout import driver, fitness, geometry
from homemaker_layout import graph as graph_mod
from homemaker_layout import operators, programme

CORPUS = ["examples/harbor-house", "examples/health-centre", "examples/maple-court"]
LEGACY_PREFIX = {"b": "bedroom", "t": "toilet", "l": "living", "k": "kitchen"}


def make_fitness(progdir: str) -> fitness.Fitness:
    overrides = driver._overrides_for(
        leaf_sharing=True, superpose=False, max_share=None, conn_grade=False,
        collapse_insearch=True, multi_use=False)
    conf, cost = fitness.load_config(progdir, overrides=dict(overrides or {}))
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


def connectivity(root: dom_mod.Node, usages: dict[str, str]) -> tuple[int, int]:
    """``(levels_connected, levels_total)`` for one tree.

    Mirrors the scorer: build the circ graphs, then ask
    ``connected_circulation`` per level on a copy, exactly as
    ``process_storey`` does.
    """
    tree = copy.deepcopy(root)
    geometry.clear_cache()
    dom_mod.canonicalize_shares(tree)
    _, circ = graph_mod.build_graphs_with_circ(tree, 1.2, lambda _f: None, usages)
    connected = sum(1 for gc in circ
                    if graph_mod.connected_circulation(gc.copy()))
    return connected, len(circ)


def report_construct(seeds: int) -> None:
    print(f"how often does a CONSTRUCTED seed start connected? ({seeds} seeds)\n")
    print(f"  {'programme':<18}{'levels connected':<20}{'seeds fully connected'}")
    print("  " + "-" * 62)
    for progdir in CORPUS:
        fit = make_fitness(progdir)
        usages = fit.usages()
        ok = tot = full = 0
        for s in range(seeds):
            c, n = connectivity(constructed_seed(progdir, s), usages)
            ok += c
            tot += n
            full += (c == n)
        print(f"  {Path(progdir).name:<18}{f'{ok}/{tot} ({100*ok/max(tot,1):.0f}%)':<20}"
              f"{full}/{seeds}")


def report_cost(seeds: int) -> None:
    """Did §39.7's usage change make level connectivity harder to achieve?"""
    print("§39.7 cost check — prefix-inferred usages vs declared "
          f"({seeds} seeds)\n")
    print(f"  {'programme':<18}{'prefix-inferred':<20}{'declared':<20}delta")
    print("  " + "-" * 68)
    for progdir in CORPUS:
        reqs = programme.load_programme_dir(progdir)
        declared = {c: r.usage for c, r in reqs.items()}
        legacy = {c: LEGACY_PREFIX.get(c[:1].lower(), "none") for c in reqs}
        res = {}
        for label, usages in (("legacy", legacy), ("declared", declared)):
            ok = tot = 0
            for s in range(seeds):
                c, n = connectivity(constructed_seed(progdir, s), usages)
                ok += c
                tot += n
            res[label] = (ok, tot)
        (a, ta), (b, tb) = res["legacy"], res["declared"]
        delta = 100 * b / max(tb, 1) - 100 * a / max(ta, 1)
        print(f"  {Path(progdir).name:<18}"
              f"{f'{a}/{ta} ({100*a/max(ta,1):.0f}%)':<20}"
              f"{f'{b}/{tb} ({100*b/max(tb,1):.0f}%)':<20}{delta:+.0f} pts")


def report_survive(seeds: int) -> None:
    """From a CONNECTED level, how fragile is that connectivity under one
    mutation — and would the comparator keep the mutant anyway?"""
    print(f"survival of connectivity under one mutation ({seeds} trials)\n")
    print(f"  {'programme':<18}{'started connected':<20}{'broken by mutation':<22}"
          f"{'…and kept by comparator'}")
    print("  " + "-" * 82)
    for progdir in CORPUS:
        fit = make_fitness(progdir)
        usages = fit.usages()
        reqs = programme.load_programme_dir(progdir)
        types = sorted(reqs) + ["C", "O"]
        started = broken = kept = 0
        rng = np.random.default_rng(0)
        for s in range(seeds):
            root = constructed_seed(progdir, s)
            c, n = connectivity(root, usages)
            if c != n:
                continue                      # only study layouts that ARE connected
            started += 1
            base_score, base_fails = fit.score_with_fails(copy.deepcopy(root))
            child, _desc = operators.mutate(root, rng, types, reqs=reqs)
            c2, n2 = connectivity(child, usages)
            if c2 == n2:
                continue
            broken += 1
            # would the outer loop admit it? lexicographic (-n_fails, fitness)
            score, fails = fit.score_with_fails(copy.deepcopy(child))
            if (-len(fails), score) > (-len(base_fails), base_score):
                kept += 1
        print(f"  {Path(progdir).name:<18}{f'{started}/{seeds}':<20}"
              f"{f'{broken}/{max(started,1)}':<22}{kept}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", choices=("construct", "cost", "survive"))
    ap.add_argument("--seeds", type=int, default=20)
    args = ap.parse_args()
    {"construct": report_construct, "cost": report_cost,
     "survive": report_survive}[args.report](args.seeds)


if __name__ == "__main__":
    main()

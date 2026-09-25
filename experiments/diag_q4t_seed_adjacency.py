"""Does the k7c narrowing reach the SEEDERS? (`homemaker-py-q4t`, §39.64)

`graph.has_adjacency` has required a USABLE outside neighbour since k7c
(§39.58). Three seeders decided the same question their own way and did not:
`cpsat`'s model (through the `context_types` it is handed), the greedy room
placement in `_assign_adjacency_aware`, and `_beam_place_rooms`. Each would
place a room against an unsupported void believing `adjacency: [o]` satisfied,
and the scorer would then refuse it.

The fix routes all three through `graph.satisfies_as_outside`, the scorer's own
predicate. Because that is now the single copy of the rule, the BEFORE arm is
reproducible exactly by stubbing it to `lambda nb: True` -- which is what this
harness does, so the two arms differ in one function and nothing else.

Measured per programme on freshly constructed seeds (no evolution, so this is
seconds rather than hours -- it is a seeding question, not a search question):

* `not adjacent to o` fails, the family the drift can produce;
* total fails and score, to catch the fix costing more than it saves.

Both arms are SCORED with the real predicate whichever arm built the seed: an
arm is judged by the objective, never by its own belief about adjacency.

programme-house is skipped -- it declares no outside adjacency at all, so there
is nothing here for it to get right or wrong.

Usage::

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_q4t_seed_adjacency.py
    ... --seeds 8 --solver cpsat
"""

from __future__ import annotations

import argparse
import copy
import os
import statistics
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
PROGRAMMES = ("harbor-house", "maple-court", "health-centre")


def build_seed(prog_dir: Path, seed: int, solver: str):
    from homemaker_layout import dom, geometry, operators, programme
    reqs = programme.load_programme_dir(str(prog_dir))
    types = sorted(reqs) + ["C", "O"]
    rng = np.random.default_rng(seed)
    n_st = max(programme.n_storeys_required(reqs),
               programme.storey_minimum(str(prog_dir)))
    buckets = programme.partition_rooms_by_storey(reqs, n_st, rng)
    base = operators.constructive_topology(
        dom.load(str(prog_dir / "init.dom")), reqs, rng, types,
        min_storeys=n_st, assign_solver=solver)
    root = operators.lift_base_to_storeys(base, buckets[1:], rng, types,
                                          reqs=reqs, assign_solver=solver)
    dom.link(root)
    geometry.clear_cache()
    return root


def score(root, prog_dir: Path):
    from homemaker_layout import fitness
    conf, cost = fitness.load_config(str(prog_dir))
    val, fails = fitness.Fitness(conf, cost).score_with_fails(copy.deepcopy(root))
    return val, [f for f in fails if f.strip()]


def arm(prog_dir: Path, seeds: range, solver: str, narrowed: bool):
    """`narrowed=False` stubs the shared predicate back to its pre-q4t answer."""
    from homemaker_layout import graph as graph_mod
    real = graph_mod.satisfies_as_outside
    stub = (lambda nb: True)
    rows = []
    try:
        for s in seeds:
            graph_mod.satisfies_as_outside = real if narrowed else stub
            root = build_seed(prog_dir, s, solver)
            graph_mod.satisfies_as_outside = real     # score honestly, always
            rows.append(score(root, prog_dir))
    finally:
        graph_mod.satisfies_as_outside = real
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--solver", default="greedy", choices=("greedy", "cpsat"),
                    help="which seeder to measure (greedy is the default path)")
    ap.add_argument("--programmes", nargs="*", default=list(PROGRAMMES))
    args = ap.parse_args()

    if os.environ.get("HOMEMAKER_ORTHOGONAL_DIVISION") != "1":
        print("NOTE: HOMEMAKER_ORTHOGONAL_DIVISION is not 1 -- this is the "
              "non-orthogonal objective (CLAUDE.md).\n")
    seeds = range(args.seeds)
    print(f"solver={args.solver}  seeds={args.seeds}\n")
    hdr = (f"{'programme':16s} {'arm':8s} {'adj-o fails':>12s} "
           f"{'all fails':>10s} {'score':>9s}")
    print(hdr)
    print("-" * len(hdr))
    totals: dict[str, list[tuple[int, int]]] = {}
    for name in args.programmes:
        d = REPO / "examples" / name
        for narrowed, label in ((False, "before"), (True, "after")):
            rows = arm(d, seeds, args.solver, narrowed)
            adj_o = [sum(1 for f in fails if "not adjacent to o" in f)
                     for _, fails in rows]
            allf = [len(fails) for _, fails in rows]
            sc = [v for v, _ in rows]
            print(f"{name:16s} {label:8s} {statistics.mean(adj_o):12.2f} "
                  f"{statistics.mean(allf):10.2f} {statistics.mean(sc):9.4f}")
            totals.setdefault(label, []).append((sum(adj_o), sum(allf)))
        print()
    for label in ("before", "after"):
        a = sum(x for x, _ in totals[label])
        b = sum(y for _, y in totals[label])
        print(f"{label:6s}: {a:4d} `not adjacent to o` fails, {b:5d} fails total")
    print("\nSeeding only. Whether the SEARCH ends better is a sweep question "
          "and is not asked here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

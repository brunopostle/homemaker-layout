"""A/B: does the shape-curve DP's exact feasible/infeasible verdict, composed
with the existing heuristic-count shape-feasibility pre-filter, beat the
heuristic-only filter on wall-clock/evals-to-fail-count, on the real
``driver.search`` loop (homemaker-py-wkh, DESIGN.md §37.5)?

Both arms run with ``feasibility_filter=True, feasibility_max_shape_fails=0``
(the existing §12.3 pre-filter switched on) so the only variable is whether
``shapecurve_prune`` additionally consults the DP (veto a heuristic prune when
DP-feasible; hard-prune immediately when DP-infeasible and the incumbent
already has zero total fails). Scoped to the DP's validated envelope
(DESIGN.md §37.2): single storey, no leaf_sharing/superpose/max_share/
multi_use -- ``examples/harbor-house-l0``, same benchmark and protocol as
``ab_shapecurve_warmstart.py`` for direct comparability.

Metric: mean (n_hard, n_soft, fitness) of ``driver.search``'s best individual
at a FIXED budget across several seeds, plus mean topologies explored (the
pre-filter's whole point is spending fewer evals per pruned topology, so more
topologies get tried at the same budget).

Usage: python experiments/ab_shapecurve_prune.py [budget] [n_seeds]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from homemaker_layout import dom, driver

PROGRAMME_DIR = Path(__file__).parent.parent / "examples" / "harbor-house-l0"


def run_arm(seed_root: dom.Node, budget: int, seed: int, prune: bool):
    t0 = time.perf_counter()
    r = driver.search(
        seed_root, PROGRAMME_DIR, budget=budget, pop_size=8, child_budget=80,
        seed_budget=200, seed=seed, leaf_sharing=False,
        feasibility_filter=True, feasibility_max_shape_fails=0,
        shapecurve_prune=prune,
    )
    elapsed = time.perf_counter() - t0
    return r, elapsed


def main() -> None:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    n_seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    seed_root = dom.load(str(PROGRAMME_DIR / "init.dom"))

    rows = []
    for seed in range(n_seeds):
        off, t_off = run_arm(seed_root, budget, seed, prune=False)
        on, t_on = run_arm(seed_root, budget, seed, prune=True)
        rows.append((seed, off.best.n_hard, off.best.n_soft, off.best.fitness,
                     off.n_topologies, t_off,
                     on.best.n_hard, on.best.n_soft, on.best.fitness,
                     on.n_topologies, t_on))
        print(f"seed {seed}: off hard={off.best.n_hard} soft={off.best.n_soft} "
              f"fit={off.best.fitness:.4g} topo={off.n_topologies} {t_off:.1f}s | "
              f"on  hard={on.best.n_hard} soft={on.best.n_soft} "
              f"fit={on.best.fitness:.4g} topo={on.n_topologies} {t_on:.1f}s",
              flush=True)

    n = len(rows)
    mean = lambda idx: sum(r[idx] for r in rows) / n
    print()
    print(f"budget={budget} n_seeds={n_seeds} programme={PROGRAMME_DIR}")
    print(f"OFF: mean hard={mean(1):.3f} soft={mean(2):.3f} fitness={mean(3):.6g} "
          f"topo={mean(4):.1f} wall={mean(5):.1f}s")
    print(f"ON : mean hard={mean(6):.3f} soft={mean(7):.3f} fitness={mean(8):.6g} "
          f"topo={mean(9):.1f} wall={mean(10):.1f}s")


if __name__ == "__main__":
    main()

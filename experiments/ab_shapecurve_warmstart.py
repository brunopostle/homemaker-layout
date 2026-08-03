"""A/B: does shapecurve-DP NM warm-start beat today's cold/proportion-aware
start on wall-clock/evals-to-fail-count, on the real ``driver.search`` loop
(homemaker-py-6xh, DESIGN.md §37.4)?

Scoped to the DP's validated envelope (DESIGN.md §37.2): single storey, no
leaf_sharing/superpose/max_share/multi_use. ``examples/harbor-house-l0`` is
the single-storey de-risk variant of harbor-house built for exactly this
purpose (storey_minimum=1) -- the full multi-storey ``examples/harbor-house``
is out of scope until the multi-storey DP follow-up lands.

Metric: mean (n_hard, n_soft, fitness) of ``driver.search``'s best individual
at a FIXED budget, across several seeds -- same format as §37.1's tiered-
comparator A/B table, not an evals-to-zero race (harbor-house-l0's small
programme does not reliably reach 0 hard fails within a script-scale budget
across all seeds, so a fixed-budget comparison is the fair, reproducible one).

Usage: python experiments/ab_shapecurve_warmstart.py [budget] [n_seeds]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from homemaker_layout import dom, driver

PROGRAMME_DIR = Path(__file__).parent.parent / "examples" / "harbor-house-l0"


def run_arm(seed_root: dom.Node, budget: int, seed: int, warmstart: bool):
    t0 = time.perf_counter()
    r = driver.search(
        seed_root, PROGRAMME_DIR, budget=budget, pop_size=8, child_budget=80,
        seed_budget=200, seed=seed, leaf_sharing=False,
        shapecurve_warmstart=warmstart,
    )
    elapsed = time.perf_counter() - t0
    return r, elapsed


def main() -> None:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    n_seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 8

    seed_root = dom.load(str(PROGRAMME_DIR / "init.dom"))

    rows = []
    for seed in range(n_seeds):
        off, t_off = run_arm(seed_root, budget, seed, warmstart=False)
        on, t_on = run_arm(seed_root, budget, seed, warmstart=True)
        rows.append((seed, off.best.n_hard, off.best.n_soft, off.best.fitness, t_off,
                     on.best.n_hard, on.best.n_soft, on.best.fitness, t_on))
        print(f"seed {seed}: off hard={off.best.n_hard} soft={off.best.n_soft} "
              f"fit={off.best.fitness:.4g} {t_off:.1f}s | "
              f"on  hard={on.best.n_hard} soft={on.best.n_soft} "
              f"fit={on.best.fitness:.4g} {t_on:.1f}s", flush=True)

    n = len(rows)
    mean = lambda idx: sum(r[idx] for r in rows) / n
    print()
    print(f"budget={budget} n_seeds={n_seeds} programme={PROGRAMME_DIR}")
    print(f"OFF: mean hard={mean(1):.3f} soft={mean(2):.3f} fitness={mean(3):.6g} "
          f"wall={mean(4):.1f}s")
    print(f"ON : mean hard={mean(5):.3f} soft={mean(6):.3f} fitness={mean(7):.6g} "
          f"wall={mean(8):.1f}s")


if __name__ == "__main__":
    main()

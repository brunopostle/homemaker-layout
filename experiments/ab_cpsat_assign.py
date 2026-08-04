"""A/B: does CP-SAT exact room-code labelling beat today's greedy/beam
heuristic seeder on the real ``driver.search`` loop (homemaker-py-2g7.5,
DESIGN.md §37.7)?

Three arms per programme/seed:
  - baseline: assign_solver="greedy" (today's default)
  - cpsat:    assign_solver="cpsat" (seeder only, item (a))
  - reassign: assign_solver="cpsat" + enable_reassign=True (adds item (b),
    the periodic in-search re-labelling operator)

Metric: mean (n_hard, n_soft, fitness) of ``driver.search``'s best individual
at a FIXED budget across several seeds, same format as the shapecurve A/Bs
(``experiments/ab_shapecurve_warmstart.py``) -- plus a count of how many
runs the ``reassign`` operator actually fired+was-accepted in, per the
bead's acceptance criterion.

Usage: python experiments/ab_cpsat_assign.py [budget] [n_seeds] [programme]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from homemaker_layout import dom, driver

EXAMPLES = Path(__file__).parent.parent / "examples"
ARMS = {
    "greedy":   {"assign_solver": "greedy", "enable_reassign": False},
    "cpsat":    {"assign_solver": "cpsat", "enable_reassign": False},
    "reassign": {"assign_solver": "cpsat", "enable_reassign": True},
}


def run_arm(seed_root: dom.Node, programme_dir: Path, budget: int, seed: int,
           arm_kw: dict):
    t0 = time.perf_counter()
    r = driver.search(
        seed_root, programme_dir, budget=budget, pop_size=8, child_budget=80,
        seed_budget=200, seed=seed, **arm_kw,
    )
    elapsed = time.perf_counter() - t0
    # "fired and accepted": a reassign-descended child survived tournament
    # replacement into the FINAL population (lineage is per-generation, not
    # cumulative -- see Individual/driver._evaluate -- so this only counts
    # children born directly from a non-noop reassign, not their descendants).
    fired = sum(1 for ind in r.population
               if ind.lineage.startswith("reassign") and "noop" not in ind.lineage)
    return r, elapsed, fired


def main() -> None:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    n_seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    programme_name = sys.argv[3] if len(sys.argv) > 3 else "harbor-house"

    programme_dir = EXAMPLES / programme_name
    seed_root = dom.load(str(programme_dir / "init.dom"))

    rows: dict[str, list[tuple]] = {name: [] for name in ARMS}
    for seed in range(n_seeds):
        line = [f"seed {seed}:"]
        for name, kw in ARMS.items():
            r, elapsed, fired = run_arm(seed_root, programme_dir, budget, seed, kw)
            rows[name].append((r.best.n_hard, r.best.n_soft, r.best.fitness, elapsed, fired))
            line.append(f"{name} hard={r.best.n_hard} soft={r.best.n_soft} "
                       f"fit={r.best.fitness:.4g} {elapsed:.1f}s"
                       + (f" reassign_fired={fired}" if name == "reassign" else ""))
        print(" | ".join(line), flush=True)

    print()
    print(f"budget={budget} n_seeds={n_seeds} programme={programme_dir.name}")
    def mean(data: list[tuple], idx: int) -> float:
        return sum(d[idx] for d in data) / len(data)

    for name, data in rows.items():
        extra = f" mean_reassign_fired={mean(data, 4):.1f}" if name == "reassign" else ""
        print(f"{name:9s}: mean hard={mean(data, 0):.3f} soft={mean(data, 1):.3f} "
              f"fitness={mean(data, 2):.6g} wall={mean(data, 3):.1f}s{extra}")


if __name__ == "__main__":
    main()

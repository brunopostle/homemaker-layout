#!/usr/bin/env python3
"""Hard/soft fail tiering A/B (homemaker-py-2g7.3, DESIGN.md §37).

Acceptance criteria: "tiered comparator behind a flag with A/B on harbor+maple
(3 seeds, 20k evals): hard-fail count at budget strictly better or equal on
mean, no §4.9 regression; report shows hard/soft split."

Compares the outer comparator (-n_fails, fitness) [use_tiers=False, the
existing default] against (-n_hard, -n_soft, fitness) [use_tiers=True] on
harbor-house and maple-court, 3 seeds each, budget=20000 native evals/run.
Reports mean hard/soft/total fail counts per config and the per-seed deltas.

Usage:
  URB_NO_OCCLUSION=1 python3 experiments/tier_ab_2g7_3.py \
      [budget] [n_seeds] [workers] [out_dir]

Defaults: budget=20000, n_seeds=3, workers=4, scratch/tier_ab_2g7_3.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import dom, driver  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ["harbor-house", "maple-court"]


def _run(programme_dir: Path, seed: int, budget: int, workers: int, use_tiers: bool):
    seed_root = dom.load(str(programme_dir / "init.dom"))
    t0 = time.perf_counter()
    r = driver.search(
        seed_root, programme_dir, budget=budget, pop_size=16, child_budget=80,
        seed_budget=300, p_crossover=0.2, seed=seed, n_workers=workers,
        leaf_sharing=True, use_tiers=use_tiers,
    )
    dt = time.perf_counter() - t0
    return {
        "n_fails": r.best.n_fails, "n_hard": r.best.n_hard, "n_soft": r.best.n_soft,
        "fitness": r.best.fitness, "n_evals": r.n_evals, "wall_s": dt,
    }


def main() -> int:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    n_seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    out_dir = Path(sys.argv[4]) if len(sys.argv) > 4 else (REPO / "scratch" / "tier_ab_2g7_3")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"budget   : {budget}")
    print(f"n_seeds  : {n_seeds}")
    print(f"workers  : {workers}")
    print(f"programmes: {PROGRAMMES}")
    print(flush=True)

    t_start = time.perf_counter()
    results: dict[str, dict[str, list[dict]]] = {}

    for prog_name in PROGRAMMES:
        programme_dir = REPO / "examples" / prog_name
        results[prog_name] = {"flat": [], "tiered": []}
        print(f"=== {prog_name} ===", flush=True)
        for seed in range(n_seeds):
            for label, use_tiers in (("flat", False), ("tiered", True)):
                res = _run(programme_dir, seed, budget, workers, use_tiers)
                results[prog_name][label].append(res)
                print(f"  seed {seed} {label:6s}: hard={res['n_hard']} "
                      f"soft={res['n_soft']} total={res['n_fails']} "
                      f"fitness={res['fitness']:.6g} evals={res['n_evals']} "
                      f"({res['wall_s']:.0f}s)", flush=True)

    print()
    print("=" * 72)
    print("SUMMARY (mean over seeds)")
    print("=" * 72)
    overall_ok = True
    for prog_name in PROGRAMMES:
        for label in ("flat", "tiered"):
            rows = results[prog_name][label]
            mh = sum(r["n_hard"] for r in rows) / len(rows)
            ms = sum(r["n_soft"] for r in rows) / len(rows)
            mt = sum(r["n_fails"] for r in rows) / len(rows)
            print(f"  {prog_name:14s} {label:6s}: hard={mh:.2f} soft={ms:.2f} "
                  f"total={mt:.2f}")
        flat_hard = sum(r["n_hard"] for r in results[prog_name]["flat"]) / n_seeds
        tiered_hard = sum(r["n_hard"] for r in results[prog_name]["tiered"]) / n_seeds
        ok = tiered_hard <= flat_hard
        overall_ok = overall_ok and ok
        print(f"  {prog_name:14s} hard-fail mean: flat={flat_hard:.2f} "
              f"tiered={tiered_hard:.2f}  -> {'PASS' if ok else 'FAIL'}")
        print()

    print(f"ACCEPTANCE (hard-fail mean strictly better-or-equal, both "
          f"programmes): {'PASS' if overall_ok else 'FAIL'}")
    print(f"wall: {time.perf_counter() - t_start:.0f}s")
    print("=" * 72, flush=True)
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())

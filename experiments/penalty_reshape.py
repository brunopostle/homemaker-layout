#!/usr/bin/env python3
"""Penalty-reshaping validation: lexicographic outer search (homemaker-py-yg5).

DESIGN.md §4.8, §5.4, §7 Phase 4, §8.5.

Two measurements:

1. INNER-LOOP PROTECTION: run nm_search at budget 80 on corpus files × seeds.
   Asserts x0_n_fails >= result.n_fails for every run (cliff NEVER allows a new
   failure to enter).  The inner loop code is unchanged; this confirms the 0.5^n
   cliff still guards it.

2. OUTER-SEARCH QUALITY: run driver.search at a modest budget with lex=True
   (lexicographic: fewer fails first, then score) vs lex=False (old scalar
   fitness comparison) across several rng seeds.  Reports: mean evals to first
   improvement, mean best score, mean best n_fails at budget.

Runs under URB_NO_OCCLUSION=1.

Usage:
  python3 experiments/penalty_reshape.py [outer_budget] [out.json]
  (defaults: outer_budget 2000, experiments/penalty_reshape.json)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import dom, driver, innerloop  # noqa: E402

os.environ.setdefault("URB_NO_OCCLUSION", "1")

EX = Path("/home/bruno/src/urb/examples/programme-house")

# Files used for inner-loop protection test (same as bakeoff_native.py baseline)
IL_FILES = (
    "2f45907abd9accac2a124d311732f749.dom",
    "candidate-002.dom",
    "c964435454c459f86c3ed9a5a7621132.dom",
)
IL_SEEDS = (0, 1, 2)
IL_BUDGET = 80

# Seed file for outer-search comparison — 2f45907 starts with 2 fails after
# inner loop (inner loop achieves 2 fails at budget 80 on this file), so the
# initial population mixes 2-fail and 3-fail designs and the cross-tier
# comparison between lex and scalar is exercised.
OUTER_SEED_FILE = EX / "2f45907abd9accac2a124d311732f749.dom"
OUTER_SEEDS = (0, 1, 2)
OUTER_POP = 8
OUTER_CHILD_BUDGET = 80


# ---------------------------------------------------------------------------
# Part 1 — inner-loop protection
# ---------------------------------------------------------------------------

def run_inner_loop_protection(budget: int = IL_BUDGET) -> list[dict]:
    print("\n=== Part 1: inner-loop protection ===")
    print(f"{'file':24s} {'seed':>4s} {'x0_f':>6s} {'fin_f':>6s} {'x0_fit':>10s} "
          f"{'fin_fit':>10s} {'ok':>4s}")
    results = []
    for fname in IL_FILES:
        root_orig = dom.load(str(EX / fname))
        for seed in IL_SEEDS:
            root = dom.load(str(EX / fname))
            with innerloop.NativeEvaluator(root, EX) as ev:
                x0 = ev.x_current
                r = innerloop.nm_search(ev, x0, budget=budget, seed=seed)
            ok = r.n_fails <= r.x0_n_fails
            print(f"{fname[:24]:24s} {seed:4d} {r.x0_n_fails:6d} {r.n_fails:6d} "
                  f"{r.x0_fitness:10.5f} {r.fitness:10.5f} {'OK' if ok else 'FAIL':>4s}")
            results.append({
                "file": fname,
                "seed": seed,
                "x0_n_fails": r.x0_n_fails,
                "final_n_fails": r.n_fails,
                "x0_fitness": r.x0_fitness,
                "final_fitness": r.fitness,
                "regression": not ok,
            })
    n_reg = sum(r["regression"] for r in results)
    print(f"\nFail regressions: {n_reg}/{len(results)} "
          f"({'PASS — inner loop protected' if n_reg == 0 else 'FAIL — cliff broken'})")
    return results


# ---------------------------------------------------------------------------
# Part 2 — outer-search quality comparison
# ---------------------------------------------------------------------------

def run_outer_search(budget: int, use_lex: bool, seed: int) -> dict:
    root = dom.load(str(OUTER_SEED_FILE))
    t0 = time.perf_counter()
    r = driver.search(
        root,
        EX,
        budget=budget,
        pop_size=OUTER_POP,
        child_budget=OUTER_CHILD_BUDGET,
        seed=seed,
        use_lex=use_lex,
    )
    wall = time.perf_counter() - t0
    first_improvement_evals = r.history[1][0] if len(r.history) > 1 else None
    return {
        "scheme": "lex" if use_lex else "scalar",
        "seed": seed,
        "budget": budget,
        "best_fitness": r.best.fitness if r.best else None,
        "best_n_fails": r.best.n_fails if r.best else None,
        "n_evals": r.n_evals,
        "n_topologies": r.n_topologies,
        "n_improvements": len(r.history),
        "first_improvement_evals": first_improvement_evals,
        "wall_s": wall,
        "history": [(ev, fit, lin) for ev, fit, lin in r.history],
        "population": [(p.fitness, p.n_fails) for p in r.population],
    }


def run_outer_comparison(budget: int) -> list[dict]:
    print(f"\n=== Part 2: outer-search comparison (budget {budget}) ===")
    print(f"{'scheme':8s} {'seed':>4s} {'best_fit':>12s} {'n_fails':>7s} "
          f"{'topologies':>10s} {'improvements':>12s} {'1st_improv':>10s}")
    results = []
    for use_lex in (True, False):
        for seed in OUTER_SEEDS:
            r = run_outer_search(budget, use_lex, seed)
            results.append(r)
            first = r["first_improvement_evals"]
            print(f"{'lex' if use_lex else 'scalar':8s} {seed:4d} "
                  f"{r['best_fitness']:12.6g} {r['best_n_fails']:7d} "
                  f"{r['n_topologies']:10d} {r['n_improvements']:12d} "
                  f"{str(first):>10s}")
    print()
    for scheme in ("lex", "scalar"):
        rs = [r for r in results if r["scheme"] == scheme]
        mean_fit = np.mean([r["best_fitness"] for r in rs])
        mean_fails = np.mean([r["best_n_fails"] for r in rs])
        mean_topo = np.mean([r["n_topologies"] for r in rs])
        first_evs = [r["first_improvement_evals"] for r in rs if r["first_improvement_evals"]]
        mean_first = np.mean(first_evs) if first_evs else float("nan")
        print(f"{scheme:8s}  mean_fit={mean_fit:.5g}  mean_fails={mean_fails:.2f}  "
              f"mean_topologies={mean_topo:.0f}  mean_first_improvement={mean_first:.0f}")
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    outer_budget = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else (
        Path(__file__).parent / "penalty_reshape.json")

    il_results = run_inner_loop_protection()
    outer_results = run_outer_comparison(outer_budget)

    out = {
        "inner_loop_protection": il_results,
        "outer_search": outer_results,
    }
    out_path.write_text(json.dumps(out, indent=1))
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

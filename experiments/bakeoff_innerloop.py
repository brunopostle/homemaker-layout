#!/usr/bin/env python3
"""Inner-loop optimiser bake-off at equal oracle budgets (homemaker-py-d0s).

DESIGN.md §7 Phase 1(b), §8.3. DOF is only ≈ rooms−1 (6–7 on the corpus), so
the question is fitness gained per oracle evaluation, not asymptotic power.
Candidates:

  nm          multi-start Nelder-Mead (scipy) — the §4.5 diagnostic optimiser.
              Inherently sequential: ONE dom per oracle call, so the Perl
              startup never amortises (§4.6).
  cma         multi-phase CMA-ES (innerloop.cma_search), one batched oracle
              call per generation.
  compass     single-start batched compass search with pattern moves + random
              augmentation (innerloop.compass_search).
  compass-ms  multi-start compass: budget split across restarts (x0 first,
              then random starts), global best kept.

Protocol: cold start from each file's equal-offset projection (x_current),
one run per (method, file, seed), best-so-far recorded after every oracle
call. Fitness-at-budget-B is read off the trace (evals ≤ B), so methods are
compared at exactly equal budgets regardless of batch granularity; checkpoint
budgets bracket the driver's real operating points (child_budget=80 warm,
seed_budget=200 cold). Wall-clock and oracle-invocation counts are recorded
per run.

Runs under URB_NO_OCCLUSION=1 (set by this script — the gp2 re-baseline flag;
all benchmarks must use it).

Usage: python3 experiments/bakeoff_innerloop.py [budget] [out.json]
       (defaults: budget 200, experiments/bakeoff_innerloop.json)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker import dom, innerloop, oracle  # noqa: E402

URB = Path("/home/bruno/src/urb")
EX = URB / "examples" / "programme-house"

FILES = (
    "2f45907abd9accac2a124d311732f749.dom",
    "candidate-002.dom",
    "c964435454c459f86c3ed9a5a7621132.dom",
)
SEEDS = (0, 1, 2)
CHECKPOINTS = (40, 80, 120, 200)


class TracingEvaluator(innerloop.OracleEvaluator):
    """Records (cumulative evals, batch-best fitness) after every oracle call."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.trace: list[tuple[int, float]] = []

    def evaluate(self, xs):
        scores = super().evaluate(xs)
        self.trace.append((self.n_evals, max(s.fitness for s in scores)))
        return scores

    def best_at(self, budget: int) -> float:
        vals = [f for n, f in self.trace if n <= budget]
        return max(vals) if vals else float("nan")


class _BudgetExhausted(Exception):
    pass


def nm_search(ev, x0, budget=200, seed=0):
    """Multi-start Nelder-Mead: x0 first, random restarts until the budget is
    spent. Sequential — every evaluation is its own oracle invocation."""
    from scipy.optimize import minimize

    rng = np.random.default_rng(seed)
    n = len(x0)
    x = np.clip(np.asarray(x0, dtype=float), innerloop._EPS, 1 - innerloop._EPS)
    s = ev.evaluate([x])[0]
    best = innerloop.Result(
        x=x.copy(), fitness=s.fitness, n_fails=s.n_fails, fail_lines=s.fail_lines,
        x0_fitness=s.fitness, x0_n_fails=s.n_fails, n_evals=0, n_oracle_calls=0,
    )

    def f(xi):
        if ev.n_evals >= budget:
            raise _BudgetExhausted
        sc = ev.evaluate([np.asarray(xi, dtype=float)])[0]
        if sc.fitness > best.fitness:
            best.x = np.asarray(xi, dtype=float).copy()
            best.fitness = sc.fitness
            best.n_fails = sc.n_fails
            best.fail_lines = sc.fail_lines
        return -sc.fitness

    start = x.copy()
    while ev.n_evals < budget:
        try:
            minimize(
                f, start, method="Nelder-Mead",
                bounds=[(innerloop._EPS, 1 - innerloop._EPS)] * n,
                options={"maxfev": budget - ev.n_evals, "xatol": 1e-3, "fatol": 1e-10},
            )
        except _BudgetExhausted:
            break
        start = rng.uniform(0.1, 0.9, n)  # restart

    best.n_evals = ev.n_evals
    best.n_oracle_calls = ev.n_oracle_calls
    return best


def compass_ms_search(ev, x0, budget=200, seed=0, n_starts=3):
    """Multi-start compass: budget split evenly; first start is x0, the rest
    random. compass_search counts against ev.n_evals, so phase budgets are
    cumulative caps."""
    rng = np.random.default_rng(seed)
    n = len(x0)
    best = None
    for phase in range(n_starts):
        phase_end = ev.n_evals + (budget - ev.n_evals) // (n_starts - phase)
        start = np.asarray(x0, dtype=float) if phase == 0 else rng.uniform(0.1, 0.9, n)
        r = innerloop.compass_search(ev, start, budget=phase_end, seed=seed + phase)
        if best is None or r.fitness > best.fitness:
            keep_x0 = best.x0_fitness if best is not None else r.x0_fitness
            keep_x0f = best.x0_n_fails if best is not None else r.x0_n_fails
            best = r
            best.x0_fitness, best.x0_n_fails = keep_x0, keep_x0f
        if ev.n_evals >= budget:
            break
    best.n_evals = ev.n_evals
    best.n_oracle_calls = ev.n_oracle_calls
    return best


METHODS = {
    "nm": nm_search,
    "cma": innerloop.cma_search,
    "compass": innerloop.compass_search,
    "compass-ms": compass_ms_search,
}


def main() -> int:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else (
        Path(__file__).parent / "bakeoff_innerloop.json")
    os.environ["URB_NO_OCCLUSION"] = "1"
    checkpoints = [c for c in CHECKPOINTS if c <= budget] or [budget]
    if checkpoints[-1] != budget:
        checkpoints.append(budget)

    # Baselines: the UNMODIFIED originals (gains measured from there, not from
    # the equal-offset projection — accept_innerloop.py convention).
    orig: dict[str, oracle.Score] = {}
    with tempfile.TemporaryDirectory(prefix="bakeoff_orig_") as tmp:
        shutil.copy(EX / "patterns.config", tmp)
        for name in FILES:
            orig[name] = oracle.score(shutil.copy(EX / name, tmp), URB)

    runs = []
    for name in FILES:
        for method in METHODS:
            for seed in SEEDS:
                root = dom.load(str(EX / name))
                with TracingEvaluator(root, EX, URB) as ev:
                    x0 = ev.x_current
                    t0 = time.perf_counter()
                    r = METHODS[method](ev, x0, budget=budget, seed=seed)
                    dt = time.perf_counter() - t0
                    run = {
                        "file": name, "method": method, "seed": seed,
                        "dof": len(x0),
                        "orig_fitness": orig[name].fitness,
                        "orig_n_fails": orig[name].n_fails,
                        "x0_fitness": r.x0_fitness, "x0_n_fails": r.x0_n_fails,
                        "best_at": {str(c): ev.best_at(c) for c in checkpoints},
                        "final_fitness": r.fitness, "final_n_fails": r.n_fails,
                        "n_evals": ev.n_evals, "n_oracle_calls": ev.n_oracle_calls,
                        "wall_s": dt,
                    }
                runs.append(run)
                gains = "  ".join(
                    f"@{c}:x{run['best_at'][str(c)] / orig[name].fitness:.2f}"
                    for c in checkpoints)
                print(
                    f"{name[:12]:12s} {method:10s} seed={seed}  {gains}  "
                    f"fails {orig[name].n_fails}->{r.n_fails}  "
                    f"{ev.n_evals}ev/{ev.n_oracle_calls}calls  {dt:.0f}s",
                    flush=True,
                )

    out_path.write_text(json.dumps(
        {"budget": budget, "checkpoints": checkpoints, "runs": runs}, indent=1))
    print(f"\nwrote {out_path}")

    # Summary: mean gain over original at each checkpoint, mean s/eval.
    print(f"\n{'method':10s} " + "".join(f"{'x@' + str(c):>8s}" for c in checkpoints)
          + f"{'s/eval':>8s}{'calls':>7s}{'fails+':>7s}")
    for method in METHODS:
        rs = [r for r in runs if r["method"] == method]
        cols = ""
        for c in checkpoints:
            g = np.mean([r["best_at"][str(c)] / r["orig_fitness"] for r in rs])
            cols += f"{g:8.2f}"
        spe = np.mean([r["wall_s"] / r["n_evals"] for r in rs])
        calls = np.mean([r["n_oracle_calls"] for r in rs])
        newf = sum(r["final_n_fails"] > r["orig_n_fails"] for r in rs)
        print(f"{method:10s} {cols}{spe:8.2f}{calls:7.0f}{newf:7d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

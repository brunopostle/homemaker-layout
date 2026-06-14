#!/usr/bin/env python3
"""Inner-loop bake-off on harbor-house designs (homemaker-py-d6d).

Extends bakeoff_native.py to harbor-house, which has 3–40 DOF vs programme-
house's 6–7.  Tests whether NM's early-budget advantage holds as DOF grows.
Files are grouped by DOF to show the scaling behaviour clearly.

Usage: python3 experiments/bakeoff_harbor.py [budget] [out.json]
       (defaults: budget 200, experiments/bakeoff_harbor.json)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import dom, fitness as fit_mod, innerloop, solver  # noqa: E402

EX = Path("/home/bruno/src/urb/examples/harbor-house")

# All files with DOF >= 3, sorted by DOF ascending
FILES = (
    "43a539866a2b63ff77c8fa11f92e133c.dom",   #  3 DOF
    "59a65b704b461146e8e2efaec9013e39.dom",   #  5 DOF
    "ec1f082320cbdbb2c5b24e29dbd4e0d0.dom",   # 11 DOF
    "448d535590f29d65a0469fb4ecbf4b56.dom",   # 14 DOF
    "0f931851fa0fd5fec70db5ae2899f10a.dom",   # 23 DOF
    "c07a3c3ccaccf580227fb6acfef8b263.dom",   # 35 DOF
    "dfa595104a9ac8a903db309697679455.dom",   # 39 DOF
    "2b51b0402ee38c150716673894d8f5c0.dom",   # 40 DOF
    "71d93882d8a520dc6c4e6fa1bcaea33a.dom",   # 40 DOF
)
SEEDS = (0, 1, 2)
CHECKPOINTS = (40, 80, 120, 200)


class NativeTracingEvaluator(innerloop.NativeEvaluator):
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
        start = rng.uniform(0.1, 0.9, n)

    best.n_evals = ev.n_evals
    best.n_oracle_calls = ev.n_oracle_calls
    return best


def compass_ms_search(ev, x0, budget=200, seed=0, n_starts=3):
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


def native_baseline(path: Path) -> innerloop._NativeScore:
    root = dom.load(str(path))
    conf, cost = fit_mod.load_config(EX)
    fit = fit_mod.Fitness(conf, cost)
    score, fails = fit.score_with_fails(root)
    return innerloop._NativeScore(fitness=score, fail_lines=tuple(fails))


def dof_of(path: Path) -> int:
    root = dom.load(str(path))
    return len(solver.free_branches(root))


def main() -> int:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else (
        Path(__file__).parent / "bakeoff_harbor.json")
    os.environ["URB_NO_OCCLUSION"] = "1"
    checkpoints = [c for c in CHECKPOINTS if c <= budget] or [budget]
    if checkpoints[-1] != budget:
        checkpoints.append(budget)

    file_dof = {name: dof_of(EX / name) for name in FILES}
    orig = {name: native_baseline(EX / name) for name in FILES}

    runs = []
    for name in FILES:
        dof = file_dof[name]
        for method in METHODS:
            for seed in SEEDS:
                root = dom.load(str(EX / name))
                ev = NativeTracingEvaluator(root, EX)
                x0 = ev.x_current
                t0 = time.perf_counter()
                r = METHODS[method](ev, x0, budget=budget, seed=seed)
                dt = time.perf_counter() - t0
                run = {
                    "file": name, "method": method, "seed": seed,
                    "dof": dof,
                    "orig_fitness": orig[name].fitness,
                    "orig_n_fails": orig[name].n_fails,
                    "x0_fitness": r.x0_fitness, "x0_n_fails": r.x0_n_fails,
                    "best_at": {str(c): ev.best_at(c) for c in checkpoints},
                    "final_fitness": r.fitness, "final_n_fails": r.n_fails,
                    "n_evals": ev.n_evals,
                    "wall_s": dt,
                }
                runs.append(run)
                gains = "  ".join(
                    f"@{c}:x{run['best_at'][str(c)] / orig[name].fitness:.2f}"
                    for c in checkpoints)
                print(
                    f"DOF={dof:2d}  {method:10s}  seed={seed}  {gains}  "
                    f"fails {orig[name].n_fails}->{r.n_fails}  {ev.n_evals}ev  {dt:.1f}s",
                    flush=True,
                )

    out_path.write_text(json.dumps(
        {"budget": budget, "checkpoints": checkpoints, "runs": runs}, indent=1))
    print(f"\nwrote {out_path}")

    # Summary by DOF band
    bands = [(1, 10, "small (≤10)"), (11, 20, "med (11-20)"), (21, 50, "large (>20)")]
    for lo, hi, label in bands:
        band_runs = [r for r in runs if lo <= r["dof"] <= hi]
        if not band_runs:
            continue
        print(f"\n--- {label} ---")
        print(f"{'method':10s} " + "".join(f"{'x@' + str(c):>8s}" for c in checkpoints)
              + f"  s/eval  fails+  n")
        for method in METHODS:
            rs = [r for r in band_runs if r["method"] == method]
            if not rs:
                continue
            cols = ""
            for c in checkpoints:
                g = np.mean([r["best_at"][str(c)] / r["orig_fitness"] for r in rs])
                cols += f"{g:8.3f}"
            spe = np.mean([r["wall_s"] / max(r["n_evals"], 1) for r in rs])
            newf = sum(r["final_n_fails"] > r["orig_n_fails"] for r in rs)
            print(f"{method:10s} {cols}  {spe:.4f}  {newf:5d}  {len(rs)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

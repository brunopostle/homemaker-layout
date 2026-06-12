#!/usr/bin/env python3
"""Phase-2 gate: memetic loop vs urb-evolve at equal oracle-eval budgets
(homemaker-py-way).

Protocol: 3 seed designs x 2000-evaluation runs; the 1000-eval tier is read
from each run's own best-so-far log (no extra oracle time). urb-evolve runs
at two population sizes (its default 128, which only allows ~16 generations
at this budget, and 16, which allows ~130) and gets credit for its better
one. urb-evolve counts evaluations via the MAX_EVALS patch; the memetic
driver accounts natively. Both run under URB_NO_OCCLUSION=1 with the same
patterns.config; every final design is re-scored through urb-fitness.pl as
the common deterministic yardstick.

  URB_NO_OCCLUSION=1 python3 experiments/benchmark_vs_urbevolve.py [budget]
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker import oracle  # noqa: E402

URB = Path("/home/bruno/src/urb")
EX = URB / "examples" / "programme-house"
HERE = Path(__file__).resolve().parent
WORK = HERE.parent / "scratch" / "benchmark"

SEEDS = ["init.dom", "c964435454c459f86c3ed9a5a7621132.dom",
         "2f45907abd9accac2a124d311732f749.dom"]
CHECKPOINT_FRACTION = 0.5


def run_homemaker(seed: str, budget: int, cell: Path) -> dict:
    out = cell / "best.dom"
    proc = subprocess.run(
        [sys.executable, str(HERE / "run_search.py"), str(budget), "0",
         str(EX / seed), str(out)],
        capture_output=True, text=True, env={**os.environ, "URB_NO_OCCLUSION": "1"},
    )
    (cell / "run.log").write_text(proc.stdout + proc.stderr)
    series = [(int(m[1]), float(m[2])) for m in
              re.finditer(r"\[\s*(\d+) evals\] best ([\d.e-]+)", proc.stdout)]
    return {"series": series, "best_dom": out, "log_ok": proc.returncode == 0}


def run_urbevolve(seed: str, budget: int, pop: int, cell: Path) -> dict:
    shutil.copy(EX / "patterns.config", cell)
    shutil.copy(EX / seed, cell)
    proc = subprocess.run(
        ["perl", f"-I{URB}/lib", str(URB / "bin" / "urb-evolve.pl"), seed],
        cwd=cell, capture_output=True, text=True,
        env={**os.environ, "URB_NO_OCCLUSION": "1", "MAX_EVALS": str(budget),
             "MAX_POP": str(pop), "MAX_ITERATIONS": "100000"},
    )
    (cell / "run.log").write_text(proc.stderr)
    series = []
    evals = None
    for line in proc.stderr.splitlines():
        if m := re.search(r"Evals: (\d+)", line):
            evals = int(m[1])
        elif (m := re.search(r"Fitness: ([\d.e-]+)", line)) and evals is not None:
            series.append((evals, float(m[1])))
    out_hash = proc.stdout.strip().split()[-1] if proc.stdout.strip() else None
    best = cell / f"{out_hash}.dom" if out_hash else None
    return {"series": series, "best_dom": best,
            "log_ok": proc.returncode == 0 and best is not None and best.exists()}


def best_at(series: list[tuple[int, float]], budget: int) -> float:
    vals = [f for e, f in series if e <= budget]
    return max(vals) if vals else float("nan")


def main() -> int:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    checkpoint = int(budget * CHECKPOINT_FRACTION)
    if WORK.exists():
        shutil.rmtree(WORK)

    cells = []
    for seed in SEEDS:
        cells.append((seed, "memetic", run_homemaker, {}))
        cells.append((seed, "urb-evolve p16", run_urbevolve, {"pop": 16}))
        cells.append((seed, "urb-evolve p128", run_urbevolve, {"pop": 128}))

    def run_cell(args):
        seed, label, fn, kw = args
        cell = WORK / f"{seed.split('.')[0][:8]}_{label.replace(' ', '_')}"
        cell.mkdir(parents=True, exist_ok=True)
        print(f"start: {seed} / {label}", flush=True)
        res = fn(seed, budget, cell, **kw)
        print(f"done:  {seed} / {label} ({len(res['series'])} log points)", flush=True)
        return (seed, label), res

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = dict(pool.map(run_cell, cells))

    # common yardstick: re-score every final design through urb-fitness.pl
    for key, res in results.items():
        if res["best_dom"] and Path(res["best_dom"]).exists():
            s = oracle.score(res["best_dom"], URB)
            res["final"], res["fails"] = s.fitness, s.n_fails
        else:
            res["final"], res["fails"] = float("nan"), -1

    print(f"\n{'seed':10s} {'system':16s} {'best@' + str(checkpoint):>12s} "
          f"{'final@' + str(budget):>12s} {'fails':>6s}")
    verdicts = []
    for seed in SEEDS:
        rows = {label: results[(seed, label)] for label in
                ("memetic", "urb-evolve p16", "urb-evolve p128")}
        for label, res in rows.items():
            print(f"{seed[:10]:10s} {label:16s} {best_at(res['series'], checkpoint):12.6g} "
                  f"{res['final']:12.6g} {res['fails']:6d}")
        hm = rows["memetic"]["final"]
        urb = max(rows["urb-evolve p16"]["final"], rows["urb-evolve p128"]["final"])
        verdicts.append(hm > urb)
        print(f"{'':10s} -> memetic {'BEATS' if hm > urb else 'LOSES TO'} "
              f"urb-evolve ({hm:.6g} vs {urb:.6g})")
    print(f"\nGATE: memetic wins {sum(verdicts)}/{len(verdicts)} seeds "
          f"-> {'GO' if all(verdicts) else 'REVIEW'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

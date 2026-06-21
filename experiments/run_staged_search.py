#!/usr/bin/env python3
"""Staged per-floor topology search (homemaker-py-c4c.3, DESIGN.md §11.3).

Runs ``driver.search_staged`` (Stage 1: single-storey base over the level-0 room
set with a substrate-readiness ranking bonus; Stage 2: upper floors lifted as
deltas, base kept mutable at low probability) on a multi-storey programme. The
single-stage counterpart is ``run_search_scaled.py``; run both at the same budget
and seed for the §11.3 A/B.

Usage:
  URB_NO_OCCLUSION=1 python3 experiments/run_staged_search.py \
    [programme_dir] [budget] [rng_seed] [seed.dom] [out.dom]

Defaults: harbor-house, budget=20000, rng_seed=0, init.dom seed.
"""

from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import dom, driver, fitness  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
HARBOR = REPO / "examples" / "harbor-house"


def _native_score(root: dom.Node, programme_dir: Path) -> tuple[float, int]:
    import copy

    conf, cost = fitness.load_config(programme_dir)
    fit = fitness.Fitness(conf, cost)
    score, fails = fit.score_with_fails(copy.deepcopy(root))
    return score, len(fails)


def main() -> int:
    programme_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else HARBOR
    budget = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rng_seed = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    seed_file = Path(sys.argv[4]) if len(sys.argv) > 4 else (programme_dir / "init.dom")
    out = Path(sys.argv[5]) if len(sys.argv) > 5 else (
        REPO / "scratch" / "staged_best.dom"
    )

    if not seed_file.exists():
        print(f"ERROR: no seed .dom at {seed_file}", file=sys.stderr)
        return 1

    use_grade = os.environ.get("USE_GRADE") == "1"  # §11.4 graded objective A/B
    niche = os.environ.get("NICHE", "0") == "1"     # §11.5 structural niching A/B
    rp = os.environ.get("RESTART_PATIENCE")
    restart_patience = int(rp) if rp else None
    adj = os.environ.get("ADJ", "1") == "1"  # s44/ld5 adjacency-aware seeding A/B
    prop = os.environ.get("PROP", "1") == "1"  # leu.2 proportion-aware split sizing (default-on)
    reassoc = os.environ.get("REASSOC", "0") == "1"  # 9gp.2 M3 reassociate move A/B
    feas = os.environ.get("FEAS", "0") == "1"  # 9gp.1 shape-feasibility pre-filter A/B
    _ms = os.environ.get("MAXSHAPE")           # 9gp.1 prune threshold (shape-fail count)
    max_shape = int(_ms) if _ms else None
    circ_div = int(os.environ.get("CIRCDIV", "3"))  # c3g circ-per-room granularity knob

    print(f"programme : {programme_dir.name}")
    print(f"seed      : {seed_file.name}")
    print(f"budget    : {budget} native evals (staged)")
    print(f"rng seed  : {rng_seed}")
    print(f"use_grade : {use_grade}")
    print(f"niche     : {niche}")
    print(f"restart_p : {restart_patience}")
    print(f"adj_aware : {adj}")
    print(f"prop_aware: {prop}")
    print(f"reassoc   : {reassoc}")
    print(f"feas_filt : {feas} (max_shape={max_shape})")
    print(f"circ_div  : {circ_div}")
    print(flush=True)

    seed_root = dom.load(str(seed_file))
    t0 = time.perf_counter()

    r = driver.search_staged(
        seed_root,
        programme_dir,
        budget=budget,
        pop_size=16,
        child_budget=80,
        seed_budget=300,
        stage1_frac=0.4,
        base_p=0.15,
        p_crossover=0.2,
        seed=rng_seed,
        log=lambda m: print(m, flush=True),
        use_grade=use_grade,
        niche_by_signature=niche,
        restart_patience=restart_patience,
        seed_adjacency_aware=adj,
        seed_proportion_aware=prop,
        enable_reassociate=reassoc,
        feasibility_filter=feas,
        feasibility_max_shape_fails=max_shape,
        circ_divisor=circ_div,
    )

    elapsed = time.perf_counter() - t0
    print(f"\n--- done ---")
    print(f"elapsed   : {elapsed:.1f}s  ({r.n_evals / elapsed:.1f} evals/s)")
    print(f"evals     : {r.n_evals} across {r.n_topologies} topologies")
    print(f"best      : {r.best.fitness:.6g} ({r.best.n_fails} fails) via {r.best.lineage}")
    print("population: " + ", ".join(
        f"{p.fitness:.4g}/{p.n_fails}f" for p in r.population
    ))
    pop_distinct = len({p.sig for p in r.population})
    print(f"diversity : {r.n_distinct_signatures} distinct topologies seen, "
          f"{pop_distinct}/{len(r.population)} distinct in final population, "
          f"{r.n_restarts} restarts")

    if r.history:
        print("\nimprovement history:")
        for ev, fit_val, lin in r.history:
            print(f"  [{ev:6d}] {fit_val:.6g}  ({lin})")

    out.parent.mkdir(parents=True, exist_ok=True)
    dom.dump(r.best.root, str(out))

    rs, rf = _native_score(r.best.root, programme_dir)
    ok = math.isclose(rs, r.best.fitness, rel_tol=1e-9)
    print(f"\n{out.name} re-scored (native): {rs:.6g} ({rf} fails) "
          f"→ {'OK' if ok else 'MISMATCH'}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

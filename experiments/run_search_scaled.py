#!/usr/bin/env python3
"""Scaled topology search on native fitness (homemaker-py-ccw, Phase 3).

Runs driver.search at larger budget using the native Python fitness exclusively
— no Perl oracle, no wall-clock bottleneck from Perl startup.

This unlocks two things the Phase-2 oracle-bounded run could not do:
  1. Larger evaluation budgets on programme-house (beat Phase-2 best).
  2. Programmes too large for the oracle (e.g. harbor-house, 16 rooms).

Usage:
  URB_NO_OCCLUSION=1 python3 experiments/run_search_scaled.py [programme_dir] [budget] [rng_seed] [seed.dom] [out.dom]

Defaults: programme-house, budget=20000, rng_seed=0, best corpus seed.

Phase-2 reference bars (URB_NO_OCCLUSION=1, budget=2000, native fitness):
  c964435 seed → 7.65e-03 (2 fails)   beats urb-evolve p128 4.00e-03
  2f45907 seed → 2.13e-02 (2 fails)   beats urb-evolve p128 1.30e-02
"""

from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import dom, driver, fitness, innerloop  # noqa: E402

URB_EX = Path("/home/bruno/src/urb/examples")
PH_DIR = URB_EX / "programme-house"
PH_SEED = PH_DIR / "c964435454c459f86c3ed9a5a7621132.dom"


def _native_score(root: dom.Node, programme_dir: Path) -> tuple[float, int]:
    """Re-score a design with native fitness (no oracle dependency)."""
    import copy

    conf, cost = fitness.load_config(programme_dir)
    fit = fitness.Fitness(conf, cost)
    score, fails = fit.score_with_fails(copy.deepcopy(root))
    return score, len(fails)


def main() -> int:
    programme_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else PH_DIR
    budget = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rng_seed = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    seed_file = Path(sys.argv[4]) if len(sys.argv) > 4 else None
    out = Path(sys.argv[5]) if len(sys.argv) > 5 else (
        Path(__file__).resolve().parents[1] / "scratch" / "scaled_best.dom"
    )

    if seed_file is None:
        # pick the default seed for known programmes, else fall back to init.dom
        if programme_dir.name == "programme-house":
            seed_file = PH_SEED
        else:
            seed_file = programme_dir / "init.dom"
            if not seed_file.exists():
                candidates = sorted(programme_dir.glob("*.dom"))
                seed_file = candidates[0] if candidates else None
            if seed_file is None:
                print(f"ERROR: no .dom seed found in {programme_dir}", file=sys.stderr)
                return 1

    use_grade = os.environ.get("USE_GRADE") == "1"  # §11.4 graded objective A/B
    # §11.5 structural niching + restarts A/B. NICHE=0 falls back to the legacy
    # fitness-scalar dedup (the "before"); RESTART_PATIENCE=<evals> enables soft
    # restarts (default off).
    niche = os.environ.get("NICHE", "0") == "1"
    # 6zy: tournament size (selection pressure), default k=2 (legacy binary).
    tournament_k = int(os.environ.get("HOMEMAKER_TOURNAMENT_K", "2"))
    rp = os.environ.get("RESTART_PATIENCE")
    restart_patience = int(rp) if rp else None
    adj = os.environ.get("ADJ", "1") == "1"  # s44 adjacency-aware seeding
    prop = os.environ.get("PROP", "1") == "1"  # leu.2 proportion-aware split sizing (default-on)

    print(f"programme : {programme_dir.name}")
    print(f"seed      : {seed_file.name}")
    print(f"budget    : {budget} native evals")
    print(f"rng seed  : {rng_seed}")
    print(f"use_grade : {use_grade}")
    print(f"niche     : {niche}")
    print(f"tourn_k   : {tournament_k}")
    print(f"restart_p : {restart_patience}")
    print(f"adj_aware : {adj}")
    print(f"prop_aware: {prop}")
    print(flush=True)

    seed_root = dom.load(str(seed_file))
    t0 = time.perf_counter()

    r = driver.search(
        seed_root,
        programme_dir,
        budget=budget,
        pop_size=16,          # up from 8 — more diversity at scale
        child_budget=80,
        seed_budget=300,      # up from 200 — thorough seed optimisation
        p_crossover=0.2,
        seed=rng_seed,
        log=lambda m: print(m, flush=True),
        use_grade=use_grade,
        tournament_k=tournament_k,
        niche_by_signature=niche,
        restart_patience=restart_patience,
        seed_adjacency_aware=adj,
        seed_proportion_aware=prop,
        # urb_root not needed: use_native=True is the default
    )

    elapsed = time.perf_counter() - t0
    evals_per_sec = r.n_evals / elapsed

    print(f"\n--- done ---")
    print(f"elapsed   : {elapsed:.1f}s  ({evals_per_sec:.1f} evals/s)")
    print(f"evals     : {r.n_evals} across {r.n_topologies} topologies")
    print(f"best      : {r.best.fitness:.6g} ({r.best.n_fails} fails) via {r.best.lineage}")
    print("population: " + ", ".join(
        f"{p.fitness:.4g}/{p.n_fails}f" for p in r.population
    ))
    # §11.5 diversity: distinct topology signatures seen, current population
    # structural spread, and restart count.
    pop_distinct = len({p.sig for p in r.population})
    print(f"diversity : {r.n_distinct_signatures} distinct topologies seen, "
          f"{pop_distinct}/{len(r.population)} distinct in final population, "
          f"{r.n_restarts} restarts")
    if r.diversity_history:
        print("pop-distinct over time (evals, pop_distinct, cumulative): "
              + ", ".join(f"({e},{d},{c})" for e, d, c in r.diversity_history))

    if r.history:
        print("\nimprovement history:")
        for ev, fit_val, lin in r.history:
            print(f"  [{ev:6d}] {fit_val:.6g}  ({lin})")

    out.parent.mkdir(parents=True, exist_ok=True)
    dom.dump(r.best.root, str(out))

    # native re-score as ground truth (oracle retired in Phase 3)
    rs, rf = _native_score(r.best.root, programme_dir)
    ok = math.isclose(rs, r.best.fitness, rel_tol=1e-9)
    print(f"\n{out.name} re-scored (native): {rs:.6g} ({rf} fails) "
          f"→ {'OK' if ok else 'MISMATCH'}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

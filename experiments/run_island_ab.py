#!/usr/bin/env python3
"""Island-model A/B (homemaker-py-psk, DESIGN.md §14).

Tests the user-proposed lever: the Perl Urb workflow ran the search many times
and kept the best because runs settled into different local minima. The Python
tool is deterministic per --seed, so the analog is to run N independent seeds,
then PRIME a fresh population with those N converged elites and run a second,
crossover-heavy migration phase (an island model with synchronous migration).

Three numbers per programme (all leaf_sharing OFF, so the controls reproduce the
§12.2 baselines maple 136.0 / harbor 74.0):

  bestN@A   best-of-N over Phase A (N runs at B_A each). The FREE reference
            (these N runs happen anyway); the legitimate descendant of Urb's
            multi-run habit.
  island    Phase B migration result: a fresh population primed from the N
            Phase-A elites, evolved with high p_crossover. Total budget
            T = N*B_A + B_B.
  bestN@T   best-of-N over N independent runs at T/N each (the "N+ longer
            independent runs" control). Same TOTAL budget T as island. THE BAR:
            island must beat this to count.

Mechanistic instrument (the key diagnostic, §14): a child_probe over Phase B
counts how many crossover children ever beat max(parent fails) / min(parent
fails). If crossover children are never net-positive, the null is mechanistic
(area-matched splice across non-canonical encodings is disruptive, cf. 9gp),
not a budget shortfall.

Usage:
  URB_NO_OCCLUSION=1 python3 experiments/run_island_ab.py \
      [programme_dir] [N] [B_A] [B_B] [master_seed] [workers] [out_dir]

Defaults: harbor-house, N=5, B_A=1500, B_B=5000, master_seed=0, workers=4.
"""

from __future__ import annotations

import copy
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import dom, driver  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def _staged(seed_root, programme_dir, budget, seed, workers):
    return driver.search_staged(
        seed_root, programme_dir, budget=budget, pop_size=16,
        child_budget=80, seed_budget=300, stage1_frac=0.4, base_p=0.15,
        p_crossover=0.2, seed=seed, n_workers=workers, leaf_sharing=False,
    )


def main() -> int:
    programme_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        REPO / "examples" / "harbor-house")
    N = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    B_A = int(sys.argv[3]) if len(sys.argv) > 3 else 1500
    B_B = int(sys.argv[4]) if len(sys.argv) > 4 else 5000
    master_seed = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    workers = int(sys.argv[6]) if len(sys.argv) > 6 else 4
    out_dir = Path(sys.argv[7]) if len(sys.argv) > 7 else (REPO / "scratch" / "island_ab")
    out_dir.mkdir(parents=True, exist_ok=True)

    seed_file = programme_dir / "init.dom"
    if not seed_file.exists():
        print(f"ERROR: no seed .dom at {seed_file}", file=sys.stderr)
        return 1
    seed_root = dom.load(str(seed_file))

    print(f"programme   : {programme_dir.name}")
    print(f"N seeds     : {N}")
    print(f"B_A (phase A): {B_A}/seed requested")
    print(f"B_B (migrate): {B_B} requested")
    print(f"control      : {N} runs sized to island's ACTUAL total evals")
    print(f"master_seed  : {master_seed}   workers {workers}   leaf_sharing OFF")
    print(flush=True)

    t_start = time.perf_counter()

    # NB: staged search has a hard floor of ~pop*child_budget*2 evals (the
    # two bootstrap stages), so a requested per-seed budget below that overshoots.
    # We account for ACTUAL evals consumed (r.n_evals), never the request.
    # --- Phase A: N independent converged elites ---------------------------
    print("=== Phase A: N independent runs ===", flush=True)
    elites = []
    phaseA_fails = []
    evA = 0
    for i in range(N):
        s = master_seed * 1000 + i
        t0 = time.perf_counter()
        r = _staged(seed_root, programme_dir, B_A, s, workers)
        phaseA_fails.append(r.best.n_fails)
        evA += r.n_evals
        elites.append(copy.deepcopy(r.best.root))
        print(f"  seed {s}: {r.best.n_fails} fails ({r.best.fitness:.6g}), "
              f"{r.n_evals} evals, {time.perf_counter() - t0:.0f}s", flush=True)
    bestN_A = min(phaseA_fails)
    print(f"  -> bestN@A = {bestN_A} fails  (pool {sorted(phaseA_fails)}), "
          f"{evA} actual evals\n", flush=True)

    # --- Phase B: island migration ----------------------------------------
    print("=== Phase B: migration (prime pop from N elites, high crossover) ===",
          flush=True)
    counter = {"i": 0}

    def island_factory(rng):
        root = copy.deepcopy(elites[counter["i"] % len(elites)])
        counter["i"] += 1
        return root

    # Instrument crossover children: did the spliced child beat its parents?
    # The driver appends "|pf=a,b" (parent fail counts) to a crossover child's
    # lineage when child_probe is set; this survives the worker pickle round-trip.
    xstats = {"xover": 0, "beat_min": 0, "beat_max": 0, "best_drop": 0}

    def child_probe(ind):
        if ind.lineage.startswith("pruned/") or "|pf=" not in ind.lineage:
            return
        pa, pb = (int(x) for x in ind.lineage.split("|pf=")[1].split(","))
        xstats["xover"] += 1
        if ind.n_fails < min(pa, pb):
            xstats["beat_min"] += 1
        if ind.n_fails < max(pa, pb):
            xstats["beat_max"] += 1
        drop = max(pa, pb) - ind.n_fails
        if drop > xstats["best_drop"]:
            xstats["best_drop"] = drop

    t0 = time.perf_counter()
    r_island = driver.search(
        seed_root, programme_dir, budget=B_B, pop_size=N, child_budget=80,
        seed_budget=300, p_crossover=0.7, seed=master_seed, n_workers=workers,
        leaf_sharing=False, bootstrap=True, seed_factory=island_factory,
        child_probe=child_probe,
    )
    island_fails = r_island.best.n_fails
    evB = r_island.n_evals
    island_total_ev = evA + evB
    dom.dump(r_island.best.root, str(out_dir / f"{programme_dir.name}_island_s{master_seed}.dom"))
    print(f"  island = {island_fails} fails ({r_island.best.fitness:.6g}), "
          f"{evB} migration evals (island total {island_total_ev}), "
          f"{time.perf_counter() - t0:.0f}s", flush=True)
    print(f"  crossover children: {xstats['xover']} evaluated, "
          f"{xstats['beat_max']} beat max(parent), {xstats['beat_min']} beat "
          f"min(parent), best fail-drop {xstats['best_drop']}\n", flush=True)

    # --- Control: N longer independent runs at equal total -----------------
    # Match the island's ACTUAL total evals, not the requested budget.
    B_T = max(B_A, island_total_ev // N)
    print(f"=== Control: best-of-N @ {B_T}/seed (~equal total {island_total_ev}) ===",
          flush=True)
    control_fails = []
    evC = 0
    for i in range(N):
        s = master_seed * 1000 + 500 + i
        t0 = time.perf_counter()
        r = _staged(seed_root, programme_dir, B_T, s, workers)
        control_fails.append(r.best.n_fails)
        evC += r.n_evals
        print(f"  seed {s}: {r.best.n_fails} fails, {r.n_evals} evals, "
              f"{time.perf_counter() - t0:.0f}s", flush=True)
    bestN_T = min(control_fails)
    print(f"  -> bestN@T = {bestN_T} fails  (pool {sorted(control_fails)}), "
          f"{evC} actual evals\n", flush=True)

    # --- Verdict ----------------------------------------------------------
    print("=" * 64)
    print(f"RESULT  {programme_dir.name}  (master_seed {master_seed})")
    print(f"  bestN@A  (free ref,  {evA} ev)        : {bestN_A} fails")
    print(f"  island   (Phase A+migration, {island_total_ev} ev) : {island_fails} fails")
    print(f"  bestN@T  (control,   {evC} ev)        : {bestN_T} fails  <- BAR")
    verdict = ("ISLAND WINS" if island_fails < bestN_T
               else "tie" if island_fails == bestN_T else "ISLAND LOSES")
    print(f"  verdict  : island vs control = {island_fails} vs {bestN_T}  ->  {verdict}")
    print(f"  crossover net-positive: {xstats['beat_max']}/{xstats['xover']} "
          f"beat max(parent); mechanism "
          f"{'LIVE' if xstats['beat_max'] else 'DEAD (alignment null)'}")
    print(f"  wall: {time.perf_counter() - t_start:.0f}s")
    print("=" * 64, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

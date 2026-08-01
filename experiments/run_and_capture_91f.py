#!/usr/bin/env python3
"""homemaker-py-91f support script: run the §13.9 full-default-stack staged
search and capture the TRUE in-process fail list (not a post-hoc rescore).

Investigation finding (see bd issue filed alongside 91f): reloading a
dumped .dom and rescoring it with matching leaf_sharing/collapse_insearch
conf does NOT reliably reproduce driver.search_staged's own reported
n_fails once collapse_insearch's cell-relabelling is doing real work --
scoring `copy.deepcopy(r.best.root)` immediately in-process (before any
dom.dump/dom.load round trip) DOES reliably reproduce it (verified: exact
match across 5 repeats and against the live search's own log). So this
script never rescores from disk -- it captures the fails list right off
the in-memory search result, and only dumps the .dom for reference.

Usage:
  python3 experiments/run_and_capture_91f.py <programme> <seed> <outdir>
"""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import dom, driver, fitness  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = {"leaf_sharing": True, "share_edge_cap": True, "collapse_insearch": True}


def main() -> int:
    prog = sys.argv[1]
    seed = int(sys.argv[2])
    outdir = Path(sys.argv[3])
    outdir.mkdir(parents=True, exist_ok=True)

    pdir = ROOT / "examples" / prog
    seed_root = dom.load(str(pdir / "init.dom"))

    t0 = time.perf_counter()
    r = driver.search_staged(
        seed_root, pdir, budget=20000, pop_size=16, child_budget=80,
        seed_budget=300, stage1_frac=0.4, base_p=0.15, p_crossover=0.2,
        seed=seed, n_workers=1,
        leaf_sharing=True, leaf_share_factor=3,
        depth_balanced=True, interior_outside=True, outside_divisor=3,
    )
    elapsed = time.perf_counter() - t0

    conf, cost = fitness.load_config(pdir, overrides=OVERRIDES)
    fit = fitness.Fitness(conf, cost)
    score, fails = fit.score_with_fails(copy.deepcopy(r.best.root))

    match = (len(fails) == r.best.n_fails)
    print(f"{prog} seed={seed}: elapsed={elapsed:.1f}s search_n_fails="
          f"{r.best.n_fails} in_process_rescore_n_fails={len(fails)} "
          f"match={match}", file=sys.stderr)

    dom.dump(r.best.root, str(outdir / f"{prog}_s{seed}.dom"))
    with open(outdir / f"{prog}_s{seed}.fails.json", "w") as fh:
        json.dump({
            "programme": prog, "seed": seed, "elapsed_s": elapsed,
            "search_n_fails": r.best.n_fails, "search_fitness": r.best.fitness,
            "rescore_n_fails": len(fails), "rescore_match": match,
            "fails": fails,
        }, fh, indent=2)

    return 0 if match else 1


if __name__ == "__main__":
    sys.exit(main())

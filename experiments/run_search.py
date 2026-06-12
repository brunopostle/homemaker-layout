#!/usr/bin/env python3
"""End-to-end memetic search on programme-house (homemaker-py-b39 acceptance).

Runs driver.search from a corpus seed within a stated oracle-evaluation
budget, logs every improvement, writes the best design to
scratch/search_best.dom and independently re-scores it through the oracle to
prove the output is a valid .dom whose recorded fitness is reproducible.

The interesting bar: the seed's geometry-only optimum (inner loop alone,
DESIGN §4.7 reference: c964435 -> 0.00674). Anything above that is value
added by *topology* search.

Run under the go-forward fitness:
  URB_NO_OCCLUSION=1 python3 experiments/run_search.py [budget] [rng-seed]
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker import dom, driver, oracle  # noqa: E402

URB = Path("/home/bruno/src/urb")
EX = URB / "examples" / "programme-house"
SEED_FILE = EX / "c964435454c459f86c3ed9a5a7621132.dom"
OUT = Path(__file__).resolve().parents[1] / "scratch" / "search_best.dom"


def main() -> int:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    rng_seed = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    print(f"seed={SEED_FILE.name} budget={budget} oracle evals, rng seed {rng_seed}",
          flush=True)

    r = driver.search(dom.load(str(SEED_FILE)), EX, budget=budget,
                      urb_root=URB, seed=rng_seed, log=lambda m: print(m, flush=True))

    print(f"\ndone: {r.n_evals} oracle evals across {r.n_topologies} topologies")
    print(f"best: {r.best.fitness:.6g} (fails {r.best.n_fails}) via {r.best.lineage}")
    print("population: " + ", ".join(f"{p.fitness:.4g}/{p.n_fails}f" for p in r.population))

    OUT.parent.mkdir(exist_ok=True)
    dom.dump(r.best.root, str(OUT))
    s = oracle.score(OUT, URB)
    ok = math.isclose(s.fitness, r.best.fitness, rel_tol=1e-9)
    print(f"\n{OUT} re-scored standalone: {s.fitness:.6g} ({s.n_fails} fails) "
          f"-> {'MATCHES search record' if ok else 'MISMATCH'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""homemaker-py-e01: larger-N harbor-house-only sweep, construction_beam_width
1 vs 4, following the exact protocol of c94's original 5-seed end-to-end run
(DESIGN.md §29) -- driver.search from a clean bootstrap (init.dom), n_workers=1
for reproducibility, budget=1500, same seed both arms, all other driver.search
kwargs left at default. Extends seeds 1-5 (reproduced here as a sanity check
against the DESIGN.md §29 table) up to N=15 seeds.

Usage: python experiments/run_e01_sweep.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from homemaker_layout import dom, driver  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "examples" / "harbor-house"
BUDGET = 1500
SEEDS = range(1, 16)
OUT = ROOT / "scratch" / "e01_sweep_results.tsv"


def run(seed: int, bw: int) -> tuple[int, float]:
    seed_root = dom.load(str(EX / "init.dom"))
    r = driver.search(
        seed_root,
        EX,
        budget=BUDGET,
        seed=seed,
        n_workers=1,
        construction_beam_width=bw,
    )
    return r.best.n_fails, r.best.fitness


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    with open(OUT, "w") as f:
        f.write("seed\tbw1_fails\tbw4_fails\tresult\telapsed_s\n")
        for seed in SEEDS:
            t0 = time.perf_counter()
            fails1, _ = run(seed, 1)
            fails4, _ = run(seed, 4)
            elapsed = time.perf_counter() - t0
            if fails4 < fails1:
                result = "bw4 win"
            elif fails4 > fails1:
                result = "bw4 loss"
            else:
                result = "tie"
            line = f"{seed}\t{fails1}\t{fails4}\t{result}\t{elapsed:.1f}"
            print(line, flush=True)
            f.write(line + "\n")
            f.flush()


if __name__ == "__main__":
    main()

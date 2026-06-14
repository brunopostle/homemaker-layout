#!/usr/bin/env python3
"""Acceptance run for the geometry inner loop (homemaker-py-1p0).

Gate (DESIGN.md §4.5, issue acceptance criteria): reproduce or exceed the
Nelder-Mead diagnostic gains — x1.24 / x1.67 / x1.59, no new failures — on
2f45907, candidate-002 and c964435, using the batched compass search.

Usage: accept_innerloop.py [budget] [method]   (default: 200 oracle evals, cma)
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import dom, innerloop, oracle  # noqa: E402

URB = Path("/home/bruno/src/urb")
EX = URB / "examples" / "programme-house"

# name -> reference x-gain. Current bars are the occlusion-disabled re-baseline
# (homemaker-py-gp2): the deterministic-seed CMA run at budget 400 under
# URB_NO_OCCLUSION=1 — set that env var to reproduce. (The original §4.5
# Nelder-Mead bars, flag-off, were 1.24 / 1.67 / 1.59; the inner loop met them
# within noise, homemaker-py-1p0.)
GATE = {
    "2f45907abd9accac2a124d311732f749.dom": 1.63,
    "candidate-002.dom": 1.70,
    "c964435454c459f86c3ed9a5a7621132.dom": 1.68,
}

# Bars are single optimiser draws and per-run variance brackets them
# (candidate-002 drew 0.0117-0.0160 against a 0.0123 flag-off bar).
# Reproduction within 1% counts as met — decision approved 2026-06-12
# (homemaker-py-1p0); chasing the last fraction with seed rolls would be
# cherry-picking.
NOISE_TOL = 0.99


def main() -> int:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    method = sys.argv[2] if len(sys.argv) > 2 else "cma"
    print(f"method={method} budget={budget}")
    all_ok = True
    with tempfile.TemporaryDirectory(prefix="accept_innerloop_") as tmp:
        scratch = Path(tmp)
        shutil.copy(EX / "patterns.config", scratch)
        for name, bar in GATE.items():
            # Baseline = the UNMODIFIED original file, exactly as §4.5 measured
            # it. The inner loop's own x0 score is the equal-offset *projection*
            # of the original (a==b forced, clipped), which is lower for legacy
            # designs with unequal cuts — gains must not be measured from there.
            s_orig = oracle.score(shutil.copy(EX / name, scratch), URB)

            root = dom.load(str(EX / name))
            t0 = time.perf_counter()
            r = innerloop.optimise(root, EX, budget=budget, method=method, urb_root=URB)
            dt = time.perf_counter() - t0
            gain = r.fitness / s_orig.fitness if s_orig.fitness else float("inf")
            ok = gain >= bar * NOISE_TOL and r.n_fails <= s_orig.n_fails
            all_ok &= ok
            print(
                f"{name:42s} dof={len(r.x):2d}  "
                f"orig={s_orig.fitness:.6g}(fails {s_orig.n_fails})  "
                f"projected x0={r.x0_fitness:.6g}(fails {r.x0_n_fails})  "
                f"opt={r.fitness:.6g}(fails {r.n_fails})  "
                f"x{gain:.2f} (bar x{bar:.2f})  "
                f"{r.n_evals} evals / {r.n_oracle_calls} oracle calls / {dt:.0f}s  "
                f"{'PASS' if ok else 'FAIL'}",
                flush=True,
            )
    print("\nGATE " + ("PASSED" if all_ok else "FAILED"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Why does 2f45907 resist equal-offset recovery? (homemaker-py-1p0)

Its equal-offset projection adds a failure (2 -> 3) and batched searches stall
near the projected start, yet DESIGN.md §4.5 reports Nelder-Mead reached
0.015684 from the same projection. This script checks, for 2f45907 only:

  1. fitness of the three projections (midpoint, a-end, b-end)
  2. scipy Nelder-Mead from the midpoint, maxfev=200 (the §4.5 setup)
  3. CMA-ES with sigma0=0.05 (tighter than the 0.15 default)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker import dom, innerloop  # noqa: E402

URB = Path("/home/bruno/src/urb")
EX = URB / "examples" / "programme-house"
NAME = "2f45907abd9accac2a124d311732f749.dom"


def main() -> None:
    root = dom.load(str(EX / NAME))
    with innerloop.OracleEvaluator(root, EX, URB) as ev:
        a = np.array([b.division[0] for b in ev.free])
        b_ = np.array([b.division[1] for b in ev.free])
        mid = (a + b_) / 2
        for label, x in [("mid", mid), ("a-end", a), ("b-end", b_)]:
            s = ev.evaluate([x])[0]
            print(f"projection {label:6s}: {s.fitness:.6g}  fails {s.n_fails}", flush=True)

        # §4.5 reproduction: sequential Nelder-Mead on the same objective
        best = {"f": -1.0, "fails": -1}

        def neg(x: np.ndarray) -> float:
            s = ev.evaluate([np.clip(x, 0.02, 0.98)])[0]
            if s.fitness > best["f"]:
                best.update(f=s.fitness, fails=s.n_fails)
            return -s.fitness

        n0 = ev.n_evals
        minimize(neg, mid, method="Nelder-Mead",
                 options={"maxfev": 200, "xatol": 1e-3, "fatol": 1e-12})
        print(f"NM from mid:       {best['f']:.6g}  fails {best['fails']}  "
              f"({ev.n_evals - n0} evals)", flush=True)

    root = dom.load(str(EX / NAME))
    r = innerloop.optimise(root, EX, budget=200, method="cma", sigmas=(0.05,), urb_root=URB)
    print(f"CMA sigma 0.05:    {r.fitness:.6g}  fails {r.n_fails}  ({r.n_evals} evals)")


if __name__ == "__main__":
    main()

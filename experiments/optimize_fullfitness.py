"""Full-fitness frozen-topology optimisation.

Drive the equal-offset division ratios with a derivative-free optimiser against
the REAL oracle fitness (the whole objective, not an area proxy) on a fixed
topology. This removes both confounds of the earlier sweeps (partial objective,
proxy target) and answers the only question that matters next:

  Is there geometry headroom above the EA's designs, or are they already
  geometry-optima (=> the bottleneck is topology + the 0.5^n cliff)?

For each candidate: report fitness/fails before and after.
"""

import sys
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from homemaker import dom, oracle, solver  # noqa: E402

URB = Path("/home/bruno/src/urb")
EX = URB / "examples/programme-house"
SCRATCH = Path(__file__).resolve().parents[1] / "scratch"
_EPS = 0.02

CANDIDATES = [
    "candidate-002.dom",                      # ~0.0074 (MCP-refined)
    "c964435454c459f86c3ed9a5a7621132.dom",   # ~0.0037 (MCP baseline)
]


def optimise(src: Path, maxfev: int = 200):
    import shutil

    shutil.copy(src, SCRATCH / "orig.dom")
    s0 = oracle.score(SCRATCH / "orig.dom", URB)

    root = dom.load(str(src))
    free = solver.free_branches(root)
    x0 = np.array([b.division[0] for b in free], dtype=float)
    opt_path = SCRATCH / "opt.dom"

    best = {"f": s0.fitness, "fails": s0.n_fails, "x": x0.copy()}

    def neg_fitness(x: np.ndarray) -> float:
        xc = np.clip(x, _EPS, 1 - _EPS)
        for j, b in enumerate(free):
            b.division = [float(xc[j]), float(xc[j])]
        dom.dump(root, str(opt_path))
        try:
            s = oracle.score(opt_path, URB)
        except Exception:  # noqa: BLE001
            return 1e9
        if s.fitness > best["f"]:
            best.update(f=s.fitness, fails=s.n_fails, x=xc.copy())
        return -s.fitness

    minimize(
        neg_fitness, x0, method="Nelder-Mead",
        options={"maxfev": maxfev, "xatol": 1e-3, "fatol": 1e-12},
    )
    return s0, best, len(free)


def main() -> None:
    SCRATCH.mkdir(exist_ok=True)
    import shutil

    shutil.copy(EX / "patterns.config", SCRATCH / "patterns.config")

    maxfev = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    for name in CANDIDATES:
        s0, best, ndof = optimise(EX / name, maxfev)
        ratio = best["f"] / s0.fitness if s0.fitness else float("inf")
        verdict = "IMPROVED" if best["f"] > s0.fitness * 1.001 else "no gain"
        print(
            f"{name:42s} dof={ndof:2d}  "
            f"orig={s0.fitness:.5g}(fails {s0.n_fails})  "
            f"opt={best['f']:.5g}(fails {best['fails']})  "
            f"x{ratio:.2f}  {verdict}",
            flush=True,
        )


if __name__ == "__main__":
    main()

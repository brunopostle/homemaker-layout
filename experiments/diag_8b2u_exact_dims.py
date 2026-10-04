"""`homemaker-py-8b2u` experiment 2: can exact rectangle algebra replace the
inner loop?

Experiment 1 (`diag_8b2u_rect_frame.py --translate`) showed every cell is
exactly (axis-aligned rectangle) cropped to (plot), so the rectangle-frame
pivot is a reparameterisation. Its biggest promised gain is that a slicing
tree's dimensions become algebra: if the dimensions can be SET rather than
SEARCHED, the 80-eval Nelder-Mead loop each child gets today could shrink, and
the outer search could try many more topologies per budget.

§39.78 found the existing shape-curve DP's errors are NOT caused by treating
quads as rectangles, and experiment 1 shows interior cells really are
rectangles -- so today's DP (`shapecurve.solve`) and bottom-up solver
(`solver.solve_ratios`) are fair stand-ins for the frame's exact algebra.

On each FROZEN corpus topology, with every ratio reset to 0.5 (a cold child):

  A  nm80     Nelder-Mead, 80 evals         what a new child gets today
  B  nm2000   Nelder-Mead, 2000 evals       the converged reference
  C  dp       shape-curve DP alone, 0 evals the algebra on its own
  D  dp+nm20  DP, then 20 evals             algebra plus a short polish
  E  sol+nm20 bottom-up solver, then 20     the other algebraic dimensioner

Every arm's final tree is scored by the same evaluator. The question: does C or
D land near B, at a fraction of A's cost?

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_8b2u_exact_dims.py
"""

from __future__ import annotations

import argparse
import copy
import math
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from homemaker_layout import (dom, driver, geometry, innerloop, programme,  # noqa: E402
                              shapecurve, solver)

PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
CORPUS = "coldstart-07b2058+orth-500000-s*.dom"
SEARCH = dict(leaf_sharing=True, collapse_insearch=True)


def cold(root):
    r = copy.deepcopy(root)
    dom.link(r)
    for _, b in innerloop.free_with_keys(r):
        b.division = [0.5, 0.5]
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default=CORPUS)
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--ref-budget", type=int, default=2000)
    args = ap.parse_args(argv)
    geometry.ORTHOGONAL_DIVISION = True

    print(f"{'artefact':42} {'DOF':>4}  " + "  ".join(
        f"{a:>16}" for a in ("R committed", "A nm80", f"B nm{args.ref_budget}", "C dp",
                             "D dp+nm20", "E sol+nm20")))
    print(f"{'':42} {'':>4}  " + "  ".join(f"{'score/fails/s':>16}" for _ in range(6)))
    for name in args.programme or PROGRAMMES:
        prog = REPO / "examples" / name
        fit = driver._fitness_for(str(prog), **SEARCH)
        reqs = programme.load_programme_dir(str(prog))
        conf = fit._conf

        def score(r):
            geometry.clear_cache()
            s, f = fit.score_with_fails(copy.deepcopy(r))
            geometry.clear_cache()
            return s, len(f)

        def nm(r, budget):
            innerloop.optimise(r, str(prog), x0=None, budget=budget)
            return r

        for p in sorted(prog.glob(args.corpus)):
            base = dom.load(str(p))
            dom.link(base)
            dof = len(innerloop.free_with_keys(base))
            cells = [(*score(base), 0.0, "")]      # R: as committed, evolved ratios

            t0 = time.process_time()
            r = nm(cold(base), 80)
            cells.append((*score(r), time.process_time() - t0, ""))

            t0 = time.process_time()
            r = nm(cold(base), args.ref_budget)
            cells.append((*score(r), time.process_time() - t0, ""))

            t0 = time.process_time()
            r = cold(base)
            feasible, _ = shapecurve.solve(r, fit)
            c_time = time.process_time() - t0
            cells.append((*score(r), c_time, "" if feasible else "*"))

            t0 = time.process_time()
            r = cold(base)
            shapecurve.solve(r, fit)
            r = nm(r, 20)
            cells.append((*score(r), time.process_time() - t0, ""))

            t0 = time.process_time()
            r = cold(base)
            try:
                solver.solve_ratios(r, reqs, strip=False, conf=conf)
                note = ""
            except Exception as e:      # an algebraic dimensioner may refuse a tree
                note = "!"
            r = nm(r, 20)
            cells.append((*score(r), time.process_time() - t0, note))

            print(f"{name + '/' + p.name.replace('coldstart-', ''):42} {dof:4d}  " + "  ".join(
                f"{s:7.2g}/{n:3d}/{t:4.0f}{m:1}" for s, n, t, m in cells), flush=True)
    print("\nR = the artefact as committed: the ratios the full 500k search evolved for it."
          "\n* = the DP called the topology infeasible and wrote no ratios "
          "(C is then the cold start itself)\n! = solve_ratios raised; E is then "
          "the cold start plus 20 evals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

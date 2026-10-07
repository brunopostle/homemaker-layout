"""Does a solver pass make a better SEED? (`homemaker-py-8b2u.21`)

§39.109: on a cold topology `solver.solve_ratios` gets 77% of the way to an
evolved design with no scorer call, and on a child it does harm. The one
place a search holds a cold topology is its seeds, which the constructor
already sizes from target areas (`operators._size_divisions_from_targets`,
§12.2) and the driver then tunes for `seed_budget` = 200 evaluations.

Constructed seeds (`diag_3i3_missing_room.build_seed`, no leaf sharing), each
sized four ways and scored with the search's overrides:

  built        as the constructor leaves it
  built+200    ...then 200 evaluations: what a seed gets today
  solved       the solver (stopped at 50 function evaluations) on the built seed
  solved+200   ...then 200 evaluations

NOT covered: seeds as the default search builds them carry SHARED leaves (one
cell standing for several rooms), and the solver aims every cell at one
room's area. A solver pass in the search would have to multiply by the share
first; this measures the idea on seeds where that question does not arise.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_8b2u21_seed_sizing.py
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import sys
import time
from pathlib import Path

from homemaker_layout import dom, driver, geometry, programme, solver

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
ARMS = ("built", "built+200", "solved", "solved+200")
SEARCH = dict(leaf_sharing=False, collapse_insearch=True)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "experiments" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--seeds", type=int, default=6)
    a = ap.parse_args(argv)
    geometry.ORTHOGONAL_DIVISION = True
    build_seed, ab = _load("diag_3i3_missing_room").build_seed, _load("ab_report")

    rows = []
    for name in a.programme or PROGRAMMES:
        prog = REPO / "examples" / name
        reqs = programme.load_programme_dir(str(prog))
        conf = driver._fitness_for(str(prog), **SEARCH)._conf
        for seed in range(a.seeds):
            base = build_seed(prog, seed)
            row = {"programme": name}
            for arm in ARMS:
                root = copy.deepcopy(base)
                dom.link(root)
                geometry.clear_cache()
                t0 = time.process_time()
                if arm.startswith("solved"):
                    try:
                        solver.solve_ratios(root, reqs, strip=False, conf=conf, max_nfev=50)
                    except Exception:
                        row["raised"] = True
                ind, _ = driver._evaluate(root, str(prog), None,
                                          200 if arm.endswith("+200") else 1, {}, "seed", **SEARCH)
                row[arm] = (ind.n_fails, ind.fitness, time.process_time() - t0)
            rows.append(row)
            print(f"  {name} seed {seed}: " + "  ".join(
                f"{arm} {row[arm][0]}" for arm in ARMS), file=sys.stderr, flush=True)

    print(f"\n{len(rows)} constructed seeds, fails (and CPU seconds)\n")
    print(f"{'programme':<16} {'n':>3} " + "".join(f"{arm:>18}" for arm in ARMS))
    groups = [*dict.fromkeys(r["programme"] for r in rows), "ALL"]
    for g in groups:
        sel = [r for r in rows if g == "ALL" or r["programme"] == g]
        print(f"{g:<16} {len(sel):3d} " + "".join(
            f"{sum(r[arm][0] for r in sel) / len(sel):10.1f} ({sum(r[arm][2] for r in sel) / len(sel):4.1f}s)"
            for arm in ARMS))
    for g in ("ALL", *groups[:-1]):
        sel = [r for r in rows if g == "ALL" or r["programme"] == g]
        print(f"\n== {g}: fails, paired on the same seed (a W is the second arm LOWER)")
        for x, y in (("built+200", "solved+200"), ("built+200", "solved"), ("built", "solved")):
            print(f"{x} against {y}:")
            print(ab.format_report(ab.paired_report(
                [float(r[x][0]) for r in sel], [float(r[y][0]) for r in sel], x, y)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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


def shared(a) -> int:
    """Seeds as the DEFAULT search builds them -- shared leaves and all -- and
    the pass as the driver applies it (`driver.solve_seed`), each followed by
    the 80 evaluations a constructed seed really gets.

      built+80          today
      solved+80         `--seed-solver`
      blind+80          the same pass with every share hidden from the solver:
                        the control for whether being share-aware matters
    """
    import inspect

    import numpy as np

    from homemaker_layout import evolve, innerloop, operators

    geometry.ORTHOGONAL_DIVISION = True
    ab = _load("ab_report")
    defaults = {k: v.default for k, v in inspect.signature(driver.search).parameters.items()}
    args = evolve._parse_args(["init.dom"])
    search = dict(leaf_sharing=args.leaf_sharing, collapse_insearch=args.collapse_insearch)
    arms = ("built+80", "solved+80", "blind+80")
    rows = []
    for name in a.programme or PROGRAMMES:
        prog = REPO / "examples" / name
        reqs = programme.load_programme_dir(str(prog))
        types = sorted(reqs) + ["C", "O"]
        conf = driver._fitness_for(str(prog), **search)._conf
        seed_root = dom.load(str(prog / "init.dom"))
        for seed in range(a.seeds):
            topo = operators.constructive_topology(
                seed_root, reqs, np.random.default_rng(seed), types,
                min_storeys=max(programme.n_storeys_required(reqs),
                                programme.storey_minimum(str(prog))),
                adjacency_aware=defaults["seed_adjacency_aware"],
                proportion_aware=defaults["seed_proportion_aware"],
                circ_divisor=defaults["circ_divisor"],
                leaf_sharing=args.leaf_sharing, leaf_share_factor=args.leaf_share_factor,
                depth_balanced=defaults["depth_balanced"],
                interior_outside=defaults["interior_outside"],
                outside_divisor=defaults["outside_divisor"])
            dom.link(topo)
            n_shared = sum(lf.share > 1 and lf.share_type == lf.type
                           for lvl in dom.levels(topo) for lf in lvl.leaves())
            row = {"programme": name, "shared": n_shared}
            for arm in arms:
                root = copy.deepcopy(topo)
                dom.link(root)
                if arm != "built+80":
                    hidden = []
                    if arm == "blind+80":
                        for lvl in dom.levels(root):
                            for lf in lvl.leaves():
                                hidden.append((lf, lf.share))
                                lf.share = 1
                    driver.solve_seed(root, reqs, conf)
                    for lf, k in hidden:
                        lf.share = k
                geometry.clear_cache()
                ind, _ = driver._evaluate(root, str(prog), None, 80, {}, "seed", **search)
                row[arm] = ind.n_fails
            rows.append(row)
            print(f"  {name} seed {seed} ({n_shared} shared cells): " + "  ".join(
                f"{arm} {row[arm]}" for arm in arms), file=sys.stderr, flush=True)
    print(f"\n{len(rows)} seeds as the default search constructs them "
          f"(leaf_sharing={args.leaf_sharing}, factor {args.leaf_share_factor}), fails\n")
    print(f"{'programme':<16} {'n':>3} {'shared cells':>13} " + "".join(f"{x:>12}" for x in arms))
    groups = [*dict.fromkeys(r["programme"] for r in rows), "ALL"]
    for g in groups:
        sel = [r for r in rows if g == "ALL" or r["programme"] == g]
        print(f"{g:<16} {len(sel):3d} {sum(r['shared'] for r in sel) / len(sel):13.1f} "
              + "".join(f"{sum(r[x] for r in sel) / len(sel):12.1f}" for x in arms))
    for g in ("ALL", *groups[:-1]):
        sel = [r for r in rows if g == "ALL" or r["programme"] == g]
        print(f"\n== {g}: fails, paired on the same seed (a W is the second arm LOWER)")
        for x, y in (("built+80", "solved+80"), ("blind+80", "solved+80")):
            print(f"{x} against {y}:")
            print(ab.format_report(ab.paired_report(
                [float(r[x]) for r in sel], [float(r[y]) for r in sel], x, y)))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--shared", action="store_true",
                    help="seeds as the default search builds them, shared leaves included")
    a = ap.parse_args(argv)
    if a.shared:
        return shared(a)
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

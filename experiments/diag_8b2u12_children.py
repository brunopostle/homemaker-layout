"""Would the sizing solver serve a CHILD better than its 80 evaluations?
(`homemaker-py-8b2u.12`, second half)

`diag_8b2u12_closed_form.py` asks the bead's question as written -- a frozen
topology, every ratio thrown away. But a search almost never sizes a topology
from nothing: a child is its parent with one move applied, it INHERITS the
parent's ratios, and only the cuts the move made start at 0.5. So this is the
measurement that could change a default: children drawn with the search's own
mutation mix from the corpus designs, each sized four ways and scored the way
the search scores a child (`driver._evaluate`, the same overrides).

  today     inherited ratios, 80 evaluations of Nelder-Mead
  sol       `solver.solve_ratios` from the inherited ratios (least squares on
            area, width and proportion; it calls no scorer), then ONE score
  sol+20    the same, then 20 evaluations
  sol10+20  the solver stopped after 10 iterations, then 20 evaluations

Reported: fails and CPU seconds per child, each arm paired against `today`
on the same child (`ab_report.paired_report`, so the MDD is beside the
verdict), all programmes and each.

What this cannot say is the bead's last question -- whether a search ENDS
better. A cheaper child means more children per budget, and whether the
search keeps them is population dynamics: the box.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 PYTHONPATH=src \\
        python experiments/diag_8b2u12_children.py [--draws 6]
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import sys
import time
from pathlib import Path

import numpy as np

from homemaker_layout import dom, driver, geometry, innerloop, operators, programme, solver

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
ARMS = ("today", "sol", "sol+20", "sol10+20")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "experiments" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def size(arm, child, prog, ratios, reqs, conf, search):
    """Size one child by `arm`; returns (fails, fitness, cpu seconds)."""
    root = copy.deepcopy(child)
    dom.link(root)
    geometry.clear_cache()
    x0 = innerloop.warm_x0(root, {**innerloop.ratio_map(root), **ratios})
    t0 = time.process_time()
    if arm == "today":
        ind, _ = driver._evaluate(root, str(prog), x0, 80, {}, "8b2u12", **search)
    else:
        for b, x in zip(solver.free_branches(root), x0):
            b.division = [float(x), float(x)]
        geometry.clear_cache()
        try:
            solver.solve_ratios(root, reqs, strip=False, conf=conf,
                                max_nfev=10 if arm.startswith("sol10") else 4000)
        except Exception:               # it may refuse a tree; the start stands
            pass
        budget = 20 if arm.endswith("+20") else 1
        ind, _ = driver._evaluate(root, str(prog), None, budget, {}, "8b2u12", **search)
    return ind.n_fails, ind.fitness, time.process_time() - t0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default="coldstart-1a24b6a+orth-500000-s*.dom")
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--draws", type=int, default=6, help="children per artefact")
    a = ap.parse_args(argv)
    geometry.ORTHOGONAL_DIVISION = True
    shaft, ab = _load("diag_8b2u_fixed_shaft"), _load("ab_report")
    weights, search = shaft.search_weights(), shaft.SEARCH

    rows = []
    for name in a.programme or PROGRAMMES:
        prog = REPO / "examples" / name
        reqs = programme.load_programme_dir(str(prog))
        types = sorted(reqs) + ["C", "O"]
        conf = driver._fitness_for(str(prog), **search)._conf
        for p in sorted(prog.glob(a.corpus)):
            parent = dom.load(str(p))
            dom.link(parent)
            geometry.clear_cache()
            ratios = innerloop.ratio_map(parent)
            rng = np.random.default_rng(int.from_bytes(p.name.encode(), "little") % 2**32)
            got = 0
            while got < a.draws:
                child, desc = operators.mutate(parent, rng, types, weights=weights, reqs=reqs)
                if "noop" in desc:
                    continue
                got += 1
                row = {"programme": name, "op": desc.split()[0],
                       "new cuts": sum(k not in ratios for k in innerloop.ratio_map(child))}
                for arm in ARMS:
                    row[arm] = size(arm, child, prog, ratios, reqs, conf, search)
                rows.append(row)
                print(f"  {name}/{p.name[-8:-4]} {row['op']:<18} "
                      + "  ".join(f"{arm} {row[arm][0]}/{row[arm][2]:.1f}s" for arm in ARMS),
                      file=sys.stderr, flush=True)

    print(f"\n{len(rows)} children ({a.draws} per artefact, {a.corpus}), fails and CPU seconds per child\n")
    print(f"{'programme':<16} {'n':>3} " + "".join(f"{arm + ' fails':>15}{'s':>6}" for arm in ARMS))
    for g in [*dict.fromkeys(r["programme"] for r in rows), "ALL"]:
        sel = [r for r in rows if g == "ALL" or r["programme"] == g]
        print(f"{g:<16} {len(sel):3d} " + "".join(
            f"{sum(r[arm][0] for r in sel) / len(sel):15.2f}"
            f"{sum(r[arm][2] for r in sel) / len(sel):6.1f}" for arm in ARMS))
    for g in ("ALL", *dict.fromkeys(r["programme"] for r in rows)):
        sel = [r for r in rows if g == "ALL" or r["programme"] == g]
        if len(sel) < 2:
            continue
        print(f"\n== {g}: fails, each arm paired against `today` on the same child "
              f"(a W is the arm LOWER)")
        for arm in ARMS[1:]:
            print(f"{arm}:")
            print(ab.format_report(ab.paired_report(
                [float(r["today"][0]) for r in sel], [float(r[arm][0]) for r in sel],
                "today", arm)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

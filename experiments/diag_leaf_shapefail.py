#!/usr/bin/env python3
"""Diagnostic A (homemaker-py-erc.1, DESIGN.md §13.1): per-leaf shape-fail vs
density / granularity.

GATES the leaf-sharing vs compactness-cuts decision. Open question from §12.3:
is the shape floor INTRINSIC to slicing at this leaf density (→ fewer leaves is
the only lever → leaf-sharing), or fixable by better-shaped cuts at the SAME
leaf count (→ compactness-cuts can pay)?

Reads, does not change behaviour. For each programme × seed it builds the §12.2
constructive seed (adjacency-aware, proportion-aware), lays it out at the
proportion-aware TARGET geometry — the squarest geometry the inner loop warm
starts from, exactly as operators.predicted_shape_fails does — then counts
size/width/proportion/crinkliness fails per leaf and reports them against
leaves-per-room and plot utilisation.

Two views:
  (1) CROSS-PROGRAMME density sweep: programmes spanning 6→52 rooms.
  (2) SYNTHETIC granularity sweep: one programme, circ_divisor varied so leaf
      count changes while the room set is held fixed.

DECISION RULE: if per-leaf shape-fail is FLAT across densities → floor is
intrinsic to slicing density → prioritise leaf-sharing (erc.3), deprioritise
compactness-cuts (erc.5). If it RISES with density → better cuts can pay → keep
compactness-cuts.

Usage:
  URB_NO_OCCLUSION=1 python3 experiments/diag_leaf_shapefail.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import dom, fitness, geometry, operators, programme  # noqa: E402

SHAPE = ("size", "width", "proportion", "crinkliness")
PROGRAMMES = ["programme-house", "harbor-house-l0", "harbor-house", "maple-court"]
SEEDS = (0, 1, 2)
ROOT = Path(__file__).resolve().parents[1]


def _shape_breakdown(fails) -> dict[str, int]:
    out = {k: 0 for k in SHAPE}
    for f in fails:
        for k in SHAPE:
            if f.endswith(" " + k):
                out[k] += 1
                break
    return out


def _layout_at_target(topo: dom.Node, reqs) -> dom.Node:
    """Mirror operators.predicted_shape_fails: squarest target-proportional geom."""
    child = copy.deepcopy(topo)
    dom._link(child)
    for lvl in dom.levels(child):
        operators._size_divisions_from_targets(lvl, reqs)
    return child


def _measure(programme_dir: Path, fit, reqs, types, seed_root, circ_divisor, s):
    rng = np.random.default_rng(s)
    topo = operators.constructive_topology(
        seed_root, reqs, rng, types,
        adjacency_aware=True, proportion_aware=True, circ_divisor=circ_divisor)
    laid = _layout_at_target(topo, reqs)
    geometry.clear_cache()
    _score, fails = fit.score_with_fails(copy.deepcopy(laid))
    bd = _shape_breakdown(fails)

    leaves = [lf for lvl in dom.levels(laid) for lf in lvl.leaves()]
    n_leaves = len(leaves)
    n_rooms = sum(r.count for r in reqs.values())

    # plot utilisation: sized-room achieved area / total plot area
    sized = {lf for lf in leaves if lf.type in reqs and reqs[lf.type].size > 0}
    geometry.clear_cache()
    occupied = sum(geometry.area(lf) for lf in sized)
    plot = sum(geometry.area(lvl) for lvl in dom.levels(laid))
    util = occupied / plot if plot else float("nan")

    return {
        "n_leaves": n_leaves, "n_rooms": n_rooms,
        "lpr": n_leaves / n_rooms, "util": util,
        "shape_total": sum(bd.values()), **bd,
    }


def _avg(rows, key):
    return sum(r[key] for r in rows) / len(rows)


def main() -> int:
    print("Diagnostic A — per-leaf shape-fail vs density (§13.1)\n")
    print("Layout: proportion-aware TARGET geometry (predicted_shape_fails proxy)")
    print(f"Seeds: {SEEDS}  per-leaf rate = shape-fails / leaves\n")

    # ---- (1) cross-programme density sweep ----
    print("(1) CROSS-PROGRAMME density sweep")
    hdr = (f"{'programme':<18}{'rooms':>6}{'leaves':>7}{'l/room':>7}{'util':>6}"
           f"{'shape':>7}{'/leaf':>7}  {'siz/lf':>7}{'wid/lf':>7}{'prp/lf':>7}{'crk/lf':>7}")
    print(hdr)
    print("-" * len(hdr))
    for name in PROGRAMMES:
        pdir = ROOT / "examples" / name
        reqs = programme.load_programme_dir(pdir)
        types = sorted(reqs) + ["C", "O"]
        conf, cost = fitness.load_config(pdir)
        fit = fitness.Fitness(conf, cost)
        seed_root = dom.load(str(pdir / "init.dom"))
        rows = [_measure(pdir, fit, reqs, types, seed_root, 3, s) for s in SEEDS]
        nl = _avg(rows, "n_leaves")
        print(f"{name:<18}{_avg(rows,'n_rooms'):>6.0f}{nl:>7.1f}"
              f"{_avg(rows,'lpr'):>7.2f}{_avg(rows,'util'):>6.2f}"
              f"{_avg(rows,'shape_total'):>7.1f}{_avg(rows,'shape_total')/nl:>7.3f}"
              f"  {_avg(rows,'size')/nl:>7.3f}{_avg(rows,'width')/nl:>7.3f}"
              f"{_avg(rows,'proportion')/nl:>7.3f}{_avg(rows,'crinkliness')/nl:>7.3f}")

    # ---- (2) synthetic granularity sweep on maple-court ----
    print("\n(2) SYNTHETIC granularity sweep — maple-court, circ_divisor varied")
    print("    (room set fixed, leaf count varied via the c3g circ knob)")
    name = "maple-court"
    pdir = ROOT / "examples" / name
    reqs = programme.load_programme_dir(pdir)
    types = sorted(reqs) + ["C", "O"]
    conf, cost = fitness.load_config(pdir)
    fit = fitness.Fitness(conf, cost)
    seed_root = dom.load(str(pdir / "init.dom"))
    hdr2 = (f"{'circ_div':>9}{'leaves':>7}{'l/room':>7}{'util':>6}"
            f"{'shape':>7}{'/leaf':>7}  {'siz/lf':>7}{'wid/lf':>7}{'prp/lf':>7}{'crk/lf':>7}")
    print(hdr2)
    print("-" * len(hdr2))
    for cd in (2, 3, 4, 6, 9):
        rows = [_measure(pdir, fit, reqs, types, seed_root, cd, s) for s in SEEDS]
        nl = _avg(rows, "n_leaves")
        print(f"{cd:>9}{nl:>7.1f}{_avg(rows,'lpr'):>7.2f}{_avg(rows,'util'):>6.2f}"
              f"{_avg(rows,'shape_total'):>7.1f}{_avg(rows,'shape_total')/nl:>7.3f}"
              f"  {_avg(rows,'size')/nl:>7.3f}{_avg(rows,'width')/nl:>7.3f}"
              f"{_avg(rows,'proportion')/nl:>7.3f}{_avg(rows,'crinkliness')/nl:>7.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

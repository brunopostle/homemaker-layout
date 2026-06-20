#!/usr/bin/env python3
"""Raw-seed fail breakdown: proportion-aware split sizing A/B (homemaker-py-leu.2).

Builds the *constructive* seed (operators.constructive_topology, single-stage,
adjacency-aware) with proportion-aware split sizing OFF then ON, scores each raw
seed with native fitness BEFORE the inner loop, and tallies fails by family. The
claim under test (DESIGN.md §12.2): sizing cuts from target areas drops the
geometry family (size/width/proportion/crinkliness) at the raw seed without
regressing the adjacency/access family that §11.6/§11.7 fixed.

Usage:
  URB_NO_OCCLUSION=1 python3 experiments/measure_seed_geometry.py <programme_dir> [n_seeds]
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import dom, fitness, operators, programme  # noqa: E402

GEOM = ("perpendicular", "proportion", "size", "width", "crinkliness")


def _categorise(fails: tuple[str, ...]) -> dict[str, int]:
    cats = {"geometry": 0, "access_adj": 0, "missing": 0, "other": 0}
    for f in fails:
        if f.endswith(GEOM) or "edge too long" in f:
            cats["geometry"] += 1
        elif "access" in f or "inaccessible" in f or "adjacent" in f or "adjacency" in f:
            cats["access_adj"] += 1
        elif "missing" in f:
            cats["missing"] += 1
        else:
            cats["other"] += 1
    return cats


def main() -> int:
    programme_dir = Path(sys.argv[1])
    n_seeds = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    reqs = programme.load_programme_dir(programme_dir)
    types = sorted(reqs) + ["C", "O"]
    conf, cost = fitness.load_config(programme_dir)
    fit = fitness.Fitness(conf, cost)

    seed_file = programme_dir / "init.dom"
    seed_root = dom.load(str(seed_file))

    print(f"programme : {programme_dir.name}  ({len(reqs)} codes)")
    print(f"seeds     : {n_seeds}  (single-stage constructive, adjacency-aware)\n")

    agg = {0: {"total": 0, "geometry": 0, "access_adj": 0, "missing": 0, "other": 0},
           1: {"total": 0, "geometry": 0, "access_adj": 0, "missing": 0, "other": 0}}

    for s in range(n_seeds):
        for prop in (False, True):
            rng = np.random.default_rng(s)
            topo = operators.constructive_topology(
                seed_root, reqs, rng, types,
                adjacency_aware=True, proportion_aware=prop)
            _score, fails = fit.score_with_fails(copy.deepcopy(topo))
            cats = _categorise(fails)
            agg[int(prop)]["total"] += len(fails)
            for k, v in cats.items():
                agg[int(prop)][k] += v

    def _avg(d, k):
        return d[k] / n_seeds

    print(f"{'family':<12} {'PROP=0 (before)':>16} {'PROP=1 (after)':>16}")
    for k in ("geometry", "access_adj", "missing", "other", "total"):
        print(f"{k:<12} {_avg(agg[0], k):>16.1f} {_avg(agg[1], k):>16.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Depth-balanced construction floor probe (homemaker-py-erc.4, DESIGN.md §13.4).

Cheap de-risk BEFORE the full 20k A/B. Diagnostic B (§13.2) localized the size
fails to depth-driven MALDISTRIBUTION: a leaf's area is the product of cut
fractions down its ancestry in the binary slicing tree, so the default random
(`_grow_leaves` picks a random leaf to split) caterpillar lands equal-target
rooms at depths that differ by many levels — the same code seen at 0.05x and
14.7x target. The inner loop provably cannot repair it (frozen topology).

erc.4 lever: grow a DEPTH-BALANCED tree (always split a shallowest leaf), so all
leaves sit at comparable depth and the proportion-aware sizing pass hits each
target with cut fractions near their proportional value instead of compounding
fmin/fmax clamp error down a deep spine.

This script builds the §12.2 constructive seed three ways — OFF (baseline),
balanced (erc.4), balanced+share3 (the erc.7 synergy preview) — and at each
mode reports (a) the area maldistribution (mean achieved/target, % undersize,
max/min ratio, leaf-depth spread) and (b) the fail floor at the seed geometry
and again after innerloop.optimise, under the matching objective.

DECISION RULE: if balancing tightens the a/t spread (max ratio down, %under
down) AND lowers size + total fails vs OFF -> the floor moves -> thread the flag
through the driver for the staged 20k A/B. If the spread / fails do not move ->
depth balance alone cannot pay; consider explicit giant-splitting instead.

Usage:
  URB_NO_OCCLUSION=1 python3 experiments/diag_depth_balance.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import (  # noqa: E402
    dom, fitness, geometry, innerloop, operators, programme)

PROGRAMMES = ["harbor-house", "maple-court"]
SEEDS = (0, 1, 2)
BUDGET = 80  # bootstrap child budget, as in Diagnostics A/B and §13.3
ROOT = Path(__file__).resolve().parents[1]

CATS = ("missing", "size", "width", "proportion", "crinkliness",
        "adjacency", "access", "other")


def _bucket(fails) -> dict[str, int]:
    out = {k: 0 for k in CATS}
    for f in fails:
        if "missing" in f or "too many" in f:
            out["missing"] += 1
        elif f.endswith(" size"):
            out["size"] += 1
        elif f.endswith(" width"):
            out["width"] += 1
        elif f.endswith(" proportion"):
            out["proportion"] += 1
        elif f.endswith(" crinkliness"):
            out["crinkliness"] += 1
        elif "adjacen" in f:
            out["adjacency"] += 1
        elif "access" in f or "inaccessible" in f:
            out["access"] += 1
        else:
            out["other"] += 1
    return out


class _force_sharing:
    """Make innerloop's NativeEvaluator build its fitness with ``leaf_sharing``
    on, so the inner loop optimises the SAME relaxed objective the seed was
    scored under (the dir's patterns.config has no such key)."""

    def __init__(self, on: bool):
        self.on = on

    def __enter__(self):
        self._orig = fitness.load_config
        if self.on:
            def patched(directory, _orig=self._orig):
                conf, cost = _orig(directory)
                conf = dict(conf)
                conf["leaf_sharing"] = True
                return conf, cost
            fitness.load_config = patched
        return self

    def __exit__(self, *exc):
        fitness.load_config = self._orig


def _maldist(topo, fit, reqs) -> dict:
    """Achieved/target spread over sized leaves + leaf-depth spread."""
    geometry.clear_cache()
    ratios = []
    for lvl in dom.levels(topo):
        for lf in lvl.leaves():
            r = reqs.get(lf.type) if lf.type else None
            if r is not None and r.has_size and r.size > 0:
                tgt = r.size * (lf.share if lf.share_type == lf.type else 1)
                ratios.append(geometry.area(lf) / tgt if tgt else float("nan"))
    depths = [d for lvl in dom.levels(topo)
              for _l, d in operators._leaves_with_depth(lvl)]
    ratios = np.array(ratios) if ratios else np.array([float("nan")])
    return {
        "mean_ratio": float(np.mean(ratios)),
        "pct_under": 100.0 * float(np.mean(ratios < 0.9)),
        "max_ratio": float(np.max(ratios)),
        "min_ratio": float(np.min(ratios)),
        "depth_spread": (max(depths) - min(depths)) if depths else 0,
    }


def _measure(fit, pdir, seed_root, reqs, types, s, balanced, sharing, factor):
    rng = np.random.default_rng(s)
    topo = operators.constructive_topology(
        seed_root, reqs, rng, types, adjacency_aware=True, proportion_aware=True,
        depth_balanced=balanced, leaf_sharing=sharing, leaf_share_factor=factor)
    n_leaves = sum(len(lvl.leaves()) for lvl in dom.levels(topo))
    md = _maldist(topo, fit, reqs)
    _s, fails = fit.score_with_fails(copy.deepcopy(topo))
    before = {"n_leaves": n_leaves, "total": len(fails), **_bucket(fails), **md}

    after_tree = copy.deepcopy(topo)
    with _force_sharing(sharing):
        innerloop.optimise(after_tree, str(pdir), x0=None, budget=BUDGET,
                           method="nm", use_native=True)
    _s2, fails2 = fit.score_with_fails(copy.deepcopy(after_tree))
    after = {"n_leaves": n_leaves, "total": len(fails2), **_bucket(fails2),
             **_maldist(after_tree, fit, reqs)}
    return before, after


def _avg(rows, k):
    return sum(r[k] for r in rows) / len(rows)


def main() -> int:
    print("Depth-balanced construction floor probe (§13.4)\n")
    print(f"Seeds: {SEEDS}.  OFF = random-grow baseline; bal = depth_balanced; "
          "bal+sh3 = balanced + leaf_sharing f3.")
    print(f"seed = constructive seed; +il = after innerloop.optimise (nm, "
          f"budget={BUDGET}).\n")
    cols = ("leaves", "total", "size", "crink", "missing", "a/t", "%und",
            "maxR", "minR", "dDep")
    hdr = f"{'programme':<14}{'mode':>10}" + "".join(f"{c:>8}" for c in cols)

    def _row(name, label, rows):
        vals = [_avg(rows, "n_leaves"), _avg(rows, "total"), _avg(rows, "size"),
                _avg(rows, "crinkliness"), _avg(rows, "missing"),
                _avg(rows, "mean_ratio"), _avg(rows, "pct_under"),
                _avg(rows, "max_ratio"), _avg(rows, "min_ratio"),
                _avg(rows, "depth_spread")]
        print(f"{name:<14}{label:>10}" + "".join(f"{v:>8.1f}" for v in vals))

    for name in PROGRAMMES:
        pdir = ROOT / "examples" / name
        reqs = programme.load_programme_dir(pdir)
        types = sorted(reqs) + ["C", "O"]
        conf, cost = fitness.load_config(pdir)
        seed_root = dom.load(str(pdir / "init.dom"))

        fit_off = fitness.Fitness(conf, cost)
        conf_on = dict(conf)
        conf_on["leaf_sharing"] = True
        fit_on = fitness.Fitness(conf_on, cost)

        print(hdr)
        print("-" * len(hdr))
        modes = [("OFF", fit_off, False, False, 1),
                 ("bal", fit_off, True, False, 1),
                 ("bal+sh3", fit_on, True, True, 3)]
        for label, fit, balanced, sharing, factor in modes:
            pairs = [_measure(fit, pdir, seed_root, reqs, types, s,
                              balanced, sharing, factor) for s in SEEDS]
            _row(name, label, [b for b, _a in pairs])
            _row(name, label + "+il", [a for _b, a in pairs])
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

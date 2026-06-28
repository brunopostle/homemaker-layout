#!/usr/bin/env python3
"""Leaf-sharing floor probe (homemaker-py-erc.3, DESIGN.md §13.3).

Cheap de-risk BEFORE the full 20k A/B: does collapsing same-code rooms into
fewer, larger SHARED leaves actually lower the achievable fail floor, or does
the gain leak back as missing/size fails under the relaxed objective?

§13.1 found the per-leaf shape tax is ~1.8 and FLAT vs slicing density, so total
shape fails track leaf count linearly → fewer leaves is the only floor-mover.
Leaf-sharing reduces ROOM-leaf count: a leaf sized to k×target counts as k
same-code rooms (graph._leaf_share_mult), so presence holds without a missing
fail and size is scored against k×target. This script builds the §12.2
constructive seed both ways (baseline OFF vs sharing ON, share_factor sweep),
scores each at its own seed geometry, and reports the fail breakdown.

DECISION RULE: if sharing-ON total fails drop well below baseline (and the drop
is in size+crinkliness, NOT bought back by missing) → the floor moves → proceed
to thread the flag through the driver for the staged 20k A/B. If missing fails
balloon or totals don't move → stop; same-code sharing cannot pay here.

Usage:
  URB_NO_OCCLUSION=1 python3 experiments/diag_leaf_sharing.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import dom, fitness, innerloop, operators, programme  # noqa: E402

PROGRAMMES = ["harbor-house", "maple-court"]
SEEDS = (0, 1, 2)
BUDGET = 80  # bootstrap child budget, as in Diagnostic B
ROOT = Path(__file__).resolve().parents[1]


class _force_sharing:
    """Context manager: make innerloop's NativeEvaluator build its fitness in
    leaf_sharing mode (the dir's patterns.config has no such key), so the inner
    loop optimises against the SAME relaxed objective the seed was scored under."""

    def __init__(self, on: bool):
        self.on = on

    def __enter__(self):
        self._orig = fitness.load_config
        if self.on:
            def patched(directory, overrides=None):
                conf, cost = self._orig(directory, overrides=overrides)
                conf = dict(conf)
                conf["leaf_sharing"] = True
                return conf, cost
            fitness.load_config = patched
        return self

    def __exit__(self, *exc):
        fitness.load_config = self._orig

# fail-string buckets (order matters: first match wins)
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


def _build(seed_root, reqs, types, s, sharing, factor):
    rng = np.random.default_rng(s)
    return operators.constructive_topology(
        seed_root, reqs, rng, types,
        adjacency_aware=True, proportion_aware=True,
        leaf_sharing=sharing, leaf_share_factor=factor)


def _measure(fit, pdir, seed_root, reqs, types, s, sharing, factor):
    topo = _build(seed_root, reqs, types, s, sharing, factor)
    n_leaves = sum(len(lvl.leaves()) for lvl in dom.levels(topo))
    _score, fails = fit.score_with_fails(copy.deepcopy(topo))
    before = {"n_leaves": n_leaves, "total": len(fails), **_bucket(fails)}

    after_tree = copy.deepcopy(topo)
    with _force_sharing(sharing):
        innerloop.optimise(after_tree, str(pdir), x0=None, budget=BUDGET,
                           method="nm", use_native=True)
    _s2, fails2 = fit.score_with_fails(copy.deepcopy(after_tree))
    after = {"n_leaves": n_leaves, "total": len(fails2), **_bucket(fails2)}
    return before, after


def _avg(rows, k):
    return sum(r[k] for r in rows) / len(rows)


def main() -> int:
    print("Leaf-sharing floor probe (§13.3)\n")
    print("Seed geometry = constructive proportion-aware target (built per mode).")
    print(f"Seeds: {SEEDS}.  'OFF' = baseline fitness; 'shareN' = leaf_sharing, "
          "share_factor=N.")
    print(f"seed = constructive seed; +il = after innerloop.optimise (nm, "
          f"budget={BUDGET}) under the same objective.\n")
    cols = ("leaves", "total", "missing", "size", "crink", "width", "prop",
            "adj", "access", "other")
    hdr = f"{'programme':<14}{'mode':>10}" + "".join(f"{c:>8}" for c in cols)

    def _row(name, label, rows, k):
        vals = [_avg(rows, "n_leaves"), _avg(rows, "total"),
                _avg(rows, "missing"), _avg(rows, "size"),
                _avg(rows, "crinkliness"), _avg(rows, "width"),
                _avg(rows, "proportion"), _avg(rows, "adjacency"),
                _avg(rows, "access"), _avg(rows, "other")]
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
        modes = [("OFF", fit_off, False, 1),
                 ("share2", fit_on, True, 2),
                 ("share3", fit_on, True, 3)]
        for label, fit, sharing, factor in modes:
            pairs = [_measure(fit, pdir, seed_root, reqs, types, s, sharing, factor)
                     for s in SEEDS]
            befores = [b for b, _a in pairs]
            afters = [a for _b, a in pairs]
            _row(name, label, befores, "before")
            _row(name, label + "+il", afters, "after")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

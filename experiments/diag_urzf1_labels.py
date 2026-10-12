"""How far do a live search's STORED room labels stand from the labels its
scorer scores? (`homemaker-py-urzf.1`, DESIGN.md §39.120 finding 6)

The search scores with `collapse_insearch`: before counting anything the
scorer relabels cells to the rooms they fit best, on its own copy. The tree an
individual carries keeps the labels it was bred with. So an operator that
reads labels -- `place_missing` counts rooms -- is reading something the
scorer never saw. This runs a short real search and, for every individual
evaluated, compares the two:

* how many cells the collapse relabels;
* whether a room is MISSING by the stored labels and present after the
  collapse (the state in which `place_missing` cuts a cell nobody asked for);
* whether scoring the collapsed tree gives the score the individual has
  (it must, or writing the labels back would change what a design is worth).

    HOMEMAKER_ORTHOGONAL_DIVISION=1 PYTHONPATH=src \\
        python experiments/diag_urzf1_labels.py [--programme programme-house] [--budget 4000]
"""

from __future__ import annotations

import argparse
import collections
import copy
import sys
from pathlib import Path

from homemaker_layout import dom, driver, geometry, graph

REPO = Path(__file__).resolve().parents[1]


def collapsed(fit, root):
    t = copy.deepcopy(root)
    dom.link(t)
    geometry.clear_cache()
    if fit._collapse_insearch:
        fit.collapse_global(t, adjacency=fit._collapse_insearch_adjacency,
                            objective="threshold", preserve_public_access=True,
                            iters=fit._collapse_insearch_iters)
    return t


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", default="programme-house")
    ap.add_argument("--budget", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    geometry.ORTHOGONAL_DIVISION = True
    prog = REPO / "examples" / a.programme
    reqs = driver._reqs_for(str(prog)) if hasattr(driver, "_reqs_for") else None
    stats = collections.Counter()
    real = driver._evaluate

    sig = __import__("inspect").signature(real)

    def spy(*args, **kwargs):
        ind, used = real(*args, **kwargs)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        kw = bound.arguments
        programme_dir = kw["programme_dir"]
        if ind.lineage.startswith("pruned/"):
            return ind, used
        fit = driver._fitness_for(
            str(programme_dir), kw.get("leaf_sharing", False), kw.get("superpose", False),
            kw.get("max_share"), kw.get("conn_grade", False),
            kw.get("collapse_insearch", True), kw.get("multi_use", False))
        t = collapsed(fit, ind.root)
        a_, b_ = ([lf.type for lvl in dom.levels(r) for lf in lvl.leaves()]
                  for r in (ind.root, t))
        moved = sum(x != y for x, y in zip(a_, b_))
        phase = "sharing" if kw.get("leaf_sharing") else "plain"
        stats[phase, "individuals"] += 1
        stats[phase, "cells"] += len(a_)
        stats[phase, "cells relabelled"] += moved
        stats[phase, "individuals with a relabelled cell"] += moved > 0
        miss0 = graph.check_space_counts(copy.deepcopy(ind.root), reqs)[1]
        miss1 = graph.check_space_counts(copy.deepcopy(t), reqs)[1]
        stats[phase, "missing by stored labels"] += bool(miss0)
        stats[phase, "missing by stored labels, present to the scorer"] += bool(miss0) and not miss1
        geometry.clear_cache()
        s_c, f_c = fit.score_with_fails(copy.deepcopy(t))
        stats[phase, "collapsed tree scores the same"] += abs(s_c - ind.fitness) <= 1e-9 * max(1.0, abs(ind.fitness)) and len(f_c) == ind.n_fails
        geometry.clear_cache()
        return ind, used

    driver._evaluate = spy
    try:
        root = dom.load(str(prog / "init.dom"))
        driver.search(root, str(prog), budget=a.budget, seed=a.seed, leaf_sharing=True)
        root = dom.load(str(prog / "init.dom"))
        driver.search(root, str(prog), budget=a.budget, seed=a.seed, leaf_sharing=False)
    finally:
        driver._evaluate = real
    for phase in ("sharing", "plain"):
        n = stats[phase, "individuals"]
        if not n:
            continue
        print(f"\n{a.programme}, a {a.budget}-evaluation search, leaf_sharing "
              f"{'on (the main phase)' if phase == 'sharing' else 'off (the polish)'}: "
              f"{n} individuals")
        for k in ("cells relabelled", "individuals with a relabelled cell",
                  "missing by stored labels",
                  "missing by stored labels, present to the scorer",
                  "collapsed tree scores the same"):
            d = stats[phase, "cells"] if k == "cells relabelled" else n
            print(f"  {k:<52} {stats[phase, k]:>6} of {d}  ({100 * stats[phase, k] / d:.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Diagnostic B (homemaker-py-erc.2, DESIGN.md §13.2): undersize-despite-slack
localization — construction-target vs inner-loop-fill.

GATES the plot-fill-construction (`erc.4`) vs inner-loop-slack-expansion (`erc.6`)
decision. The paradox from §12.3: plot utilisation is ~0.44 (over half the plot
empty) yet size fails are large (rooms UNDERSIZE). Where is the slack stranded,
and at which stage should it be spent?

Reads, does not change behaviour. For each programme x seed it builds the §12.2
constructive seed (adjacency- and proportion-aware) — whose geometry already sits
at the proportion-aware TARGET ratios (`_size_divisions_from_targets`, the inner
loop's warm-start), so this IS the "before inner loop" state — then runs
`innerloop.optimise` to get the "after inner loop" state, and measures at each:

  1. Per sized-room leaf: achieved area vs target area (get_space_params size),
     classified undersize / at-target / oversize, plus authoritative size-fail
     count from `score_with_fails`.
  2. Plot accounting: total plot area split into sized-room / circulation /
     outside, and the room-target sum vs plot (could rooms even fill the plot?).
  3. Whether the INNER LOOP moves any of it: size fails before vs after, util
     before vs after, oversize leaves before vs after.

DECISION RULE: if rooms are parked at/under target with the slack sitting as
unused plot (rooms can't fill it / no oversize to rebalance) -> fix in
CONSTRUCTION (plot-fill, `erc.4`). If the inner loop has room to expand
(oversize coexists with undersize, slack is inside the sized leaves) but does not
spend it -> no objective gradient -> fix in the INNER LOOP (slack-expansion term,
`erc.6`).

Usage:
  URB_NO_OCCLUSION=1 python3 experiments/diag_slack_localization.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker_layout import (  # noqa: E402
    dom, fitness, geometry, innerloop, operators, programme,
)

PROGRAMMES = ["harbor-house", "maple-court"]
SEEDS = (0, 1, 2)
BUDGET = 80  # constructed bootstrap seeds get child_budget (driver default 80)
AT_TARGET_TOL = 0.10  # |achieved/target - 1| <= tol counts as "at target"
ROOT = Path(__file__).resolve().parents[1]


def _is_sized(leaf, reqs) -> bool:
    return leaf.type in reqs and reqs[leaf.type].size > 0


def _t0(leaf) -> str:
    return leaf.type[0].lower() if leaf.type else ""


def _measure(tree, fit, reqs):
    """Per-leaf achieved-vs-target + plot accounting for one laid-out tree."""
    geometry.clear_cache()
    _score, fails = fit.score_with_fails(copy.deepcopy(tree))
    size_fails = sum(1 for f in fails if f.endswith(" size"))

    leaves = [lf for lvl in dom.levels(tree) for lf in lvl.leaves()]
    geometry.clear_cache()
    plot = sum(geometry.area(lvl) for lvl in dom.levels(tree))

    sized_area = circ_area = out_area = 0.0
    target_sum = 0.0
    under = at = over = 0
    ratios = []
    for lf in leaves:
        a = geometry.area(lf)
        t0 = _t0(lf)
        if _is_sized(lf, reqs):
            target = fit.get_space_params(lf.type, "size")[0]
            sized_area += a
            target_sum += target
            r = a / target if target else float("nan")
            ratios.append(r)
            if r < 1.0 - AT_TARGET_TOL:
                under += 1
            elif r > 1.0 + AT_TARGET_TOL:
                over += 1
            else:
                at += 1
        elif t0 == "c":
            circ_area += a
        else:
            out_area += a

    n_sized = len(ratios)
    return {
        "size_fails": size_fails,
        "plot": plot,
        "sized_area": sized_area,
        "circ_area": circ_area,
        "out_area": out_area,
        "target_sum": target_sum,
        "n_sized": n_sized,
        "util": sized_area / plot if plot else float("nan"),
        "target_fill": target_sum / plot if plot else float("nan"),
        "mean_ratio": float(np.mean(ratios)) if ratios else float("nan"),
        "under": under, "at": at, "over": over,
        "pct_under": 100.0 * under / n_sized if n_sized else float("nan"),
        "pct_over": 100.0 * over / n_sized if n_sized else float("nan"),
    }


def _leaf_ratios(tree, fit, reqs):
    """(a/t, type, target, achieved) for every sized-room leaf."""
    geometry.clear_cache()
    out = []
    for lvl in dom.levels(tree):
        for lf in lvl.leaves():
            if _is_sized(lf, reqs):
                t = fit.get_space_params(lf.type, "size")[0]
                a = geometry.area(lf)
                out.append((a / t if t else float("nan"), lf.type, t, a))
    return out


def _run_seed(pdir, fit, reqs, types, seed_root, s):
    rng = np.random.default_rng(s)
    topo = operators.constructive_topology(
        seed_root, reqs, rng, types,
        adjacency_aware=True, proportion_aware=True, circ_divisor=3)
    before = _measure(topo, fit, reqs)

    after_tree = copy.deepcopy(topo)
    r = innerloop.optimise(after_tree, str(pdir), x0=None, budget=BUDGET,
                           method="nm", use_native=True)
    after = _measure(after_tree, fit, reqs)
    after["n_evals"] = r.n_evals
    return before, after, _leaf_ratios(topo, fit, reqs)


def _avg(rows, key):
    vals = [r[key] for r in rows if not (isinstance(r[key], float) and r[key] != r[key])]
    return sum(vals) / len(vals) if vals else float("nan")


def main() -> int:
    print("Diagnostic B — undersize-despite-slack localization (§13.2)\n")
    print("BEFORE = constructive seed at proportion-aware TARGET ratios "
          "(inner-loop warm start)")
    print(f"AFTER  = after innerloop.optimise (nm, budget={BUDGET})")
    print(f"Seeds: {SEEDS}   at-target tol: +/-{AT_TARGET_TOL:.0%}\n")

    for name in PROGRAMMES:
        pdir = ROOT / "examples" / name
        reqs = programme.load_programme_dir(pdir)
        types = sorted(reqs) + ["C", "O"]
        conf, cost = fitness.load_config(pdir)
        fit = fitness.Fitness(conf, cost)
        seed_root = dom.load(str(pdir / "init.dom"))

        befores, afters = [], []
        detail0 = None
        for s in SEEDS:
            b, a, leaf_rows = _run_seed(pdir, fit, reqs, types, seed_root, s)
            befores.append(b)
            afters.append(a)
            if detail0 is None:
                detail0 = leaf_rows

        n_sized = _avg(befores, "n_sized")
        print(f"=== {name}  (sized rooms/seed: {n_sized:.0f}) ===")
        print(f"{'':16}{'sizeF':>7}{'util':>7}{'tgtFill':>8}{'a/t':>6}"
              f"{'%und':>6}{'%ovr':>6}{'sized%':>7}{'circ%':>7}{'out%':>7}")
        for label, rows in (("BEFORE (target)", befores), ("AFTER (innerloop)", afters)):
            plot = _avg(rows, "plot")
            print(f"{label:16}"
                  f"{_avg(rows,'size_fails'):>7.1f}"
                  f"{_avg(rows,'util'):>7.2f}"
                  f"{_avg(rows,'target_fill'):>8.2f}"
                  f"{_avg(rows,'mean_ratio'):>6.2f}"
                  f"{_avg(rows,'pct_under'):>6.0f}"
                  f"{_avg(rows,'pct_over'):>6.0f}"
                  f"{100*_avg(rows,'sized_area')/plot:>7.0f}"
                  f"{100*_avg(rows,'circ_area')/plot:>7.0f}"
                  f"{100*_avg(rows,'out_area')/plot:>7.0f}")
        print(f"  plot area ~ {_avg(befores,'plot'):.0f} m2;  "
              f"room-target sum ~ {_avg(befores,'target_sum'):.0f} m2  "
              f"(tgtFill = target sum / plot)")
        print(f"  inner-loop evals/seed ~ {_avg(afters,'n_evals'):.0f}")

        # Same-target maldistribution evidence (seed 0): a leaf's area is set by
        # its SLICING POSITION, not its target. The same room TYPE/target lands
        # at both extremes -> depth-driven, not unclaimed plot, not tiny-target.
        detail0.sort(reverse=True)
        print("  seed-0 extremes (type / target / achieved / a-over-t):")
        for r, ty, t, a in detail0[:3]:
            print(f"     OVER  {ty:5} t={t:5.1f} a={a:6.1f} a/t={r:5.2f}")
        for r, ty, t, a in detail0[-3:]:
            print(f"     UNDER {ty:5} t={t:5.1f} a={a:6.1f} a/t={r:5.2f}")
        print()

    print("READ: util = sized-room area / plot.  tgtFill = sum of room targets / plot:")
    print("  if tgtFill << 1, rooms cannot fill the plot even at target -> slack is")
    print("  structurally unassigned (CONSTRUCTION / erc.4).  %ovr>0 alongside %und")
    print("  with AFTER unchanged -> slack is inside leaves but inner loop won't spend")
    print("  it (no gradient -> INNER LOOP / erc.6).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

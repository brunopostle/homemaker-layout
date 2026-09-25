"""What the `support_outside` operator does to the §39.53 layouts, locally.

`homemaker-py-e4r`, DESIGN.md §39.53. The A/B that answers "does it help the
SEARCH" needs the box (`experiments/e4r_support_outside_ab.py`, ~22 core-hours).
This answers the cheaper question that has to come first and that a container
can answer in minutes: **applied to a layout that carries `level N no outside
space`, does one draw of the operator clear it, and what does it cost?**

Protocol, per artefact carrying the fail:

1. score it as committed -- the baseline;
2. draw ``--draws`` children from ``operators.mutate_support_outside``;
3. run the ratio inner loop on each child at the driver's per-child budget,
   because the driver does (warm-vs-cold, `homemaker-py-8cs`, makes Lamarckian
   re-optimisation after every topology move mandatory) and because the
   operator's `place` move cuts at 0.5/0.5, which is a starting point and not
   an answer -- scoring the raw child measures the cut, not the move;
4. report the BEST child by (roof fail, fails, -score), and the median, so one
   lucky draw cannot carry the table.

This is a local-improvement measurement, not an A/B: it says the operator can
reach a better layout from here, which is necessary for the search to benefit
and not sufficient. Do not quote it as evidence that the operator helps.

Usage::

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_e4r_operator.py
    ... --draws 32 --child-budget 80 --glob 'experiments/results/xhw/xhw-*.dom'
"""

from __future__ import annotations

import argparse
import csv
import glob as globmod
import statistics
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
PROGRAMME = REPO / "examples" / "programme-house"
XHW_TABLE = REPO / "experiments" / "results" / "xhw_storey_ab.tsv"
ROOF = "no outside space"


def _score(root, fit):
    import copy
    val, fails = fit.score_with_fails(copy.deepcopy(root))
    return val, [f for f in fails if f.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--glob", default=str(REPO / "experiments/results/xhw/xhw-*.dom"))
    ap.add_argument("--draws", type=int, default=32)
    ap.add_argument("--child-budget", type=int, default=80,
                    help="ratio inner-loop budget per child (driver default: 80)")
    ap.add_argument("--programme", default=str(PROGRAMME))
    args = ap.parse_args()

    from homemaker_layout import dom, fitness, genome, innerloop, operators

    import os
    if os.environ.get("HOMEMAKER_ORTHOGONAL_DIVISION") != "1":
        print("NOTE: HOMEMAKER_ORTHOGONAL_DIVISION is not 1, so these artefacts\n"
              "      are being scored under a different objective than the one\n"
              "      that produced them (CLAUDE.md, `+orth`).\n")
    conf, cost = fitness.load_config(args.programme)
    fit = fitness.Fitness(conf, cost)

    header = (f"{'artefact':22s} {'before':>16s}   {'best child':>16s}  "
              f"{'median':>10s}  move")
    print(f"draws={args.draws}  child_budget={args.child_budget}\n")
    print(header)
    print("-" * len(header))

    n_with_fail = n_cleared = n_no_move = 0
    deltas = []
    for path in sorted(globmod.glob(args.glob)):
        root = genome.decode(genome.encode(dom.load(path)))
        v0, f0 = _score(root, fit)
        if not any(ROOF in f for f in f0):
            continue
        n_with_fail += 1

        rows = []
        for seed in range(args.draws):
            child, desc = operators.mutate_support_outside(
                root, np.random.default_rng(seed), [])
            if "noop" in desc:
                continue
            innerloop.optimise(child, args.programme, budget=args.child_budget)
            v, f = _score(child, fit)
            rows.append((sum(1 for x in f if ROOF in x), len(f), -v, desc))
        if not rows:
            n_no_move += 1
            print(f"{Path(path).stem:22s} {len(f0):3d} fails {v0:7.4f}   "
                  f"{'-- no move available --':>16s}")
            continue
        rows.sort()
        roof, nf, negv, desc = rows[0]
        med = statistics.median(r[1] for r in rows)
        n_cleared += (roof == 0)
        deltas.append(nf - len(f0))
        print(f"{Path(path).stem:22s} {len(f0):3d} fails {v0:7.4f}   "
              f"{nf:3d} fails {-negv:7.4f}  {med:10.1f}  {desc}")

    print()
    print(f"artefacts carrying `{ROOF}`: {n_with_fail}")
    print(f"  the operator offers no move on : {n_no_move}")
    print(f"  best draw clears the fail on   : {n_cleared}")
    if deltas:
        print(f"  fail-count change of that draw : "
              f"median {statistics.median(deltas):+.1f}, "
              f"range {min(deltas):+d}..{max(deltas):+d}")
    print("\nLocal reachability only. Whether the SEARCH benefits is "
          "experiments/e4r_support_outside_ab.py, which needs the box.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

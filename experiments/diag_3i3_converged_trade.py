"""`homemaker-py-3i3` (b): what did the search trade a missing room FOR?

§39.80 found no converged artefact omitting a required room. The `07b2058+orth`
sweep produced one: maple-court s1 is missing `r#1`, one of twelve resident
rooms on level 2. This asks whether the omission was the objective's choice or
the search's failure, by trying every cheap way to put the room back:

  retype   each cell on the room's level, retyped to the missing code
  split    each cell on that level halved (three ratios, four rotations), one
           half given the missing code -- the move `mutate_divide` makes

and printing the best of each, with the fails it removes and adds and their
tier. If something beats the artefact, the search missed it; if the best is
score-neutral, the objective is INDIFFERENT between the omission and what
including the room costs on this topology, and that indifference is the base
magnitude §39.80 left open, priced on a real case (DESIGN.md §39.83).

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_3i3_converged_trade.py
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from homemaker_layout import dom, geometry, operators  # noqa: E402
from homemaker_layout.fitness import (Fitness, classify_fail_tier,  # noqa: E402
                                      load_config)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--programme", default="maple-court")
    ap.add_argument("--dom", default="coldstart-07b2058+orth-500000-s1.dom")
    ap.add_argument("--code", default="r", help="the missing room code")
    ap.add_argument("--level", type=int, default=2, help="the level it belongs on")
    args = ap.parse_args(argv)

    geometry.ORTHOGONAL_DIVISION = True
    prog = REPO / "examples" / args.programme
    conf, cost = load_config(str(prog))

    def score(root):
        geometry.clear_cache()
        s, f = Fitness(conf, cost).score_with_fails(copy.deepcopy(root))
        geometry.clear_cache()
        return s, f

    def cells(root):
        return [l for lv in dom.levels(root) for l in lv.leaves()
                if dom.level_of(l) == args.level]

    base = dom.load(str(prog / args.dom))
    dom.link(base)
    s0, f0 = score(base)
    missing = [f for f in f0 if f.startswith("missing required space:")
               and not f.endswith("(critical)")]
    print(f"{args.programme}/{args.dom}: score {s0:.4g}, {len(f0)} fails; "
          f"missing: {missing or 'nothing'}\n")

    def edit(i, how):
        child = copy.deepcopy(base)
        dom.link(child)
        leaf = cells(child)[i]
        how(leaf)
        return operators._finalise(child)

    n = len(cells(base))
    trials = []
    for i in range(n):
        t = cells(base)[i].type
        if t != args.code:
            def retype(leaf):
                leaf.type = args.code
            trials.append(("retype", f"{t}->{args.code}", cells(base)[i].id,
                           edit(i, retype)))
        for rot in range(4):
            for div in ([0.5, 0.5], [0.35, 0.65], [0.65, 0.35]):
                def split(leaf, rot=rot, div=div):
                    keep = leaf.type
                    leaf.division, leaf.rotation = list(div), rot
                    leaf.left, leaf.right = dom.Node(type=keep), dom.Node(type=args.code)
                    leaf.type = None
                trials.append(("split", f"{t}+{args.code} rot{rot} {div}",
                               cells(base)[i].id, edit(i, split)))

    best = {}
    for kind, desc, cid, child in trials:
        s, f = score(child)
        if kind not in best or s > best[kind][0]:
            best[kind] = (s, f, desc, cid)
    for kind in ("retype", "split"):
        if kind not in best:
            continue
        s, f, desc, cid = best[kind]
        beat = sum(1 for k, *_ in trials if k == kind)
        print(f"best {kind} of {beat}: {args.level}/{cid} {desc}: x{s / s0:.3g}, "
              f"{len(f) - len(f0):+d} fails")
        for sign, fs in (("-", sorted(set(f0) - set(f))), ("+", sorted(set(f) - set(f0)))):
            for x in fs:
                print(f"    {sign} {x}  [{classify_fail_tier(x)}]")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""`mutate_repair_shaft` measured: what does giving the staircase back buy?

DESIGN.md §39.73 counted the damage (seven live operators leave a building with no
vertical shaft, 12 of 48 artefacts are in that state) and left `homemaker-py-t7q`'s
decision open: guard the seven, or repair after them. A guard REMOVES moves and
needs the A/B that needs the box; a repair ADDS one, so it can be measured here.

This scores every corpus artefact with no intact shaft, applies the repair, and
scores it again -- each artefact under its own objective's orthogonal-division
setting. It also checks the operator is silent everywhere else: the whole point of
firing only on the x0.0225 state is that it cannot mint a second staircase past
`staircase_max`.

    python experiments/diag_t7q_repair.py [--draws 4]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from homemaker_layout import dom, genome, geometry, innerloop, operators  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402
from homemaker_layout.fitness_cmd import load_config  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("harbor-house", "health-centre", "maple-court", "programme-house")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=4)
    ap.add_argument("--solve", type=int, default=0, metavar="BUDGET",
                    help="inner-loop evaluations for BOTH arms before scoring -- "
                         "the fair comparison, since every child a search "
                         "evaluates has had its ratios solved (the cut leaves "
                         "soft width/crinkliness fails that are exactly what the "
                         "ratio loop exists to clear)")
    args = ap.parse_args(argv)

    fired = declined = silent = 0
    print(f"{'artefact':44s} {'before':>14s} {'after':>14s}   ratio  cleared")
    for prog_name in PROGRAMMES:
        prog = REPO / "examples" / prog_name
        conf, cost = load_config(prog)
        types = ["C", "O"]
        for path in sorted(prog.glob("coldstart-*.dom")):
            geometry.ORTHOGONAL_DIVISION = "+orth" in path.name
            fitness = Fitness(conf, cost)
            root = genome.decode(genome.encode(dom.load(str(path))))
            geometry.clear_cache()
            lvls = dom.levels(root)
            if len(lvls) < 2 or operators._shaft_paths(lvls):
                # must be a noop: there is a shaft, or there is no stack at all
                for seed in range(args.draws):
                    _c, desc = operators.mutate_repair_shaft(
                        root, np.random.default_rng(seed), types)
                    assert "noop" in desc, f"{path.name}: fired where it must not: {desc}"
                silent += 1
                continue

            if args.solve:
                res = innerloop.optimise(root, str(prog), budget=args.solve,
                                         method="nm")
                before_score, before_fails = res.fitness, res.fail_lines
            else:
                before_score, before_fails = fitness.score_with_fails(root)
            best = None
            for seed in range(args.draws):
                child, desc = operators.mutate_repair_shaft(
                    root, np.random.default_rng(seed), types)
                if "noop" in desc:
                    continue
                geometry.clear_cache()
                if args.solve:
                    res = innerloop.optimise(child, str(prog), budget=args.solve,
                                             method="nm")
                    score, fails = res.fitness, res.fail_lines
                else:
                    score, fails = fitness.score_with_fails(child)
                key = (-len(fails), score)
                if best is None or key > best[0]:
                    best = (key, score, fails, desc, child)
            label = f"{prog_name[:13]}/{path.name.replace('coldstart-', '')[:30]}"
            if best is None:
                declined += 1
                print(f"{label:44s} {before_score:14.6g} {'(declined)':>14s}")
                continue
            fired += 1
            _key, after_score, after_fails, desc, child = best
            cleared = sorted(set(before_fails) - set(after_fails))
            added = sorted(set(after_fails) - set(before_fails))
            ratio = after_score / before_score if before_score else float("inf")
            print(f"{label:44s} {before_score:14.6g} {after_score:14.6g} "
                  f" x{ratio:<8.3g} {len(before_fails)}f->{len(after_fails)}f  {desc}")
            if cleared:
                print(f"{'':44s}   clears: {cleared}")
            if added:
                print(f"{'':44s}   ADDS:   {added}")
            assert operators._shaft_paths(dom.levels(child)), "no shaft after repair"

    geometry.ORTHOGONAL_DIVISION = False
    print(f"\n  fired on {fired}, declined on {declined}, silent (nothing to "
          f"repair) on {silent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

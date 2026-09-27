"""`homemaker-py-v2k` acceptance step 1: can ONE move reach a fail-free 3 storeys?

DESIGN.md §39.70 measured the far side of the storey-count valley by hand: a
3-storey programme-house scores 0.416206 with zero fails where the best of twelve
evolved runs scores 0.220122 with one. `mutate_level_add` cannot get there --
it duplicates the top storey EMPTY, which costs 60-98% of the parent's score
before a single room can follow it up, and 35 of 36 corpus artefacts sit at their
programme's `storey_minimum` as a result.

`operators.mutate_level_add_migrate` is the compound move that tries. This asks
the bead's first acceptance question, which needs no search box: from each
committed 2-storey artefact, do N draws of the operator reach a THREE-storey
layout with NO fails, and what does it score once its ratios are solved the way
any child's would be?

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_v2k_migrate.py
    ... --draws 12 --budget 4000 --programme harbor-house

The second acceptance question -- what the operator does to a SEARCH -- is an
A/B at a real budget and cannot be answered in a container.

Read the columns as reachability, not as an average: in a search a child that
scores worse than its parent is simply rejected, so what matters is whether the
good state is reached at all, and how often. A row that never reaches it says the
operator is not aimed at that artefact's problem (`1138ff1+orth` s1 fails
`level 0 no outside space` -- a GROUND-floor garden -- which no amount of storeys
above it repairs).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from homemaker_layout import dom, genome, geometry, innerloop, operators, programme  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402
from homemaker_layout.fitness_cmd import load_config  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# programme-house's `+orth` corpora: the objective the artefacts were evolved
# under and the switch state §39.70's comparison uses.
ARTEFACTS = tuple(f"coldstart-{stamp}+orth-500000-s{seed}.dom"
                  for stamp in ("1138ff1", "c836457") for seed in (0, 1, 2))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--programme", default="programme-house")
    ap.add_argument("--draws", type=int, default=12)
    ap.add_argument("--budget", type=int, default=4000,
                    help="inner-loop evaluations for the winning child's ratios")
    args = ap.parse_args(argv)

    prog = REPO / "examples" / args.programme
    conf, cost = load_config(prog)
    fit = Fitness(conf, cost)
    reqs = programme.load_programme_dir(str(prog))
    types = sorted(reqs) + ["C", "O"]
    if not geometry.ORTHOGONAL_DIVISION:
        print("note: HOMEMAKER_ORTHOGONAL_DIVISION is unset, so these artefacts "
              "are being scored under a geometry they were not evolved for "
              "(§39.12 clause 3)", file=sys.stderr)

    def score(root):
        geometry.clear_cache()
        return fit.score_with_fails(root)

    names = [n for n in ARTEFACTS if (prog / n).is_file()] or \
        sorted(p.name for p in prog.glob("coldstart-*.dom"))
    print(f"{'artefact':38s} {'parent':>17s} {'best of N draws':>19s} "
          f"{'+ ratio solve':>19s}   fail-free")
    for name in names:
        root = genome.decode(genome.encode(dom.load(str(prog / name))))
        p_score, p_fails = score(root)
        best = None
        clean = 0
        for seed in range(args.draws):
            child, desc = operators.mutate_level_add_migrate(
                root, np.random.default_rng(seed), types, reqs=reqs)
            if "noop" in desc:
                continue
            c_score, c_fails = score(child)
            if not c_fails:
                clean += 1
            # rank as the search would: fewer fails first, then fitness
            key = (-len(c_fails), c_score)
            if best is None or key > best[0]:
                best = (key, c_score, len(c_fails), child, desc)
        if best is None:
            print(f"{name:38s} {p_score:11.6g} {len(p_fails):2d}f"
                  f"       (noop on every draw)")
            continue
        res = innerloop.optimise(best[3], str(prog), budget=args.budget,
                                 method="nm")
        print(f"{name:38s} {p_score:11.6g} {len(p_fails):2d}f "
              f"{best[1]:15.6g} {best[2]:2d}f {res.fitness:15.6g} "
              f"{res.n_fails:2d}f   {clean:2d}/{args.draws}"
              f"  ({len(dom.levels(root))}->{len(dom.levels(best[3]))} storeys)")
        if res.fail_lines:
            print(f"{'':38s}   remaining: {list(res.fail_lines)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

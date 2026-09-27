"""`mutate_repair_shaft` measured: what does giving the staircase back buy?

DESIGN.md §39.73 counted the damage (seven live operators leave a building with no
vertical shaft, 12 of 48 artefacts are in that state) and left `homemaker-py-t7q`'s
decision open: guard the seven, or repair after them. A guard REMOVES moves and
needs the A/B that needs the box; a repair ADDS one, so it can be measured here.

Two modes.

DEFAULT: score every corpus artefact with no intact shaft, apply the repair, score
it again -- each artefact under its own objective's orthogonal-division setting. It
also checks the operator is silent everywhere else: the whole point of firing only
on the x0.0225 state is that it cannot mint a second staircase past
`staircase_max`.

``--from-broken``: the realistic population. A converged artefact that ENDED
shaft-less is the least favourable place to cut a shaft back in; mid-search the
state is a CHILD whose shaft an operator just broke, a few mutations from a layout
that had one. So: break the shaft with each of the live operators that can
(§39.73's census), then try the repair on what comes out. It runs two arms --
with the subdivision step and without it -- which isolates what §39.75's
`_open_address` buys, since a freshly broken shaft is usually broken by a MERGE and
the pre-§39.75 repair had no answer to that at all.

    python experiments/diag_t7q_repair.py [--draws 4] [--solve 3000]
    python experiments/diag_t7q_repair.py --from-broken
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


# The live operators §39.73 measured emptying a shaft, worst first.
BREAKERS = ("swap", "undivide", "level_retype", "support_outside", "divide",
            "retype")


def _no_subdivision(lvl, path, below):
    """`operators._open_address` as it behaved before §39.75: merged is a dead end."""
    node = lvl
    for ch in path:
        if not node.divided:
            return None
        node = node.left if ch == "l" else node.right
    return None if node.divided else (node, 0)


def from_broken(draws: int) -> int:
    """Repair children whose shaft an operator just broke, with and without
    the subdivision step."""
    import inspect

    import statistics

    saved = operators._open_address
    totals = {"with": [0, 0], "without": [0, 0]}   # [restored, fired]
    ratios: dict = {"with": [], "without": []}     # repaired / broken score
    broken = 0
    for prog_name in PROGRAMMES:
        prog = REPO / "examples" / prog_name
        reqs_ = __import__("homemaker_layout.programme", fromlist=["x"])
        reqs = reqs_.load_programme_dir(str(prog))
        conf, cost = load_config(prog)
        types = sorted(reqs) + ["C", "O"]
        for path in sorted(prog.glob("coldstart-*.dom")):
            geometry.ORTHOGONAL_DIVISION = "+orth" in path.name
            fitness = Fitness(conf, cost)
            root = genome.decode(genome.encode(dom.load(str(path))))
            geometry.clear_cache()
            if not operators._shaft_paths(dom.levels(root)):
                continue
            for name in BREAKERS:
                op = operators.MUTATIONS[name]
                kw = {}
                if "reqs" in inspect.signature(op).parameters:
                    kw["reqs"] = reqs
                for seed in range(draws):
                    geometry.clear_cache()
                    hurt, _d = op(root, np.random.default_rng(seed), types, **kw)
                    geometry.clear_cache()
                    if operators._shaft_paths(dom.levels(hurt)):
                        continue
                    broken += 1
                    base_score, base_fails = fitness.score_with_fails(hurt)
                    for arm in ("with", "without"):
                        operators._open_address = (saved if arm == "with"
                                                   else _no_subdivision)
                        try:
                            for rseed in range(2):
                                geometry.clear_cache()
                                fixed, desc = operators.mutate_repair_shaft(
                                    hurt, np.random.default_rng(rseed), types)
                                if "noop" in desc:
                                    continue
                                totals[arm][1] += 1
                                geometry.clear_cache()
                                if operators._shaft_paths(dom.levels(fixed)):
                                    totals[arm][0] += 1
                                score, _f = fitness.score_with_fails(fixed)
                                if base_score > 0:
                                    ratios[arm].append(score / base_score)
                                break
                        finally:
                            operators._open_address = saved
    geometry.ORTHOGONAL_DIVISION = False
    print(f"{broken} children with a broken shaft, from {len(BREAKERS)} operators "
          f"x {draws} draws over every artefact that had one\n")
    for arm in ("with", "without"):
        restored, fired = totals[arm]
        share = 100.0 * restored / broken if broken else 0.0
        rs = ratios[arm]
        med = statistics.median(rs) if rs else 0.0
        wins = sum(1 for r in rs if r > 1.0)
        print(f"  repair {arm + ' subdivision':22s} fired on {fired:4d}, "
              f"restored a shaft on {restored:4d}  ({share:4.1f}% of broken)")
        print(f"  {'':29s} vs the broken child: median x{med:.3g}, "
              f"better in {wins}/{len(rs)}"
              f"  (best x{max(rs, default=0):.3g})")
    print("\n  `base_score` is the child the breaking operator produced, so a ratio "
          "above 1\n  means repairing it beat leaving it broken. Raw scores, no "
          "ratio solve: both\n  arms are treated identically, and mid-search a "
          "child gets solved either way.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=4)
    ap.add_argument("--solve", type=int, default=0, metavar="BUDGET",
                    help="inner-loop evaluations for BOTH arms before scoring -- "
                         "the fair comparison, since every child a search "
                         "evaluates has had its ratios solved (the cut leaves "
                         "soft width/crinkliness fails that are exactly what the "
                         "ratio loop exists to clear)")
    ap.add_argument("--from-broken", action="store_true",
                    help="repair children whose shaft an operator just broke, "
                         "with and without the subdivision step")
    args = ap.parse_args(argv)

    if args.from_broken:
        return from_broken(args.draws)

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

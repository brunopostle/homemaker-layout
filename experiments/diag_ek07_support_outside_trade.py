"""`homemaker-py-ek07`: what does `support_outside` trade the terrace FOR?

DESIGN.md §39.81: across 36 paired seeds the operator cleared `no outside
space` in all seven discordant pairs, yet score and total fails were a wash --
the arm that cleared the fail ended with a size or width fail instead. Those
were independent 500k-eval trajectories, so they say what the search ENDS with,
not what one application of the operator costs. This measures the latter.

For every arm-A (operator off) artefact that still carries the fail, it draws
the operator repeatedly and evaluates each child the way the search does --
`driver._evaluate`, the parent's ratios carried over, `child_budget` inner-loop
evals -- and reports, per sub-move (`place` / `swap` / `underbuild`):

  cleared    the outdoor-space fail is gone after the inner loop
  added      the fail families the child gained, after the inner loop
  better     the child outscores its parent (the search would keep it)

and the same with `mutate_bridge_circulation` applied after the move, the
follow-up the operator's docstring relies on to clear the access fail it can
cause -- which the searches in §39.81 ran with switched OFF.

Parents are the arm-A artefacts that carry the fail when scored TODAY, from
either A/B (`--source flat tiers`); §39.93 is the re-run at 2.3 m.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_ek07_support_outside_trade.py
"""

from __future__ import annotations

import argparse
import collections
import copy
import csv
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402

from homemaker_layout import dom, driver, geometry, innerloop, operators, programme  # noqa: E402

PROG = REPO / "examples" / "programme-house"
# Where the arm-A artefacts of each A/B live: §39.81's flat run (07b2058+orth),
# §39.91's --use-tiers run (59d8aa1+orth), and any --tag run beside them.
RESULTS = REPO / "experiments" / "results"
SOURCES = {"flat": ("e4r", "e4r_support_outside_ab.tsv"),
           "tiers": ("e4r-tiers", "e4r_support_outside_ab_tiers.tsv")}
ROOF = "no outside space"
# the search config both §39.81 arms used (search_configs/4549a418fc.json)
SEARCH = dict(leaf_sharing=True, collapse_insearch=True)
CHILD_BUDGET = 80


def family(f: str) -> str:
    if f.startswith("missing"):
        return "missing room"
    if ROOF in f:
        return ROOF
    f = re.sub(r"^\d+/\S+ ", "", f)            # leaf id
    f = re.sub(r"^\([^)]*\) ", "", f)           # (code)
    f = re.sub(r"\blevel \d+\b", "level N", f)
    return re.sub(r"^\d+ ", "N ", f)


def evaluate(root, parent_ratios):
    """Score `root` as the search would score a child of a parent with
    `parent_ratios`: carried ratios, warm start, child_budget evals."""
    root = copy.deepcopy(root)
    # as the driver does: a cut the parent did not have keeps the operator's
    # ratio (`new_splits`), every surviving cut inherits the parent's
    ratios = {**innerloop.ratio_map(root), **parent_ratios}
    x0 = innerloop.warm_x0(root, ratios)
    ind, _ = driver._evaluate(root, str(PROG), x0, CHILD_BUDGET, {}, "ek07",
                              **SEARCH)
    geometry.clear_cache()
    _, fails = driver._fitness_for(str(PROG), **SEARCH).score_with_fails(
        copy.deepcopy(ind.root))
    geometry.clear_cache()
    return ind.fitness, fails


def parents(sources) -> "list[tuple[str, str, Path]]":
    """(source, seed, path) of every arm-A artefact that carries the fail WHEN
    SCORED NOW. The A/B tables record it at the objective each run was made at
    -- §39.87 has since narrowed the outdoor width from 3.0 m to 2.3 m -- so
    the table's `roof_fail` column is the wrong thing to select on."""
    fit, out = driver._fitness_for(str(PROG), **SEARCH), []
    for src in sources:
        name, table = SOURCES.get(src, (src, None))
        d = RESULTS / name
        doms = sorted(d.glob("e4r-armA-s*.dom"),
                      key=lambda q: int(q.stem.rsplit("-s", 1)[1]))
        if not doms:
            raise SystemExit(f"no arm-A artefacts in {d}")
        was = {r["seed"] for r in csv.DictReader((RESULTS / table).open(),
                                                 delimiter="\t")
               if r["arm"] == "armA" and r["roof_fail"] == "1"} if table else set()
        now = set()
        for q in doms:
            root = dom.load(str(q))
            dom.link(root)
            _, fails = fit.score_with_fails(root)
            geometry.clear_cache()
            if any(ROOF in f for f in fails):
                seed = q.stem.rsplit("-s", 1)[1]
                now.add(seed)
                out.append((src, seed, q))
        note = ""
        if table and was != now:
            note = (f"  (its table says {len(was)}: "
                    f"no longer {sorted(was - now, key=int)}, "
                    f"newly {sorted(now - was, key=int)})")
        print(f"{src}: {len(now)} of {len(doms)} arm-A artefacts carry "
              f"`{ROOF}` at today's objective{note}")
    print()
    return out


def exhaustive(sources) -> int:
    seeds = parents(sources)
    print(f"every `place` cut on the {len(seeds)} arm-A artefacts carrying `{ROOF}`\n")
    print(f"{'seed':>5} {'cuts':>5} {'clear':>6} {'win':>4}  {'parent':>9} {'best cut':>9}"
          f"  best cut's fails gained / lost")
    wins = 0
    for src, seed, path in seeds:
        seed_label = f"{src[0]}{seed}"
        parent = dom.load(str(path))
        dom.link(parent)
        ratios = innerloop.ratio_map(parent)
        p_score, p_fails = evaluate(parent, ratios)
        n = cleared = won = 0
        best = None
        for li, _ in operators._levels_without_outdoor(parent):
            lvls = dom.levels(parent)
            shaft = operators._shaft_cells(lvls)
            slots = [i for i, lf in enumerate(lvls[li].leaves())
                     if not dom.is_outside(lf) and not any(lf is c for c in shaft)
                     and operators._can_carry_terrace(lf, li, lvls)]
            for i in slots:
                for rot in range(4):
                    for side in (0, 1):
                        for r in (0.25, 0.5, 0.75):
                            child = copy.deepcopy(parent)
                            dom.link(child)
                            t = dom.levels(child)[li].leaves()[i]
                            kept = t.type
                            t.division, t.rotation = [r, 1 - r], rot
                            t.left = dom.Node(type="O" if side else kept)
                            t.right = dom.Node(type=kept if side else "O")
                            t.type = None
                            child = operators._finalise(child)
                            s, f = evaluate(child, ratios)
                            n += 1
                            ok = not any(ROOF in x for x in f)
                            cleared += ok
                            won += ok and s > p_score
                            if ok and (best is None or s > best[0]):
                                best = (s, f, f"{li}/{t.id} rot{rot} side{side} {r}")
        wins += won > 0
        if best is None:
            print(f"{seed_label:>5} {n:5d}   no cut clears the fail")
            continue
        gained = sorted((collections.Counter(map(family, best[1]))
                         - collections.Counter(map(family, p_fails))).elements())
        lost = sorted((collections.Counter(map(family, p_fails))
                       - collections.Counter(map(family, best[1]))).elements())
        print(f"{seed_label:>5} {n:5d} {cleared:6d} {won:4d}  {p_score:9.4f} {best[0]:9.4f}"
              f"  +{gained} -{lost}  ({best[2]})")
        # the raw lines, because WHOSE width fails is the finding (§39.86: the
        # new terrace's own) and a family name cannot say
        for line in sorted(set(best[1]) - set(p_fails)):
            print(f"{'':>11}{line}")
    print(f"\nartefacts where at least one single cut beats the parent: {wins} of {len(seeds)}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=12,
                    help="operator draws per artefact (default 12)")
    ap.add_argument("--exhaustive", action="store_true",
                    help="instead of random draws, try EVERY place cut (eligible "
                         "leaf x 4 rotations x 2 sides x ratios 1/4,1/2,3/4) and "
                         "report the best per artefact: does ANY single cut win?")
    ap.add_argument("--source", nargs="+", default=["flat"],
                    help="which A/B's arm-A artefacts to use: flat (results/e4r, "
                         "the default), tiers (results/e4r-tiers), or any other "
                         "directory name under experiments/results. Several may "
                         "be given; seeds are then prefixed f/t in the table.")
    args = ap.parse_args(argv)
    geometry.ORTHOGONAL_DIVISION = True
    if args.exhaustive:
        return exhaustive(args.source)

    reqs = programme.load_programme_dir(str(PROG))
    types = sorted(reqs) + ["C", "O"]
    seeds = parents(args.source)
    print(f"{len(seeds)} arm-A artefacts carry `{ROOF}`; "
          f"{args.draws} draws each, child_budget {CHILD_BUDGET}\n")

    stats = collections.defaultdict(lambda: collections.defaultdict(list))
    for _, seed, path in seeds:
        parent = dom.load(str(path))
        dom.link(parent)
        ratios = innerloop.ratio_map(parent)
        p_score, p_fails = evaluate(parent, ratios)
        rng = np.random.default_rng(int(seed))
        for _ in range(args.draws):
            child, desc = operators.mutate_support_outside(parent, rng, types)
            move = desc.split()[1] if len(desc.split()) > 1 else "noop"
            if move == "noop":
                stats[move]["n"].append(1)
                continue
            bridged, bdesc = operators.mutate_bridge_circulation(
                child, rng, types, reqs=reqs)
            stats["bridge fired"]["n"].append("noop" not in bdesc)
            arms = [("alone", child)]
            if "noop" not in bdesc:   # an idle bridge would only duplicate `alone`
                arms.append(("+bridge", bridged))
            for arm, root in arms:
                s, fails = evaluate(root, ratios)
                st = stats[f"{move} {arm}"]
                st["n"].append(1)
                st["cleared"].append(not any(ROOF in f for f in fails))
                st["better"].append(s > p_score)
                st["delta"].append(len(fails) - len(p_fails))
                gained = collections.Counter(map(family, fails)) - \
                    collections.Counter(map(family, p_fails))
                st["added"].append(gained)

    print(f"{'move':22} {'n':>4} {'cleared':>8} {'better':>7} {'d fails':>8}  "
          "families gained (per child)")
    for key in sorted(stats):
        st = stats[key]
        n = len(st["n"])
        if key == "noop":
            print(f"{key:22} {n:4d}   (no eligible move)")
            continue
        if key == "bridge fired":
            print(f"{key:22} {n:4d}   bridge_circulation acted on "
                  f"{np.mean(st['n']):.0%} of children")
            continue
        added = sum(st["added"], collections.Counter())
        top = ", ".join(f"{k} {v / n:.2f}" for k, v in added.most_common(5))
        print(f"{key:22} {n:4d} {np.mean(st['cleared']):8.0%} "
              f"{np.mean(st['better']):7.0%} {np.mean(st['delta']):+8.2f}  {top}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

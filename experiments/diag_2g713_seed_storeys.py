"""`homemaker-py-2g7.13` step 1: is a three-storey seed a better start?

DESIGN.md §39.142: seeded from the owner's drawing (three storeys, two cores),
harbor-house ends at 10 / 12 / 5 fails; cold, at 28 / 24 / 37, and every cold
design has two storeys. The constructor builds a seed with
``max(highest level:, storey_minimum)`` storeys -- two for harbor-house -- so
a cold run starts at two and can reach three only through `level_add`, which
arrives empty (§39.134).

This asks the first question without a search: build constructor seeds at two
and at three storeys from the same random streams, give each the same short
inner-loop tune every seed gets, and compare their fails with the owner's
drawing tuned the same way. A seed is not a design; what this can show is
whether the three-storey start is at least no worse, which is what a search
A/B on the box would then need.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_2g713_seed_storeys.py
    ... --seeds 6 --budget 600 --storeys 2 3

Seeds are built with the default search's constructor settings except
`leaf_sharing`, which is off here so a seed is scored as itself rather than
through the shared-leaf relaxation; both arms are treated the same.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from homemaker_layout import dom, driver, geometry, innerloop, operators, programme  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402
from homemaker_layout.fitness_cmd import load_config  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

CONSTRUCTOR_KEYS = {
    "seed_adjacency_aware": "adjacency_aware",
    "seed_proportion_aware": "proportion_aware",
    "circ_divisor": "circ_divisor",
    "depth_balanced": "depth_balanced",
    "interior_outside": "interior_outside",
    "outside_divisor": "outside_divisor",
    "construction_beam_width": "construction_beam_width",
    "multi_use": "multi_use",
    "assign_solver": "assign_solver",
    "preserve_circulation": "preserve_circulation",
}


def constructor_kwargs() -> dict:
    """The default search's constructor settings, read off `driver.search`."""
    sig = inspect.signature(driver.search)
    kw = {ours: sig.parameters[theirs].default
          for theirs, ours in CONSTRUCTOR_KEYS.items()}
    kw["leaf_sharing"] = False
    return kw


def rng_for(*parts) -> np.random.Generator:
    h = hashlib.sha1("|".join(map(str, parts)).encode()).digest()
    return np.random.default_rng(int.from_bytes(h[:8], "big"))


def family(fail: str) -> str:
    parts = fail.split()
    if "/" in parts[0]:
        parts = parts[1:]
        if parts and parts[0].startswith("("):
            parts = parts[1:]
    elif parts[0].isdigit():
        parts = parts[1:]
    text = " ".join(parts)
    for key in ("level", "too few stairs", "not adjacent to"):
        if text.startswith(key):
            return key
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", default="harbor-house")
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--budget", type=int, default=600,
                    help="inner-loop evaluations per seed (the search gives 200)")
    ap.add_argument("--storeys", type=int, nargs="+", default=[2, 3])
    ap.add_argument("--hand", default="hand2a.dom",
                    help="a hand design in the programme's folder, tuned alike")
    args = ap.parse_args(argv)
    if not geometry.ORTHOGONAL_DIVISION:
        print("set HOMEMAKER_ORTHOGONAL_DIVISION=1", file=sys.stderr)
        return 2

    prog = REPO / "examples" / args.programme
    conf, cost = load_config(prog)
    fit = Fitness(conf, cost)
    reqs = programme.load_programme_dir(str(prog))
    types = sorted(reqs) + ["C", "O"]
    init = dom.load(str(prog / "init.dom"))
    kw = constructor_kwargs()

    def tuned(root):
        geometry.clear_cache()
        raw = len(fit.score_with_fails(root)[1])
        res = innerloop.optimise(root, str(prog), budget=args.budget, method="nm")
        geometry.clear_cache()
        _s, fails = fit.score_with_fails(root)
        return raw, res.fitness, list(fails)

    rows = {}
    for n in args.storeys:
        rows[n] = []
        for s in range(args.seeds):
            root = operators.constructive_topology(
                init, reqs, rng_for(args.programme, s), types,
                min_storeys=n, **kw)
            stairs = len(operators._shaft_feet(dom.levels(root)))
            raw, score, fails = tuned(root)
            rows[n].append((raw, len(fails), score, stairs,
                            len(dom.levels(root)), fails))
            print(f"  {n} storeys, seed {s}: {len(dom.levels(root))} storeys, "
                  f"{stairs} stair shaft(s), {raw} fails raw -> "
                  f"{len(fails)} tuned, score {score:.3g}", flush=True)

    hand = None
    if args.hand and (prog / args.hand).is_file():
        root = dom.load(str(prog / args.hand))
        raw, score, fails = tuned(root)
        hand = (raw, len(fails), score, fails)

    print(f"\n{args.programme}: {args.seeds} seeds per arm, "
          f"{args.budget} inner-loop evaluations each")
    for n, rs in rows.items():
        tuned_fails = [r[1] for r in rs]
        fam = Counter(family(f) for r in rs for f in r[5])
        print(f"  {n} storeys asked: built {Counter(r[4] for r in rs)}, "
              f"raw {statistics.mean(r[0] for r in rs):.1f}, "
              f"tuned {statistics.mean(tuned_fails):.1f} "
              f"(min {min(tuned_fails)}, max {max(tuned_fails)}), "
              f"stairs {Counter(r[3] for r in rs)}")
        print("      " + ", ".join(f"{k} {v / len(rs):.1f}"
                                   for k, v in fam.most_common(8)))
    if len(args.storeys) == 2:
        a, b = args.storeys
        d = [x[1] - y[1] for x, y in zip(rows[a], rows[b])]
        print(f"  paired by stream, {a} minus {b} storeys: mean {statistics.mean(d):+.1f}, "
              f"{sum(x > 0 for x in d)} better at {b} / {sum(x < 0 for x in d)} worse")
    if hand:
        fam = Counter(family(f) for f in hand[3])
        print(f"  {args.hand}: raw {hand[0]} -> tuned {hand[1]}, score {hand[2]:.3g}; "
              + ", ".join(f"{k} {v}" for k, v in fam.most_common(8)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

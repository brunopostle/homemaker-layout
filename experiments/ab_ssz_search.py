"""Fixed-budget search A/B for the crinkliness modes (`homemaker-py-ssz`).

DESIGN.md §38.6 A/B'd the modes against the §38.2 *deletion test*, which has
since been retracted, and it used the pre-§39.4 `type[:1] in ("C","O")` prefix
rule that mislabels programme rooms as circulation. So the modes have never
been measured against what `ssz`'s acceptance criteria actually asks for: a
fixed-budget search, hard/soft fail split, on harbor-house and maple-court.

**The scoring discipline is the point of this script.** `compact_ok`,
`exempt_circulation` and `usage_daylight` all return 1.0 for leaves that stock
scores below FAIL_THRESHOLD, so scoring an arm under its own objective deletes
a fail category for free and every arm "wins". Two numbers are therefore
reported per arm:

  urb    the arm's final layout re-scored under the STOCK objective. This is
         the comparable yardstick, and the one that answers "did optimising
         under this variant steer the search to a better building?"
  own    the same layout under the arm's own objective. Lower than `urb` by
         construction for the permissive modes; it is reported only so the
         size of the definitional discount is visible, never as the result.

A mode passes on `urb`, not on `own`.

Usage::

    python experiments/ab_ssz_search.py --budget 3000 --seeds 3
    python experiments/ab_ssz_search.py --modes urb usage_daylight --seeds 2
"""

from __future__ import annotations

import argparse
import collections
import copy
import csv
import time
from pathlib import Path

from homemaker_layout import dom as dom_mod
from homemaker_layout import driver, fitness

CORPUS = ["examples/harbor-house", "examples/maple-court"]
MODES = ["urb", "floor", "compact_ok", "exempt_circulation", "usage_daylight"]


def _with_mode(mode: str):
    """Patch `fitness.load_config` so every evaluator built during the run --
    the driver's, the inner loop's, the seeder's -- sees `crinkliness_mode`.

    `driver.search` has no parameter for it, and `driver._fitness_for` is
    lru_cached on its arguments, so the cache is cleared around the patch or a
    later arm would silently reuse the previous arm's evaluator.
    """
    orig = fitness.load_config

    def patched(directory, overrides=None):
        ov = dict(overrides or {})
        ov["crinkliness_mode"] = mode
        return orig(directory, overrides=ov)

    return orig, patched


def tiers(fails) -> tuple[int, int]:
    c = collections.Counter(fitness.classify_fail_tier(f) for f in fails)
    return c["hard"], c["soft"]


def run_arm(progdir: str, seed: int, mode: str, budget: int,
            child_budget: int) -> dict:
    orig, patched = _with_mode(mode)
    fitness.load_config = patched
    driver._fitness_for.cache_clear()
    t0 = time.perf_counter()
    try:
        res = driver.search(
            dom_mod.load(f"{progdir}/init.dom"), progdir,
            budget=budget, seed=seed, child_budget=child_budget, n_workers=1)
        root = copy.deepcopy(res.best.root)
        own_conf, own_cost = patched(progdir, overrides={"leaf_sharing": True,
                                                         "collapse_insearch": True})
        _, own_fails = fitness.Fitness(own_conf, own_cost).score_with_fails(
            copy.deepcopy(root))
    finally:
        fitness.load_config = orig
        driver._fitness_for.cache_clear()

    # the comparable yardstick: stock objective, same layout
    conf, cost = orig(progdir, overrides={"leaf_sharing": True,
                                          "collapse_insearch": True})
    _, urb_fails = fitness.Fitness(conf, cost).score_with_fails(copy.deepcopy(root))

    uh, us = tiers(urb_fails)
    oh, os_ = tiers(own_fails)
    return dict(programme=Path(progdir).name, seed=seed, mode=mode,
                urb_hard=uh, urb_soft=us, urb_total=uh + us,
                own_hard=oh, own_soft=os_, own_total=oh + os_,
                elapsed_s=round(time.perf_counter() - t0, 1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=int, default=3000)
    ap.add_argument("--child-budget", type=int, default=80)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--modes", nargs="+", default=MODES)
    ap.add_argument("--corpus", nargs="+", default=CORPUS)
    ap.add_argument("--out", default="experiments/results/ab_ssz_search.csv")
    args = ap.parse_args()

    rows = []
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    for progdir in args.corpus:
        for mode in args.modes:
            for seed in range(args.seeds):
                r = run_arm(progdir, seed, mode, args.budget, args.child_budget)
                rows.append(r)
                print(f"  {r['programme']:<14} {mode:<20} seed={seed} "
                      f"urb {r['urb_hard']}h/{r['urb_soft']}s "
                      f"(own {r['own_hard']}h/{r['own_soft']}s) "
                      f"{r['elapsed_s']}s", flush=True)
                with out.open("w", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                    w.writeheader()
                    w.writerows(rows)

    print(f"\n=== stock-objective (urb) fail counts, budget {args.budget} ===")
    print(f"  {'programme':<14}{'mode':<22}{'hard':<14}{'soft':<14}total")
    print("  " + "-" * 70)
    for progdir in args.corpus:
        name = Path(progdir).name
        for mode in args.modes:
            sel = [r for r in rows if r["programme"] == name and r["mode"] == mode]
            if not sel:
                continue
            h = sum(r["urb_hard"] for r in sel) / len(sel)
            s = sum(r["urb_soft"] for r in sel) / len(sel)
            print(f"  {name:<14}{mode:<22}{h:<14.1f}{s:<14.1f}{h + s:.1f}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()

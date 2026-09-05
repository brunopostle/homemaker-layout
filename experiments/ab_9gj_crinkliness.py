"""Search A/B for the crinkliness reformulation (`homemaker-py-9gj`).

Two independent changes to `quality_uncrinkliness`, either or both:

  crinkliness_tail="ramp"        below FAIL_THRESHOLD. The factor evaluates a
                                 gaussian at `x = 1/crink`, whose exponent
                                 grows like 1/crink^2, so the failing tail
                                 spans quality 1e-300..1e-1 -- all of it
                                 numerically zero beside a passing leaf's ~1.
                                 The ramp makes that tail a straight line in
                                 crinkliness. (DESIGN.md §39.13. Measured a
                                 complete null on its own: 12 of 12 pairs
                                 byte-identical.)
  crinkliness_shape="daylight"   above it. `1/crink` is the room's mean depth
                                 from its daylit wall in storey-heights, and
                                 the stock gaussian is TWO-sided on it, so a
                                 room with more daylight than target is
                                 penalised for it -- while the cost model
                                 already charges that wall via
                                 `exterior_wall`/`boundary_wall`. "daylight"
                                 clips that side to 1.0. (DESIGN.md §39.14.)

**Why stock scoring is valid here** (the §38.9 trap, and the one case the
`9gj` bead flags as exempt): the ramp is continuous at FAIL_THRESHOLD and
strictly below it, so no leaf changes which side of the threshold it is on.
The fail set is byte-identical on every corpus artefact -- asserted in
`tests/test_fitness_crinkliness_tail.py`, not assumed here. An arm therefore
cannot win by deleting a fail category, and both arms are scored under stock.

**Two experiment shapes**, because they answer different questions:

  --start plateau  (default)  seed each run from that programme's
                              `coldstart-500000-s<k>.dom`. This is the ESCAPE
                              test the bead asks for: the ramp has signal only
                              where a search has already built partially-lit
                              rooms, and the corpus `init.dom` files show a
                              +0.000% score delta -- there is nothing for it to
                              grade at the start of a search.
  --start init                cold start, for comparison.

Pairing is on (starting layout, RNG seed), so `--seeds N` over `--starts M`
gives N*M paired samples per programme.

Usage::

    python experiments/ab_9gj_crinkliness.py --budget 8000 --seeds 2 --starts 3
    python experiments/ab_9gj_crinkliness.py --start init --budget 8000 --seeds 6

Sharding, because one run is minutes and the job list is 4x that. Each shard
keeps BOTH arms of a pair together, so the two halves of a comparison never
land on differently-loaded processes::

    for i in 0 1 2 3; do
      python experiments/ab_9gj_crinkliness.py --budget 8000 --seeds 2 --starts 3 \
             --shard $i --nshards 4 &
    done; wait
    python experiments/ab_9gj_crinkliness.py --report

A POWERED run needs more than the in-session pilot could afford. §39.12 puts
harbor's minimum detectable difference at n=3 at 13.7 fails; the plateau-escape
deltas here are single-digit, so budget for n >= 8 pairs per programme
(`--seeds 3 --starts 3` gives 9) and a budget large enough for either arm to
move at all -- the pilot's 8000 evals is 1.6% of what produced the plateau::

    for i in $(seq 0 3); do
      python experiments/ab_9gj_crinkliness.py --budget 100000 --seeds 3 --starts 3 \
             --shard $i --nshards 4 &
    done; wait
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

# Each arm names a crinkliness configuration. "stock" must stay first: it is
# the baseline every other arm is paired against, and the yardstick all arms
# are SCORED under.
ARM_CONF = {
    "stock": {},
    "ramp": {"crinkliness_tail": "ramp"},
    "daylight": {"crinkliness_shape": "daylight"},
    "daylight+ramp": {"crinkliness_shape": "daylight",
                      "crinkliness_tail": "ramp"},
    # homemaker-py-ecx (§39.18): orthogonal to the crinkliness arms -- it
    # changes how the factors are COMBINED, not what any of them says.
    "geomean": {"quality_aggregate": "geometric_mean"},
    "geomean+daylight": {"quality_aggregate": "geometric_mean",
                         "crinkliness_shape": "daylight",
                         "crinkliness_tail": "ramp"},
}
ARMS = ["stock", "daylight", "daylight+ramp"]


def _with_arm(arm: str):
    """Patch `fitness.load_config` so every evaluator built during the run --
    the driver's, the inner loop's, the seeder's -- sees the arm's overrides.

    `driver.search` has no parameter for them and `driver._fitness_for` is
    lru_cached, so the cache is cleared around the patch (see ab_ssz_search).
    """
    orig = fitness.load_config
    arm_ov = ARM_CONF[arm]

    def patched(directory, overrides=None):
        ov = dict(overrides or {})
        ov.update(arm_ov)
        return orig(directory, overrides=ov)

    return orig, patched


def tiers(fails) -> tuple[int, int]:
    c = collections.Counter(fitness.classify_fail_tier(f) for f in fails)
    return c["hard"], c["soft"]


def run_arm(progdir: str, start: Path, seed: int, tail: str, budget: int,
            child_budget: int) -> dict:
    orig, patched = _with_arm(tail)
    fitness.load_config = patched
    driver._fitness_for.cache_clear()
    t0 = time.perf_counter()
    try:
        res = driver.search(dom_mod.load(str(start)), progdir, budget=budget,
                            seed=seed, child_budget=child_budget, n_workers=1)
        root = copy.deepcopy(res.best.root)
    finally:
        fitness.load_config = orig
        driver._fitness_for.cache_clear()

    conf, cost = orig(progdir, overrides={"leaf_sharing": True,
                                          "collapse_insearch": True})
    score, fails = fitness.Fitness(conf, cost).score_with_fails(copy.deepcopy(root))
    h, s = tiers(fails)
    return dict(programme=Path(progdir).name, start=start.name, seed=seed,
                tail=tail, hard=h, soft=s, total=h + s, score=score,
                elapsed_s=round(time.perf_counter() - t0, 1))


def starting_points(progdir: str, kind: str, n: int) -> list[Path]:
    """The distinct layouts to start from.

    `--starts` applies to plateau mode only: there is exactly one `init.dom`,
    and repeating it would give several jobs the same (start, seed) pairing key,
    which `_report` would silently collapse to one. In init mode the RNG seed
    is the only sampling dimension, so use `--seeds`.
    """
    d = Path(progdir)
    if kind == "init":
        return [d / "init.dom"]
    found = sorted(d.glob("coldstart-500000-s*.dom"))[:n]
    if not found:
        raise SystemExit(f"no coldstart-500000-s*.dom in {d} for --start plateau")
    return found


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=int, default=8000)
    ap.add_argument("--child-budget", type=int, default=80)
    ap.add_argument("--seeds", type=int, default=2, help="RNG seeds per start")
    ap.add_argument("--starts", type=int, default=3,
                    help="plateau layouts to start from (plateau mode only)")
    ap.add_argument("--start", choices=("plateau", "init"), default="plateau")
    ap.add_argument("--corpus", nargs="+", default=CORPUS)
    ap.add_argument("--arms", nargs="+", default=ARMS,
                    choices=sorted(ARM_CONF), help="first arm is the baseline")
    ap.add_argument("--out", default="experiments/results/ab_9gj_crinkliness.csv")
    ap.add_argument("--shard", type=int, default=0,
                    help="run only jobs i where i %% nshards == shard")
    ap.add_argument("--nshards", type=int, default=1,
                    help="split the job list across N processes; each writes "
                         "<out>.shard<i>. Use --report to merge and analyse.")
    ap.add_argument("--report", action="store_true",
                    help="merge <out>.shard* (or <out>) and print the analysis "
                         "only -- runs nothing")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.report:
        rows = []
        shards = sorted(out.parent.glob(out.name + ".shard*")) or (
            [out] if out.exists() else [])
        for sh in shards:
            with sh.open() as fh:
                for r in csv.DictReader(fh):
                    for k in ("total", "hard", "soft", "seed"):
                        r[k] = int(r[k])
                    r["score"] = float(r["score"])
                    rows.append(r)
        if len(shards) > 1:
            with out.open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
        _report(rows, args.corpus, args.arms)
        print(f"\nmerged {len(rows)} runs from {len(shards)} file(s) into {out}")
        return

    # Build the whole job list first so sharding is deterministic and every
    # (start, seed) pair keeps BOTH arms in the same shard -- the comparison is
    # paired, and splitting a pair across processes would let machine load
    # differ between the two halves of one pair.
    jobs = []
    for progdir in args.corpus:
        for start in starting_points(progdir, args.start, args.starts):
            for seed in range(args.seeds):
                jobs.append((progdir, start, seed))

    rows: list[dict] = []
    dest = (out if args.nshards == 1
            else out.with_name(out.name + f".shard{args.shard}"))
    for i, (progdir, start, seed) in enumerate(jobs):
        if i % args.nshards != args.shard:
            continue
        for tail in args.arms:
            r = run_arm(progdir, start, seed, tail, args.budget,
                        args.child_budget)
            rows.append(r)
            print(f"  {r['programme']:<14} {start.name:<26} seed={seed} "
                  f"{tail:<9} {r['hard']}h/{r['soft']}s = {r['total']:3d} "
                  f"score {r['score']:.4g}  {r['elapsed_s']}s", flush=True)
            with dest.open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
    if args.nshards == 1:
        _report(rows, args.corpus, args.arms)
    print(f"\nwrote {dest}")


def _report(rows, corpus, arms=None) -> None:
    """homemaker-py-tco: state what this N could resolve, beside the result."""
    from ab_report import format_report, paired_report
    seen = []
    for r in rows:
        if r["tail"] not in seen:
            seen.append(r["tail"])
    arms = [a for a in (arms or seen) if a in seen] or seen
    base = arms[0]
    for progdir in corpus:
        name = Path(progdir).name
        by: dict[tuple, dict] = {}
        for r in rows:
            if r["programme"] == name:
                by.setdefault((r["start"], r["seed"]), {})[r["tail"]] = r["total"]
        for arm in arms[1:]:
            keys = sorted(k for k, v in by.items() if base in v and arm in v)
            if len(keys) < 2:
                continue
            print(f"\n--- {name}: {arm} vs {base} (stock-scored total fails) ---")
            print(format_report(paired_report(
                [by[k][base] for k in keys], [by[k][arm] for k in keys],
                base, arm)))


if __name__ == "__main__":
    main()

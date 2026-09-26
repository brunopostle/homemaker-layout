"""Does the `support_outside` repair operator find the terrace? (`homemaker-py-e4r`)

DESIGN.md §39.53. The owner's three-storey programme-house -- every level's
outdoor space over enclosed space -- exists, is the best result at
`c836457+orth` (zero fails, 0.2635, next best 0.2134), and the search finds it
**one run in six**. §39.53's A/B settled that the storey count is not the
variable: forcing three storeys left 5 of 6 runs still failing `no outside
space`. What decides it is what sits UNDERNEATH the outdoor space, and nothing
in the operator set aimed at that relation.

`operators.mutate_support_outside` is the operator that does. This is its A/B.

Matched pairs, one variable, the flag:

* **arm A** -- `--no-support-outside`, the control.
* **arm B** -- `homemaker-evolve` as shipped.

The arms inverted at §39.65, when the operator became the default on the owner's
ruling. Arm B is therefore what a plain run now does and arm A is the counter-
factual; the comparison and its direction are unchanged, and `roof_fail`
clearing more often in arm B is still the claim.

Both arms use the SAME programme directory and the same objective, so unlike
`xhw_storey_ab.py` there is no arm-specific config and nothing to re-score:
a `.dom` from either arm is scored by the one scorer both arms optimised.

**Why twelve seeds and not the six §39.53 used.** The headline outcome is
binary per seed (does this run clear `no outside space`?), and a paired binary
test over six pairs CANNOT reach significance however it comes out: with `b`
discordant pairs the smallest two-sided sign/McNemar p is `2 * 0.5**b`, which
at the theoretical maximum `b = 6` is 0.031 but at `b = 5` is already 0.0625.
Six seeds can produce at most six discordant pairs and realistically far fewer.
Twelve pairs cost about 22 core-hours here (the §39.53 runs averaged 56 min),
against the 436 the coldstart sweep costs -- cheap enough that being underpowered
would be a choice. §38.19/§38.21 are this project's two standing examples of
reporting a margin the sample could not resolve; `ab_report.paired_report`
prints the MDD beside the continuous verdicts for the same reason.

**Record what you expect before running it** (CLAUDE.md, *Working while the box
is away*). The expectation on file:

* `roof_fail` clears in materially more than 1 seed in 6 -- that is the whole
  claim, and the number to beat.
* total fails are NOT expected to drop by the same amount: `place` displaces a
  leaf and `swap` may relocate circulation, so the operator trades a
  `no outside space` fail for a missing-room or connectivity fail that
  `place_missing` / `bridge_circulation` then have to clear. A wash on fails
  with `roof_fail` cleared is a PASS on the mechanism and a question about the
  operator set around it, not a failure.
* score is expected up if and only if the fail clears, since §39.53's
  zero-fail layout outscores the field by 0.05.

Results are committed and pushed per run -- the container is ephemeral and
§39.33's lesson was expensive. `--resume` skips pairs already in the table.

Usage::

    python experiments/e4r_support_outside_ab.py --budget 500000 --seeds 12 \
        --slots $(nproc)
    python experiments/e4r_support_outside_ab.py --resume
    python experiments/e4r_support_outside_ab.py --report-only
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import os
import shutil
import subprocess
import tempfile
import time
from math import comb
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESULTS = REPO / "experiments" / "results" / "e4r_support_outside_ab.tsv"
ARTEFACTS = REPO / "experiments" / "results" / "e4r"
SRC_PROGRAMME = REPO / "examples" / "programme-house"
ARMS = ("armA", "armB")
FIELDS = ["arm", "seed", "objective", "budget", "storeys", "fails", "hard",
          "soft", "roof_fail", "score", "elapsed_s", "dom", "fail_list"]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _runner():
    """Borrow the cold-start runner's objective stamp and its commit/push
    discipline rather than writing a third copy of either (§39.42, §39.43)."""
    return _load(REPO / "experiments" / "run_coldstart_baseline.py",
                 "_coldstart_runner")


def build_arm(work: Path, arm: str) -> Path:
    """A clean copy of the programme. Both arms are byte-identical -- the only
    difference between them is a command-line flag -- but they get separate
    directories so the two runs never race on `.score`/`.fails` side files."""
    d = work / arm
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(SRC_PROGRAMME, d)
    for junk in (list(d.glob("coldstart-*")) + list(d.glob("*.score"))
                 + list(d.glob("*.fails")) + list(d.glob("*.checkpoint"))):
        junk.unlink()
    return d


def score(dom: Path, programme: Path, env: dict):
    from homemaker_layout.fitness import classify_fail_tier
    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        for cfg in programme.glob("*.config"):
            shutil.copy(cfg, w / cfg.name)
        shutil.copy(dom, w / dom.name)
        subprocess.run(["homemaker-fitness", dom.name], cwd=w,
                       capture_output=True, env=env)
        lines = [l for l in (w / f"{dom.name}.fails").read_text().splitlines()
                 if l.strip()]
        val = float((w / f"{dom.name}.score").read_text().strip())
    hard = sum(1 for l in lines if classify_fail_tier(l) == "hard")
    return val, lines, hard


def storeys(path: Path) -> int:
    from homemaker_layout import dom as dm, geometry as g
    g.ORTHOGONAL_DIVISION = True
    n, k = dm.load(str(path)), 0
    g.clear_cache()
    while n is not None:
        n, k = n.above, k + 1
    return k


def rows() -> list[dict]:
    if not RESULTS.exists():
        return []
    return list(csv.DictReader(RESULTS.open(), delimiter="\t"))


def record(row: dict, dom: Path, mod) -> None:
    existing = rows()
    existing.append({k: str(row[k]) for k in FIELDS})
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t")
        w.writeheader()
        w.writerows(existing)
    ARTEFACTS.mkdir(parents=True, exist_ok=True)
    kept = ARTEFACTS / dom.name
    shutil.copy(dom, kept)
    mod.commit_and_push(
        [str(RESULTS.relative_to(REPO)), str(kept.relative_to(REPO))],
        f"e4r {row['arm']} seed {row['seed']}: {row['fails']} fails "
        f"(roof_fail={row['roof_fail']}), score {row['score']}",
        "support_outside operator A/B (homemaker-py-e4r, DESIGN.md §39.53).\n"
        "Pushed per run because the container is ephemeral.")


def report() -> int:
    """Paired verdicts over the seeds both arms have finished."""
    ab = _load(REPO / "experiments" / "ab_report.py", "_ab_report")
    by = {(r["arm"], r["seed"]): r for r in rows()}
    seeds = sorted({s for _, s in by
                    if (ARMS[0], s) in by and (ARMS[1], s) in by}, key=int)
    if not seeds:
        print("no complete pairs yet")
        return 1
    print(f"paired seeds: {len(seeds)} ({', '.join(seeds)})\n")
    # `ab_report`'s mean_diff is off-minus-on and its W/L counts read "on wins
    # when the difference is positive", i.e. LOWER is better. That is right for
    # fails and backwards for score, so score says so rather than being negated
    # into a display nobody can read.
    for metric in ("fails", "hard", "score"):
        a = [float(by[(ARMS[0], s)][metric]) for s in seeds]
        b = [float(by[(ARMS[1], s)][metric]) for s in seeds]
        print(f"{metric}:" + ("   (mean_diff is off-minus-on, so NEGATIVE = "
                              "arm B scored higher = better; W/L is inverted "
                              "for this metric)" if metric == "score" else ""))
        print(ab.format_report(ab.paired_report(a, b, "off", "on")))
        print()

    # The headline outcome is binary per seed; a sign test is the honest
    # reading of it, and its floor on p is worth printing because N=6 could
    # not have reached 0.05 however it came out (see the module docstring).
    a = [int(by[(ARMS[0], s)]["roof_fail"]) for s in seeds]
    b = [int(by[(ARMS[1], s)]["roof_fail"]) for s in seeds]
    cleared = sum(1 for x, y in zip(a, b) if x and not y)
    broke = sum(1 for x, y in zip(a, b) if y and not x)
    disc = cleared + broke
    print("no outside space -- the §39.53 claim")
    print(f"  off: {sum(a)}/{len(seeds)} runs carry the fail    "
          f"(§39.53 measured 5 of 6 at N=6)")
    print(f"  on : {sum(b)}/{len(seeds)} runs carry the fail")
    print(f"  discordant pairs: {disc} ({cleared} cleared by the operator, "
          f"{broke} broken)")
    if not disc:
        print("  no discordant pairs: the operator changed no run's verdict.")
        return 0
    lo = min(cleared, broke)
    p_val = min(1.0, 2 * sum(comb(disc, k) for k in range(lo + 1)) / 2 ** disc)
    floor = 2 / 2 ** disc
    print(f"  two-sided sign test p = {p_val:.4g}")
    if floor >= 0.05:
        print(f"  ** NOT RESOLVABLE: {disc} discordant pairs cannot reach "
              f"p<0.05 -- the smallest p this many pairs can produce is "
              f"{floor:.3g}. Run more seeds rather than reporting a margin.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=int, default=500000)
    ap.add_argument("--seeds", type=int, default=12,
                    help="paired seeds per arm (default 12; see the module "
                         "docstring for why six cannot resolve this)")
    ap.add_argument("--slots", type=int, default=4,
                    help="concurrent single-worker runs; set it to the core count")
    ap.add_argument("--resume", action="store_true",
                    help="skip (arm, seed) pairs already recorded")
    ap.add_argument("--report-only", action="store_true",
                    help="re-print the paired verdicts and exit")
    args = ap.parse_args()

    if args.report_only:
        return report()

    mod = _runner()
    dirty = mod.uncommitted_objective_sources()
    if dirty:
        print("the objective's own source is not committed: "
              + ", ".join(dirty) + "\nCommit first (§39.51).")
        return 2
    env = dict(os.environ, HOMEMAKER_ORTHOGONAL_DIVISION="1",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               MKL_NUM_THREADS="1")
    env.pop("HOMEMAKER_SUPPORT_OUTSIDE", None)   # the flag is the variable,
    # and an inherited env override would silently set BOTH arms
    os.environ.update(env)
    objective = mod.objective_commit()

    work = Path(tempfile.gettempdir()) / "e4r_arms"
    work.mkdir(parents=True, exist_ok=True)
    arms = {arm: build_arm(work, arm) for arm in ARMS}

    queue = [(arm, s) for s in range(args.seeds) for arm in ARMS]
    if args.resume:
        have = {(r["arm"], r["seed"]) for r in rows()}
        before = len(queue)
        queue = [q for q in queue if (q[0], str(q[1])) not in have]
        print(f"resuming: {before - len(queue)} already recorded, "
              f"{len(queue)} to run")
    if not queue:
        print("nothing to do")
        return report()

    print(f"{len(queue)} runs, objective {objective}, budget {args.budget}, "
          f"{args.slots} slots", flush=True)
    running: dict = {}
    while queue or running:
        while queue and len(running) < args.slots:
            arm, seed = queue.pop(0)
            d = arms[arm]
            out = d / f"e4r-{arm}-s{seed}.dom"
            fh = (d / f"e4r-{arm}-s{seed}.log").open("w")
            cmd = ["homemaker-evolve", "init.dom", "--budget", str(args.budget),
                   "--seed", str(seed), "--workers", "1", "--output", str(out)]
            # arm A is now the CONTROL: the operator is default-on since §39.65,
            # so the flag that makes an arm differ is the negative one.
            if arm == "armA":
                cmd.append("--no-support-outside")
            p = subprocess.Popen(cmd, cwd=d, stdout=subprocess.DEVNULL,
                                 stderr=fh, env=env)
            running[p.pid] = (p, arm, seed, out, fh, time.monotonic())
            print(f"  start {arm} s{seed}", flush=True)
        time.sleep(10)
        for pid, (p, arm, seed, out, fh, st) in list(running.items()):
            if p.poll() is None:
                continue
            fh.close()
            del running[pid]
            el = round(time.monotonic() - st, 1)
            if not out.exists():
                print(f"    FAILED {arm} s{seed} rc={p.returncode} ({el}s)",
                      flush=True)
                continue
            sc, fails, hard = score(out, arms["armA"], env)
            roof = any("no outside space" in f for f in fails)
            print(f"    done {arm} s{seed}: {len(fails)} fails "
                  f"(roof_fail={int(roof)}), score {sc:.4g}, {el}s", flush=True)
            record(dict(arm=arm, seed=seed, objective=objective,
                        budget=args.budget, storeys=storeys(out),
                        fails=len(fails), hard=hard, soft=len(fails) - hard,
                        roof_fail=int(roof), score=f"{sc:.6g}", elapsed_s=el,
                        dom=out.name, fail_list=" | ".join(sorted(fails))),
                   out, mod)
    print("\n=== all runs complete ===\n", flush=True)
    return report()


if __name__ == "__main__":
    raise SystemExit(main())

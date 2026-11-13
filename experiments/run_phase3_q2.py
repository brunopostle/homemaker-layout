#!/usr/bin/env python3
"""Phase 3 of the aggregation review: Q2, the ranking order under a
programme-centric score, settled by experiment (`homemaker-py-5fje.6`,
DESIGN.md §39.201 Phase 3, §39.218).

The cells are (aggregation, rank), factorial, and the owner asked for all of
them (2026-11-08):

    A0  x {fails, score, tiers}     today's score; A0-fails is the control
    P1  x {fails, score, tiers}     phi 1e-3
    P1u x {fails, score, tiers}     P1 with phi 1e-20

Each arm is twelve runs at 128k evaluations, one worker each: four programmes,
three starts. harbor-house and maple-court start from the three best seeds of
their latest catalogue races (`halving-harbor-split`, `halving-maple-single`,
fields the earlier races fixed); health-centre and programme-house start cold
from `init.dom`. Start k always runs with rng seed k, so arm X's run k and arm
Y's run k differ only in the arm: the pairs for the report cards.

The queue is arm-major in the order above, so the 2 x 2 core (A0/P1 x
fails/score) finishes first and can be read while the rest runs; within an
arm the longest programmes go first. Every finished run is scored under A0 AND
under its own arm, recorded in `results.tsv` with its arm's objective stamp
and search config, and committed and pushed. `--resume` skips recorded rows.

    export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
    setsid nohup env HOMEMAKER_ORTHOGONAL_DIVISION=1 \\
        python -u experiments/run_phase3_q2.py --slots 6 \\
        > ~/homemaker-phase3-q2.log 2>&1 < /dev/null &

Do not edit `src/` while it runs.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "experiments" / "results" / "phase3-q2"
TSV = OUT / "results.tsv"
BUDGET = 128000

_spec = importlib.util.spec_from_file_location(
    "rcb", REPO / "experiments" / "run_coldstart_baseline.py")
rcb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rcb)

# name -> (aggregation, phi or None, rank); queue order is this order
ARMS = {
    "A0-fails": ("A0", None, "fails"),
    "A0-score": ("A0", None, "score"),
    "P1-fails": ("P1", None, "fails"),
    "P1-score": ("P1", None, "score"),
    "A0-tiers": ("A0", None, "tiers"),
    "P1-tiers": ("P1", None, "tiers"),
    "P1u-fails": ("P1", "1e-20", "fails"),
    "P1u-score": ("P1", "1e-20", "score"),
    "P1u-tiers": ("P1", "1e-20", "tiers"),
}
R = "experiments/results"
STARTS = {   # longest first
    "maple-court": [f"{R}/halving-maple-single/single-{k}.dom" for k in (1, 2, 3)],
    "harbor-house": [f"{R}/halving-harbor-split/{n}.dom"
                     for n in ("dealt-1", "dealt-2", "cap-1")],
    "health-centre": ["examples/health-centre/init.dom"] * 3,
    "programme-house": ["examples/programme-house/init.dom"] * 3,
}
COLUMNS = ["arm", "aggregation", "phi", "rank", "programme", "k", "start",
           "budget", "fails", "hard", "soft", "score_a0", "score_arm",
           "elapsed_s", "dom", "objective", "search_commit", "search_config"]


def arm_env(arm: str) -> dict:
    agg, phi, rank = ARMS[arm]
    env = {"HOMEMAKER_AGGREGATION": agg, "HOMEMAKER_RANK": rank}
    if phi is not None:
        env["HOMEMAKER_AGGREGATION_PHI"] = phi
    return env


@contextlib.contextmanager
def environ(extra: dict):
    keys = ("HOMEMAKER_AGGREGATION", "HOMEMAKER_AGGREGATION_PHI", "HOMEMAKER_RANK")
    old = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    os.environ.update(extra)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def stamps(arm: str) -> "tuple[str, str, str, Path | None]":
    """(objective, search_commit, search_config hash, new sidecar) for one arm,
    read under the arm's environment exactly as its subprocess will see it."""
    with environ(arm_env(arm)):
        h, conf = rcb.search_config()
        assert conf["rank"] == ARMS[arm][2], conf
        return rcb.objective_commit(), rcb.search_commit(), h, rcb.write_search_config(h, conf)


def score(dom_path: Path, programme: str, arm: str) -> "tuple[int, int, int, float, float]":
    """(fails, hard, soft, A0 score, the arm's score), in this process."""
    from homemaker_layout import dom
    from homemaker_layout.fitness import Fitness, classify_fail_tier, load_config
    agg, phi, _ = ARMS[arm]
    pdir = REPO / "examples" / programme
    out = []
    for ov in ({"aggregation": "A0"},
               {"aggregation": agg, **({"aggregation_phi": float(phi)} if phi else {})}):
        root = dom.load(str(dom_path))
        dom.link(root)
        out.append(Fitness(*load_config(pdir, overrides=ov)).score_with_fails(root))
    (a0, fails), (own, _) = out
    hard = sum(1 for f in fails if classify_fail_tier(f) == "hard")
    return len(fails), hard, len(fails) - hard, a0, own


def recorded() -> "set[tuple[str, str, int]]":
    if not TSV.exists():
        return set()
    with TSV.open() as fh:
        return {(r["arm"], r["programme"], int(r["k"]))
                for r in csv.DictReader(fh, delimiter="\t")}


def append_row(row: dict) -> None:
    new = not TSV.exists()
    with TSV.open("a") as fh:
        w = csv.DictWriter(fh, COLUMNS, delimiter="\t", lineterminator="\n")
        if new:
            w.writeheader()
        w.writerow(row)


def main() -> int:
    global OUT, TSV
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--slots", type=int, default=6)
    ap.add_argument("--budget", type=int, default=BUDGET)
    ap.add_argument("--arms", nargs="+", default=list(ARMS), choices=list(ARMS))
    ap.add_argument("--programmes", nargs="+", default=list(STARTS), choices=list(STARTS))
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--work", type=Path, default=Path.home() / "phase3-q2",
                    help="run logs (default ~/phase3-q2)")
    ap.add_argument("--out", type=Path, default=OUT,
                    help="results directory (default experiments/results/phase3-q2)")
    ap.add_argument("--no-push", action="store_true", help="smoke runs: commit nothing")
    args = ap.parse_args()
    OUT = args.out.resolve()   # relative_to(REPO) below needs it absolute
    TSV = OUT / "results.tsv"

    if os.environ.get(rcb.ORTH_ENV) != "1":
        print("!!! set HOMEMAKER_ORTHOGONAL_DIVISION=1", file=sys.stderr)
        return 2
    dirty = rcb.uncommitted_objective_sources()
    if dirty:
        print(f"!!! objective sources uncommitted: {dirty}", file=sys.stderr)
        return 2
    done = recorded()
    if done and not args.resume and not args.dry_run:
        print(f"!!! {TSV} already has {len(done)} rows; --resume", file=sys.stderr)
        return 2

    meta = {arm: stamps(arm) for arm in args.arms}
    queue = [(arm, prog, k) for arm in args.arms for prog in args.programmes
             for k in (1, 2, 3) if (arm, prog, k) not in done]
    print(f"{len(queue)} runs, budget {args.budget}, {args.slots} slots, "
          f"HEAD {subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=REPO, capture_output=True, text=True).stdout.strip()}",
          flush=True)
    for arm in args.arms:
        o, s, h, _ = meta[arm]
        print(f"  {arm:10s} objective {o:24s} search {s} config {h}", flush=True)
    if args.dry_run:
        for arm, prog, k in queue:
            print(f"  would run {arm} {prog} {k} from {STARTS[prog][k - 1]}")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    pending_sidecars = {arm: m[3] for arm, m in meta.items() if m[3]}
    running: dict = {}
    while queue or running:
        while queue and len(running) < args.slots:
            arm, prog, k = queue.pop(0)
            start = REPO / STARTS[prog][k - 1]
            stem = f"{arm}--{prog}--{k}"
            out = OUT / f"{stem}.dom"
            log = args.work / f"{stem}.log"
            fh = log.open("w")
            env = {**os.environ, **arm_env(arm)}
            if "HOMEMAKER_AGGREGATION_PHI" not in arm_env(arm):
                env.pop("HOMEMAKER_AGGREGATION_PHI", None)
            proc = subprocess.Popen(
                [sys.executable, "-m", "homemaker_layout.evolve", str(start),
                 "--programme-dir", str(REPO / "examples" / prog),
                 "--budget", str(args.budget), "--seed", str(k), "--workers", "1",
                 "--output", str(out), "--checkpoint-every", str(args.budget // 8)],
                cwd=REPO, stdout=subprocess.DEVNULL, stderr=fh, env=env)
            running[proc.pid] = (proc, arm, prog, k, out, log, fh, time.monotonic())
            print(f"=== {time.strftime('%F %T')} start {stem}", flush=True)

        time.sleep(15)
        for pid, (proc, arm, prog, k, out, log, fh, t0) in list(running.items()):
            if proc.poll() is None:
                continue
            fh.close()
            del running[pid]
            elapsed = round(time.monotonic() - t0, 1)
            stem = out.stem
            if proc.returncode or not out.exists():
                print(f"!!! {stem} FAILED rc={proc.returncode} after {elapsed}s, see {log}",
                      flush=True)
                continue
            n, hard, soft, a0, own = score(out, prog, arm)
            o, s, h, _ = meta[arm]
            agg, phi, rank = ARMS[arm]
            append_row(dict(arm=arm, aggregation=agg, phi=phi or "-", rank=rank,
                            programme=prog, k=k, start=STARTS[prog][k - 1],
                            budget=args.budget, fails=n, hard=hard, soft=soft,
                            score_a0=f"{a0:.6g}", score_arm=f"{own:.6g}",
                            elapsed_s=elapsed, dom=out.name, objective=o,
                            search_commit=s, search_config=h))
            print(f"=== {time.strftime('%F %T')} done {stem}: {n} fails ({hard}h) "
                  f"A0 {a0:.4g} arm {own:.4g} in {elapsed / 3600:.2f} h", flush=True)
            kept = OUT / log.name
            shutil.copyfile(log, kept)
            paths = [str(out), str(kept), str(TSV)]
            side = pending_sidecars.pop(arm, None)
            if side:
                paths.append(str(side))
            if args.no_push:
                continue
            rcb.commit_and_push(
                [str(Path(p).relative_to(REPO)) for p in paths],
                f"Phase 3 Q2: {stem}, {n} fails (homemaker-py-5fje.6)",
                note="Phase 3 of the aggregation review, DESIGN.md §39.218: one run "
                     "of the (aggregation, rank) factorial, 128k evaluations, "
                     "one worker.")
    print(f"=== {time.strftime('%F %T')} phase 3 q2 complete", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Is `homemaker-evolve --native` as good a search as the default?
(`homemaker-py-8b2u.8`, DESIGN.md §39.104)

Matched pairs, one variable, the flag:

* **quad**   -- `homemaker-evolve` as shipped, orthogonal division on: Urb's
  quad tree, written as format v1.
* **native** -- `homemaker-evolve --native`: the same operators and genes on a
  rectangle-frame tree, written as format v2.

It is not the same search with another file format. A ratio is a fraction of
the node's rectangle, not of a cropped edge, so the same genome draws slightly
different cells wherever a cell touches a skew plot boundary.

**The two arms are scored by one objective.** Every orthogonal design scores
the same as a quad tree and as the native tree of the same building (192 of
192, `tests/test_native_tree.py`), so each arm's own `homemaker-fitness` score
is the comparable number. The two rows still carry different marks --
`<stamp>+orth` and `<stamp>+native` -- because they name different searches
and a later reader must be able to tell which geometry drew the artefact.

**Record what you expect before running it.** On file in the bead: no resolved
difference on programme-house (small skew, few cells); if anything differs it
will be on the large programmes, where more cells touch the skew boundary.
`elapsed_s` is part of the answer: a native score cost 40% more before
`8b2u.10`/`.11` and 6-15% more after, and at 500k that is wall-clock.

Results are committed and pushed per run, as the cold-start runner does it.

Usage::

    python experiments/native_ab.py --seeds 36 --slots $(nproc)
    python experiments/native_ab.py --programme maple-court --seeds 3 --slots 6
    python experiments/native_ab.py --resume
    python experiments/native_ab.py --report-only
    python experiments/native_ab.py --scratch /some/dir --budget 300 --seeds 1   # smoke
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
ARMS = ("quad", "native")
NATIVE_SUFFIX = "+native"
FIELDS = ["programme", "arm", "seed", "objective", "search_commit", "budget",
          "storeys", "fails", "hard", "soft", "score", "elapsed_s", "dom",
          "fail_list"]


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _runner():
    """The cold-start runner's stamp and its commit/push discipline, borrowed
    rather than copied a fourth time (§39.42, §39.43)."""
    return _load(REPO / "experiments" / "run_coldstart_baseline.py",
                 "_coldstart_runner")


def stamp(mod, arm: str) -> str:
    """The objective mark of one arm. The commit is the runner's; the suffix
    says which geometry drew the artefact."""
    base = mod.objective_commit()
    if base.endswith(mod.ORTH_SUFFIX):
        base = base[: -len(mod.ORTH_SUFFIX)]
    return base + (NATIVE_SUFFIX if arm == "native" else mod.ORTH_SUFFIX)


def build_arm(work: Path, programme: str, arm: str) -> Path:
    """A clean copy of the programme for one arm, so the two never race on
    `.score` / `.fails` side files."""
    d = work / programme / arm
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(REPO / "examples" / programme, d)
    for junk in {*d.glob("coldstart-*"), *d.glob("*.score"),
                 *d.glob("*.fails"), *d.glob("*.checkpoint")}:
        junk.unlink()
    return d


def score(dom: Path, programme_dir: Path, env: dict):
    """`homemaker-fitness` on a copy: a v1 file is scored as the quad tree it
    is (the switch is on in `env`), a v2 file natively."""
    from homemaker_layout.fitness import classify_fail_tier
    with tempfile.TemporaryDirectory() as td:
        w = Path(td)
        for cfg in programme_dir.glob("*.config"):
            shutil.copy(cfg, w / cfg.name)
        shutil.copy(dom, w / dom.name)
        subprocess.run([sys.executable, "-m", "homemaker_layout.fitness_cmd", dom.name],
                       cwd=w, capture_output=True, env=env)
        lines = [ln for ln in (w / f"{dom.name}.fails").read_text().splitlines()
                 if ln.strip()]
        val = float((w / f"{dom.name}.score").read_text().strip())
    hard = sum(1 for ln in lines if classify_fail_tier(ln) == "hard")
    return val, lines, hard


def storeys(path: Path) -> int:
    from homemaker_layout import dom as dm, geometry as g
    was, g.ORTHOGONAL_DIVISION = g.ORTHOGONAL_DIVISION, True
    try:
        n, k = dm.load(str(path)), 0
    finally:
        g.ORTHOGONAL_DIVISION = was
        g.clear_cache()
    while n is not None:
        n, k = n.above, k + 1
    return k


class Table:
    def __init__(self, results: Path, artefacts: Path, commit: bool):
        self.results, self.artefacts, self.commit = results, artefacts, commit

    def rows(self) -> "list[dict]":
        if not self.results.exists():
            return []
        return list(csv.DictReader(self.results.open(), delimiter="\t"))

    def record(self, row: dict, dom: Path, mod) -> None:
        existing = self.rows()
        existing.append({k: str(row[k]) for k in FIELDS})
        self.results.parent.mkdir(parents=True, exist_ok=True)
        with self.results.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t")
            w.writeheader()
            w.writerows(existing)
        self.artefacts.mkdir(parents=True, exist_ok=True)
        kept = self.artefacts / dom.name
        shutil.copy(dom, kept)
        if self.commit:
            mod.commit_and_push(
                [str(self.results.relative_to(REPO)), str(kept.relative_to(REPO))],
                f"native A/B {row['programme']} {row['arm']} seed {row['seed']}: "
                f"{row['fails']} fails, score {row['score']}",
                "homemaker-evolve --native against the default search "
                "(homemaker-py-8b2u.8, DESIGN.md §39.104).")


def report(table: Table) -> int:
    """Paired verdicts, per programme, over the seeds both arms finished."""
    ab = _load(REPO / "experiments" / "ab_report.py", "_ab_report")
    rows = table.rows()
    done = False
    for prog in dict.fromkeys(r["programme"] for r in rows):
        by = {(r["arm"], r["seed"]): r for r in rows if r["programme"] == prog}
        seeds = sorted({s for _, s in by if all((a, s) in by for a in ARMS)}, key=int)
        marks = sorted({r["objective"] for r in by.values()})
        print(f"=== {prog}: {len(seeds)} paired seeds; objective {', '.join(marks)}\n")
        if len(seeds) < 2:
            print("  fewer than two complete pairs: nothing to report yet\n")
            continue
        done = True
        for metric in ("fails", "hard", "score", "elapsed_s"):
            a = [float(by[("quad", s)][metric]) for s in seeds]
            b = [float(by[("native", s)][metric]) for s in seeds]
            note = {"score": "   (mean_diff is quad-minus-native, so NEGATIVE = "
                             "native scored higher = better; W/L is inverted "
                             "for this metric)",
                    "elapsed_s": "   (seconds; positive mean_diff = native faster)"}
            print(f"{metric}:{note.get(metric, '')}")
            print(ab.format_report(ab.paired_report(a, b, "quad", "native")))
            print()
    return 0 if done else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--programme", choices=PROGRAMMES, default="programme-house")
    ap.add_argument("--budget", type=int, default=500000)
    ap.add_argument("--seeds", type=int, default=36,
                    help="paired seeds per arm (default 36, the e4r A/B's count)")
    ap.add_argument("--slots", type=int, default=4,
                    help="concurrent single-worker runs; set it to the core count")
    ap.add_argument("--resume", action="store_true",
                    help="skip (programme, arm, seed) runs already recorded")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--scratch", metavar="DIR",
                    help="write the table and artefacts under DIR and commit "
                         "nothing: for a smoke run at a toy budget")
    args = ap.parse_args(argv)

    out = Path(args.scratch) if args.scratch else REPO / "experiments" / "results"
    table = Table(out / "native_ab.tsv", out / "native-ab", commit=not args.scratch)
    if args.report_only:
        return report(table)

    mod = _runner()
    dirty = mod.uncommitted_objective_sources()
    if dirty and not args.scratch:
        print("the objective's own source is not committed: "
              + ", ".join(dirty) + "\nCommit first (§39.51).")
        return 2
    env = dict(os.environ, HOMEMAKER_ORTHOGONAL_DIVISION="1",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    env.pop("HOMEMAKER_NATIVE", None)       # the flag is the variable; an
    # inherited override would silently set BOTH arms
    os.environ.update(env)
    marks = {arm: stamp(mod, arm) for arm in ARMS}
    search = mod.search_commit()
    # One table, one objective per arm. Rows at another stamp are another
    # experiment; mixing them makes pairs that are not comparable (qkp0).
    stale = sorted({r["objective"] for r in table.rows()} - set(marks.values()))
    if stale:
        print(f"{table.results} holds rows at {', '.join(stale)}; the live "
              f"objective is {marks['quad']} / {marks['native']}.\nMove the old "
              "table aside rather than mixing the two.")
        return 2

    work = Path(tempfile.gettempdir()) / ("native_ab_scratch" if args.scratch else "native_ab")
    arms = {arm: build_arm(work, args.programme, arm) for arm in ARMS}
    queue = [(arm, s) for s in range(args.seeds) for arm in ARMS]
    if args.resume:
        have = {(r["arm"], r["seed"]) for r in table.rows()
                if r["programme"] == args.programme}
        before = len(queue)
        queue = [q for q in queue if (q[0], str(q[1])) not in have]
        print(f"resuming: {before - len(queue)} already recorded, {len(queue)} to run")
    elif any(r["programme"] == args.programme for r in table.rows()):
        print(f"{table.results} already holds {args.programme} rows; pass "
              "--resume to run what is missing")
        return 2
    if not queue:
        print("nothing to do")
        return report(table)

    print(f"{len(queue)} runs on {args.programme}, objective {marks['quad']} / "
          f"{marks['native']}, search {search}, budget {args.budget}, "
          f"{args.slots} slots", flush=True)
    running: dict = {}
    while queue or running:
        while queue and len(running) < args.slots:
            arm, seed = queue.pop(0)
            d = arms[arm]
            dom_out = d / f"native-ab-{args.programme}-{arm}-s{seed}.dom"
            fh = dom_out.with_suffix(".log").open("w")
            cmd = [sys.executable, "-m", "homemaker_layout.evolve", "init.dom",
                   "--budget", str(args.budget), "--seed", str(seed),
                   "--workers", "1", "--output", str(dom_out)]
            if arm == "native":
                cmd.append("--native")
            p = subprocess.Popen(cmd, cwd=d, stdout=subprocess.DEVNULL,
                                 stderr=fh, env=env)
            running[p.pid] = (p, arm, seed, dom_out, fh, time.monotonic())
            print(f"  start {arm} s{seed}", flush=True)
        time.sleep(0.5 if args.scratch else 10)
        for pid, (p, arm, seed, dom_out, fh, st) in list(running.items()):
            if p.poll() is None:
                continue
            fh.close()
            del running[pid]
            el = round(time.monotonic() - st, 1)
            if not dom_out.exists():
                print(f"    FAILED {arm} s{seed} rc={p.returncode} ({el}s): see "
                      f"{dom_out.with_suffix('.log')}", flush=True)
                continue
            sc, fails, hard = score(dom_out, arms["quad"], env)
            print(f"    done {arm} s{seed}: {len(fails)} fails, score {sc:.4g}, "
                  f"{el}s", flush=True)
            table.record(dict(programme=args.programme, arm=arm, seed=seed,
                              objective=marks[arm], search_commit=search,
                              budget=args.budget, storeys=storeys(dom_out),
                              fails=len(fails), hard=hard, soft=len(fails) - hard,
                              score=f"{sc:.6g}", elapsed_s=el, dom=dom_out.name,
                              fail_list=" | ".join(sorted(fails))),
                         dom_out, mod)
    print("\n=== all runs complete ===\n", flush=True)
    return report(table)


if __name__ == "__main__":
    raise SystemExit(main())

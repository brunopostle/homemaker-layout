"""A paired A/B of one `homemaker-evolve` flag: the same seeds with and without.

The shape `e4r_support_outside_ab.py` established, for the flags that have
come since. Each experiment is two arms differing in ONE flag, the control
first:

* **native** (`homemaker-py-8b2u.8`, DESIGN.md §39.104) -- `quad`, the search
  as shipped on Urb's quad tree with orthogonal division, against `native`,
  `--native`: the same operators and genes on a rectangle-frame tree, written
  as format v2. Not the same search with another file format: a ratio is a
  fraction of the node's rectangle, not of a cropped edge. Expectation on
  file: no resolved difference on programme-house; if anything differs it
  will be on the large programmes, where more cells touch the skew boundary.
  `elapsed_s` is part of the answer (a native score costs 13-17% more).
* **w4e** (`homemaker-py-w4e`, DESIGN.md §39.106) -- `shipped` against
  `repaired`, `--core-undivide-repaired`: `core_undivide` as its docstring
  describes it, the inverse of `core_divide`. Expectation on file: no
  resolved difference in fails on programme-house (the move needs a
  `core_divide` to undo, and both are a small share of draws); the thing to
  read is `too few stairs` / `staircase volume`, which the repaired move
  should not make more frequent.

* **t7q** (`homemaker-py-t7q`, DESIGN.md §39.75) -- `repair`, the default,
  against `--no-repair-shaft`. NOTE the flag REMOVES the operator: here the
  control is the arm that has it. The bead holds the expectation.
* **v2k** (`homemaker-py-v2k`, DESIGN.md §39.71) -- the default against
  `--level-add-migrate`. The bead holds the expectation.
* **seedsolve** (`homemaker-py-8b2u.21`, DESIGN.md §39.118) -- seeds as the
  constructor leaves them against `--seed-solver`, which sizes each seed with
  the ratio solver first. In a container that left 8.9 fewer fails per seed
  after tuning. Expectation on file: on programme-house NO resolved difference
  at 500k -- a seed's head start is a few thousand evaluations of a run a
  hundred times longer, and §12.2 found seeding an accelerator, not a new
  asymptote. If anything shows, it is on harbor-house, where the seed gain
  was largest (15 fails), and in the EARLY history of a run, not its end.
* **child40**, **child20** (`homemaker-py-8b2u.20`, DESIGN.md §39.110) --
  `child80`, the per-child inner-loop budget every run has ever used, against
  `--child-budget 40` or `20` at the SAME total budget, so the flagged arm
  breeds two or four times the children. In a container, on converged
  parents, a child tuned for 20 evaluations keeps 7 of the 11 wins that 80
  evaluations find. Expectation on file: the flagged arm ends with no more
  fails than the control on programme-house, and fewer on the large
  programmes if the container result carries into a live population -- which
  is the thing a container cannot say.

**The two arms are scored by one objective.** For `native` that is a fact
with a test behind it: every orthogonal design scores the same as a quad tree
and as the native tree of the same building (192 of 192,
`tests/test_native_tree.py`). The rows still carry different marks --
`<stamp>+orth` and `<stamp>+native` -- because a later reader must be able to
tell which geometry drew an artefact.

Results are committed and pushed per run, as the cold-start runner does it.

Usage::

    python experiments/flag_ab.py native --seeds 36 --slots $(nproc)
    python experiments/flag_ab.py native --programme maple-court --seeds 3 --slots 6
    python experiments/flag_ab.py w4e --seeds 36 --slots $(nproc)
    python experiments/flag_ab.py child20 --seeds 36 --slots $(nproc)
    python experiments/flag_ab.py native --resume
    python experiments/flag_ab.py native --report-only
    python experiments/flag_ab.py w4e --scratch /some/dir --budget 300 --seeds 1   # smoke
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
NATIVE_SUFFIX = "+native"
# name -> (control arm, flagged arm), the flag, the bead and what it is
EXPERIMENTS = {
    "native": dict(arms=("quad", "native"), flag="--native", env="HOMEMAKER_NATIVE",
                   bead="homemaker-py-8b2u.8, DESIGN.md §39.104",
                   what="homemaker-evolve --native against the default search"),
    "w4e": dict(arms=("shipped", "repaired"), flag="--core-undivide-repaired",
                env="HOMEMAKER_CORE_UNDIVIDE_REPAIRED",
                bead="homemaker-py-w4e, DESIGN.md §39.106",
                what="core_undivide repaired against the shipped operator"),
    "t7q": dict(arms=("repair", "norepair"), flag="--no-repair-shaft",
                env="HOMEMAKER_REPAIR_SHAFT",
                bead="homemaker-py-t7q, DESIGN.md §39.75",
                what="the search without mutate_repair_shaft against the default, which has it"),
    "v2k": dict(arms=("shipped", "migrate"), flag="--level-add-migrate",
                env="HOMEMAKER_LEVEL_ADD_MIGRATE",
                bead="homemaker-py-v2k, DESIGN.md §39.71",
                what="level_add_migrate switched on against the default, which has it off"),
    "seedsolve": dict(arms=("built", "solved"), flag="--seed-solver",
                      env="HOMEMAKER_SEED_SOLVER",
                      bead="homemaker-py-8b2u.21, DESIGN.md §39.118",
                      what="seeds sized by the ratio solver against seeds as constructed"),
    "child40": dict(arms=("child80", "child40"), flag="--child-budget 40",
                    env="HOMEMAKER_CHILD_BUDGET",
                    bead="homemaker-py-8b2u.20, DESIGN.md §39.110",
                    what="a 40-evaluation inner loop per child against 80, equal total budget"),
    "child20": dict(arms=("child80", "child20"), flag="--child-budget 20",
                    env="HOMEMAKER_CHILD_BUDGET",
                    bead="homemaker-py-8b2u.20, DESIGN.md §39.110",
                    what="a 20-evaluation inner loop per child against 80, equal total budget"),
}
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
        try:
            n, k = dm.load(str(path)), 0
        except Exception:
            # A native design need not fit Urb's quad tree at all (a cut that
            # misses its cell once cropped to the plot). Loading it that way
            # to count storeys killed the `native` A/B after six pairs, on
            # 2026-10-08, and the queue went on without it.
            n, k = dm.load(str(path), native=True), 0
    finally:
        g.ORTHOGONAL_DIVISION = was
        g.clear_cache()
    while n is not None:
        n, k = n.above, k + 1
    return k


class Table:
    def __init__(self, name: str, out: Path, commit: bool):
        self.name, self.exp = name, EXPERIMENTS[name]
        self.arms = self.exp["arms"]
        self.results = out / f"{name}_ab.tsv"
        self.artefacts = out / f"{name}-ab"
        self.commit = commit

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
                f"{self.name} A/B {row['programme']} {row['arm']} seed {row['seed']}: "
                f"{row['fails']} fails, score {row['score']}",
                f"{self.exp['what']} ({self.exp['bead']}).")


def report(table: Table) -> int:
    """Paired verdicts, per programme, over the seeds both arms finished."""
    ab = _load(REPO / "experiments" / "ab_report.py", "_ab_report")
    rows = table.rows()
    done = False
    for prog in dict.fromkeys(r["programme"] for r in rows):
        by = {(r["arm"], r["seed"]): r for r in rows if r["programme"] == prog}
        seeds = sorted({s for _, s in by if all((a, s) in by for a in table.arms)}, key=int)
        marks = sorted({r["objective"] for r in by.values()})
        print(f"=== {prog}: {len(seeds)} paired seeds; objective {', '.join(marks)}\n")
        if len(seeds) < 2:
            print("  fewer than two complete pairs: nothing to report yet\n")
            continue
        done = True
        for metric in ("fails", "hard", "score", "elapsed_s"):
            off, on = table.arms
            a = [float(by[(off, s)][metric]) for s in seeds]
            b = [float(by[(on, s)][metric]) for s in seeds]
            note = {"score": f"   (mean_diff is {off}-minus-{on}, so NEGATIVE = "
                             f"{on} scored higher = better; W/L is inverted "
                             "for this metric)",
                    "elapsed_s": f"   (seconds; positive mean_diff = {on} faster)"}
            print(f"{metric}:{note.get(metric, '')}")
            print(ab.format_report(ab.paired_report(a, b, off, on)))
            print()
        # stairs are what an operator on the core can cost a building
        for needle in ("too few stairs", "staircase volume", "no outside space"):
            a = [int(needle in by[(off, s)]["fail_list"]) for s in seeds]
            b = [int(needle in by[(on, s)]["fail_list"]) for s in seeds]
            cleared = sum(1 for x, y in zip(a, b) if x and not y)
            broken = sum(1 for x, y in zip(a, b) if y and not x)
            print(f"`{needle}`: {off} {sum(a)}/{len(seeds)}, {on} {sum(b)}/{len(seeds)}; "
                  f"discordant {cleared + broken} ({cleared} cleared, {broken} broken)"
                  + ("  ** fewer than 6 discordant pairs cannot reach p < 0.05 **"
                     if cleared + broken < 6 else ""))
        print()
    return 0 if done else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("experiment", choices=sorted(EXPERIMENTS))
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
    table = Table(args.experiment, out, commit=not args.scratch)
    exp, ARMS = table.exp, table.arms
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
    for e in EXPERIMENTS.values():          # the flag is the variable; an
        env.pop(e["env"], None)             # inherited override would silently
        os.environ.pop(e["env"], None)      # set BOTH arms
    os.environ.update(env)
    marks = {arm: stamp(mod, arm) for arm in ARMS}
    if len(set(marks.values())) == 1:       # one geometry: say so once
        marks_text = marks[ARMS[0]]
    else:
        marks_text = " / ".join(marks[a] for a in ARMS)
    search = mod.search_commit()
    # One table, one objective per arm. Rows at another stamp are another
    # experiment; mixing them makes pairs that are not comparable (qkp0).
    stale = sorted({r["objective"] for r in table.rows()} - set(marks.values()))
    if stale:
        print(f"{table.results} holds rows at {', '.join(stale)}; the live "
              f"objective is {marks_text}.\nMove the old "
              "table aside rather than mixing the two.")
        return 2

    work = Path(tempfile.gettempdir()) / (
        f"{args.experiment}_ab" + ("_scratch" if args.scratch else ""))
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

    print(f"{args.experiment}: {len(queue)} runs on {args.programme}, objective "
          f"{marks_text}, search {search}, budget {args.budget}, "
          f"{args.slots} slots", flush=True)
    running: dict = {}
    while queue or running:
        while queue and len(running) < args.slots:
            arm, seed = queue.pop(0)
            d = arms[arm]
            dom_out = d / f"{args.experiment}-ab-{args.programme}-{arm}-s{seed}.dom"
            fh = dom_out.with_suffix(".log").open("w")
            cmd = [sys.executable, "-m", "homemaker_layout.evolve", "init.dom",
                   "--budget", str(args.budget), "--seed", str(seed),
                   "--workers", "1", "--output", str(dom_out)]
            if arm == ARMS[1]:
                cmd += exp["flag"].split()
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
            sc, fails, hard = score(dom_out, arms[ARMS[0]], env)
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

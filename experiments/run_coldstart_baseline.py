"""Cold-start re-baseline of the four example programmes (`homemaker-py-ssz` fallout).

The objective changed (DESIGN.md §38.10/§38.11: crinkliness is declared per
space), so every prior corpus fail count is stale. This re-runs all four
programmes cold, from `init.dom`, at a fixed budget.

Design notes, all of which matter for the result being trustworthy:

* **One worker per run, four runs at a time.** The box has 4 cores. Running
  four single-worker searches beats one four-worker search here: it saturates
  the cores just as well AND avoids `homemaker-py-b8g`, the parallel/BLAS
  non-determinism that makes `n_workers>1` runs irreproducible. A baseline
  nobody can reproduce is not a baseline.
* **Seed-major order.** The queue runs seed 0 of every programme, then seed 1,
  then seed 2 -- so if the box is lost half way we have all four programmes at
  fewer seeds, rather than one programme at three seeds and nothing else.
* **Timings exclude suspend.** ``elapsed_s`` is measured with
  ``time.monotonic()``, so a run that spans a suspended machine reports the
  time it actually had a CPU rather than wall time. The 39.12 baseline's
  ~430 h total was measured with ``time.time()`` and is only trustworthy
  because that box stayed awake.
* **Commit and push after every finished run.** This is an ephemeral container;
  it is reclaimed on inactivity or session end. Anything not pushed is gone. Git
  calls are serialised under a lock file so the runner cannot race a human (or
  another agent) committing in the same tree.
* **Scored by the shipped scorer**, from inside the programme directory, exactly
  as CLAUDE.md requires -- `homemaker-fitness` resolves patterns.config and
  writes .score/.fails relative to cwd.

Usage::

    python experiments/run_coldstart_baseline.py --budget 500000 --seeds 3
    python experiments/run_coldstart_baseline.py --budget 2000 --seeds 1 --dry-run
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROGRAMMES = ["harbor-house", "maple-court", "health-centre", "programme-house"]
LOCK = REPO / ".git" / "coldstart-git.lock"
RESULTS = REPO / "experiments" / "results" / "coldstart_baseline.tsv"
# The branch this runner publishes to. Named once: it appeared as a
# literal in two git calls, and they must not drift apart.
BRANCH = "claude/beads-project-intro-fjiez3"
FIELDS = ["objective", "programme", "seed", "budget", "fails", "hard", "soft",
          "score", "elapsed_s", "dom"]


def objective_commit() -> str:
    """Short commit of the last change to `fitness.py` -- i.e. which objective
    this run is being scored by.

    Every row carries it because the table did not, once, and the cost was
    real: the 39.12 rows and the `bk9` rows sat in one file under one set of
    column headings, five (programme, seed) pairs appearing twice with
    different fail counts and nothing to say why (DESIGN.md 39.28/39.31). A
    fail count is only comparable to another measured by the same objective,
    so the objective belongs in the row, not in a reader's memory of when the
    sweep was run. This is 39.12 clause 3 -- "any target quoted in a document
    or a test carries the commit it was measured at" -- applied to the table
    that does the quoting.
    """
    # BOTH files, not just fitness.py. geometry.py decides every leaf's area,
    # aspect and width, so a change there changes what every term evaluates --
    # it is as much "the objective" as the scorer is. Stamping only fitness.py
    # meant an orthogonal-division sweep (homemaker-py-32t) took the SAME stamp
    # as a non-orthogonal one and would have written over its artefacts: two
    # objectives under one name, which is precisely what §39.32 exists to stop.
    r = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--",
         "src/homemaker_layout/fitness.py", "src/homemaker_layout/geometry.py"],
        cwd=REPO, capture_output=True, text=True)
    stamp = r.stdout.strip() or "unknown"
    # ...and the run-time switch, which no commit records. ORTHOGONAL_DIVISION
    # is selected by the environment (so it crosses the worker fork), so the
    # same commit can produce two different objectives; the stamp has to say
    # which one ran.
    if os.environ.get("HOMEMAKER_ORTHOGONAL_DIVISION", "") == "1":
        stamp += "+orth"
    return stamp


def committable(candidates: "list[str]", repo: Path = REPO) -> "list[str]":
    """``candidates`` minus the paths git is configured to ignore (7ry).

    `.score` and `.fails` are gitignored (`*.dom.score`, `*.dom.fails`), and
    ``record_and_push`` used to hand them to ``git add`` regardless. ``git add``
    refuses an ignored path and exits non-zero; ``git commit --only`` is then
    given a pathspec naming a file that was never staged and fails with "did not
    match any file(s) known to git". So two ignored sidecars killed the whole
    commit, taking the .dom, the .log and the results table with them.

    That is why the `bk9` sweep committed nothing across twelve runs, with every
    artefact hand-carried by the owner (DESIGN.md §39.33). `2378e5f` made the
    failure audible without fixing it, which is what it said it was doing;
    reproducing it took one 20-second run once someone looked.

    Asking ``git check-ignore`` rather than hardcoding the two suffixes keeps the
    runner working if .gitignore changes underneath it.
    """
    if not candidates:
        return []
    r = subprocess.run(["git", "check-ignore", "--", *candidates],
                       cwd=repo, capture_output=True, text=True)
    ignored = {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}
    return [c for c in candidates if c not in ignored]


@contextmanager
def git_lock():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def score(dom_path: Path) -> tuple[int, int, int, float]:
    """(fails, hard, soft, score) via the shipped scorer, run from the
    programme dir as CLAUDE.md requires."""
    from homemaker_layout.fitness import classify_fail_tier
    subprocess.run(["homemaker-fitness", dom_path.name],
                   cwd=dom_path.parent, capture_output=True, text=True)
    fails_file = dom_path.with_suffix(".dom.fails")
    lines = [ln.strip() for ln in fails_file.read_text().splitlines()
             if ln.strip()] if fails_file.exists() else []
    hard = sum(1 for ln in lines if classify_fail_tier(ln) == "hard")
    score_file = dom_path.with_suffix(".dom.score")
    val = float(score_file.read_text().strip()) if score_file.exists() else float("nan")
    return len(lines), hard, len(lines) - hard, val


def record_and_push(row: dict, artefacts: "list[Path]") -> None:
    rows = []
    if RESULTS.exists():
        rows = list(csv.DictReader(RESULTS.open(), delimiter="\t"))
    rows.append({k: str(row[k]) for k in FIELDS})
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t")
        w.writeheader()
        w.writerows(rows)

    msg = (f"coldstart {row['programme']} seed {row['seed']} @ {row['budget']}: "
           f"{row['fails']} fails ({row['hard']}h/{row['soft']}s)")
    # Commit ONLY this run's artefacts plus the results table. `git add -A` here
    # swept the whole working tree: one completion committed 49 files and ~2M
    # insertions, including three still-running programmes' partial .dom files
    # and unrelated evolved-*.dom, all under a message naming a different
    # programme. `--only` commits exactly the listed paths regardless of what
    # else is staged, so a concurrent edit elsewhere in the tree cannot ride
    # along and in-flight runs are never committed as if they were results.
    paths = [str(a.relative_to(REPO)) for a in artefacts if a.exists()]
    paths.append(str(RESULTS.relative_to(REPO)))

    def _git(*argv) -> "subprocess.CompletedProcess":
        """Run one git command and SAY SO when it fails.

        Every call here used to be `capture_output=True` with the return code
        ignored, and the function then printed "pushed:" unconditionally. A
        failing `git commit` was therefore reported as a successful push after
        every run -- seven completed runs sat on disk for a week looking, from
        the far end, exactly like a job that had never been started. The
        results were never at risk; the reporting was. Failing loudly and
        CONTINUING is the point: a broken git must not cost the queue, and must
        not be silent either.
        """
        r = subprocess.run(["git", *argv], cwd=REPO, capture_output=True, text=True)
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip().splitlines()
            head = err[0] if err else f"exit {r.returncode}"
            print(f"    GIT FAILED: git {' '.join(argv[:2])} -> {head}",
                  flush=True)
        return r

    dropped = [p for p in paths if p not in set(committable(paths))]
    if dropped:
        print(f"    (not committing {len(dropped)} gitignored path(s): "
              f"{', '.join(sorted(Path(d).name for d in dropped))})", flush=True)
    paths = committable(paths)

    committed = pushed = False
    with git_lock():
        _git("add", "--", *paths)
        c = _git("commit", "-q", "--only", *paths, "-m", msg + "\n\n"
                 "Cold-start re-baseline after the DESIGN.md 38.10/38.11 objective\n"
                 "change. Single worker (avoids homemaker-py-b8g), scored by the\n"
                 "shipped scorer from the programme directory.\n\n"
                 "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>\n"
                 "Claude-Session: https://claude.ai/code/session_01MJ84Feep79Hhm3E4zZJmnB")
        committed = c.returncode == 0
        if committed:
            for attempt in range(4):
                # Push FIRST. The previous shape pulled before every attempt,
                # including the first, so on a development box -- where the tree
                # is dirty as a matter of course -- `git pull --rebase` failed
                # with "cannot pull with rebase: You have unstaged changes"
                # even when the push needed no reconciling and would have gone
                # straight through (homemaker-py-cna).
                if _git("push", "-q", "origin", BRANCH).returncode == 0:
                    pushed = True
                    break
                # Only now is there something to reconcile: the remote moved.
                # NO autoStash. It does make the pull succeed on a dirty tree,
                # but when the stashed edit conflicts with what was pulled it
                # leaves the tree in a conflicted state (`UU`) with the work in
                # a stash -- verified, not assumed. The runner does not own this
                # tree; a loud "not pushed" is recoverable and the commit is
                # safe locally, whereas conflicting someone's working copy
                # mid-sweep is not the runner's call to make.
                time.sleep(2 ** (attempt + 1))
                _git("pull", "--rebase", "-q", "origin", BRANCH)

    if pushed:
        print(f"    pushed: {msg}", flush=True)
    elif committed:
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                               capture_output=True, text=True).stdout.strip()
        why = ("\n      -- the working tree is dirty, so `git pull --rebase`"
               " cannot reconcile the moved remote."
               "\n         Commit or stash your own changes, then `git push`."
               if dirty else
               "\n      -- `git push` when git is fixed")
        print(f"    COMMITTED BUT NOT PUSHED: {msg}"
              f"\n      -- the run is safe in git{why}", flush=True)
    else:
        print(f"    NOT COMMITTED: {msg}"
              f"\n      -- the .dom/.score/.fails and {RESULTS.name} are on disk"
              f" and complete;\n         nothing is lost, but nothing is in git"
              f" either", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--budget", type=int, default=500000)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--slots", type=int, default=4,
                    help="concurrent runs; one worker each, so set it to your "
                         "core count (default 4)")
    ap.add_argument("--checkpoint-every", type=int, default=None, metavar="N",
                    help="write each run's best-so-far .dom every N evals "
                         "(default: budget/20). The longest single run in the "
                         "first baseline took 62 h; without this, losing the "
                         "box at hour 61 loses all of it.")
    ap.add_argument("--programmes", nargs="+", default=PROGRAMMES)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    checkpoint_every = (args.checkpoint_every if args.checkpoint_every is not None
                        else max(1, args.budget // 20))
    # Read once, at the start: every row of this sweep is stamped with the same
    # objective, and a mid-sweep edit to fitness.py would otherwise split the
    # sweep in two without saying so.
    objective = objective_commit()

    # seed-major: all programmes at seed 0, then seed 1, ...
    queue = [(p, s) for s in range(args.seeds) for p in args.programmes]
    print(f"{len(queue)} runs, budget {args.budget}, {args.slots} slots, "
          f"checkpoint every {checkpoint_every} evals, seed-major order"
          f"\nobjective: {objective} "
          f"(last change to fitness.py/geometry.py, +orth if the "
          f"orthogonal-division switch is on)\n",
          flush=True)
    if args.dry_run:
        for p, s in queue:
            print(f"  would run {p} seed {s}")
        return

    running: dict = {}
    while queue or running:
        while queue and len(running) < args.slots:
            prog, seed = queue.pop(0)
            d = REPO / "examples" / prog
            # Stamped with the objective, so a sweep never overwrites another
            # objective's results. `de41ce8` wrote the `bk9` outputs straight
            # over the 39.12 layouts under the shared `coldstart-500000-s*`
            # name, which cost the baseline from the working tree, broke a test
            # that had pinned to it, and left the tree holding two objectives'
            # artefacts indistinguishable by filename (DESIGN.md 39.27/39.31).
            stem = f"coldstart-{objective}-{args.budget}-s{seed}"
            out = d / f"{stem}.dom"
            log = d / f"{stem}.log"
            fh = log.open("w")
            proc = subprocess.Popen(
                ["homemaker-evolve", "init.dom", "--budget", str(args.budget),
                 "--seed", str(seed), "--workers", "1", "--output", str(out),
                 "--checkpoint-every", str(checkpoint_every)],
                cwd=d, stdout=subprocess.DEVNULL, stderr=fh)
            # monotonic, NOT time.time(): CLOCK_REALTIME advances while the
            # machine is suspended, so a run spanning an overnight suspend
            # would report elapsed_s inflated by the suspend. CLOCK_MONOTONIC
            # stops (that is what CLOCK_BOOTTIME is for), so this measures the
            # time the run actually had a CPU.
            running[proc.pid] = (proc, prog, seed, out, fh, time.monotonic())
            print(f"  start {prog} seed {seed} -> {out.name}", flush=True)

        time.sleep(10)
        for pid, (proc, prog, seed, out, fh, t0) in list(running.items()):
            if proc.poll() is None:
                continue
            fh.close()
            del running[pid]
            elapsed = round(time.monotonic() - t0, 1)
            if not out.exists():
                print(f"    FAILED {prog} seed {seed} (rc={proc.returncode}, "
                      f"{elapsed}s) -- see the .log", flush=True)
                continue
            n, hard, soft, val = score(out)
            print(f"    done {prog} seed {seed}: {n} fails "
                  f"({hard}h/{soft}s) score {val:.4g} in {elapsed}s", flush=True)
            record_and_push(
                dict(objective=objective, programme=prog, seed=seed,
                     budget=args.budget,
                     fails=n, hard=hard, soft=soft, score=f"{val:.6g}",
                     elapsed_s=elapsed, dom=out.name),
                [out, log, out.with_suffix(".dom.score"), out.with_suffix(".dom.fails")])

    print("\n=== all runs complete ===", flush=True)


if __name__ == "__main__":
    main()

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
          "score", "elapsed_s", "dom", "search_commit", "search_config"]
# `search_commit` / `search_config` (§39.65). Until they existed a row said what
# OBJECTIVE scored it and nothing at all about the SEARCH that produced it, so
# flipping any operator gate -- there are seven, and this runner passes no flags
# for any of them -- silently changed what every future row meant while the rows
# stayed labelled identically. That is §39.42's failure one layer out: the stamp
# covers the objective and nothing covered the search.
#
# Two columns because two different things move, exactly as the objective needs
# both `objective_commit` and the `+orth` environment suffix:
#   search_commit  -- the last commit touching SEARCH_SOURCES; catches a change
#                     to how an operator behaves, or to a default in driver.py.
#   search_config  -- a hash of the EFFECTIVE knob values as `homemaker-evolve`
#                     resolves them; catches an environment override
#                     (HOMEMAKER_SUPPORT_OUTSIDE=1 and friends), which no commit
#                     records. Resolves against
#                     `experiments/results/search_configs/<hash>.json`, written
#                     and committed the first time a configuration is seen, so
#                     the row stays short and the hash stays readable.
#
# Both are ABSOLUTE, not "what differs from today's defaults": a column defined
# relative to the current defaults reads "nothing unusual" again the moment
# someone changes a default, which is the failure it exists to catch.
SEARCH_CONFIGS = REPO / "experiments" / "results" / "search_configs"
# The run-time switch that no commit records, and the suffix it puts on the
# stamp. Named here because three places have to agree on the spelling: this
# runner, `verify_results_table.py`, and anything that re-scores an artefact.
ORTH_ENV = "HOMEMAKER_ORTHOGONAL_DIVISION"
ORTH_SUFFIX = "+orth"
# The files the stamp is computed from -- named once, because `objective_commit`
# and `uncommitted_objective_sources` must agree about what "the objective" is,
# and two copies of that rule is how §39.42 happened.
#
# THE RULE: a file belongs here if changing it changes what a committed `.dom`
# scores. That is not a matter of taste -- it is measurable, and
# `tests/test_objective_sources.py` measures it, by recording which
# `homemaker_layout` modules a single `score_with_fails` actually loads and
# failing if one of them is missing from this tuple. The list rotted twice
# before that guard existed (§39.63); it cannot rot silently now.
#
# This set was fitness.py alone, then + geometry.py (see `objective_commit`),
# and is now all five modules scoring touches. dom.py and graph.py were the
# expensive omissions: `score_with_fails` calls `dom.merge_divided` and
# `preprocess_building` outright and reaches into `graph` for every adjacency
# and connectivity check, so a one-line edit to either moves fail counts while
# the stamp and the uncommitted guard both stay silent -- measured at +2 fails
# over the twelve artefacts for a single line of dom.py (§39.63).
#
# NOT here, deliberately: solver.py, driver.py, operators.py, innerloop.py,
# shapecurve.py, cpsat.py. They decide how the search MOVES, not what it is
# scored against; none of them is loaded by a score. `other_dirty_sources`
# warns about those instead.
OBJECTIVE_SOURCES = ("src/homemaker_layout/dom.py",
                     "src/homemaker_layout/fitness.py",
                     "src/homemaker_layout/geometry.py",
                     "src/homemaker_layout/graph.py",
                     "src/homemaker_layout/programme.py")


# The files that decide how the search MOVES rather than what a layout scores.
# Disjoint from OBJECTIVE_SOURCES by construction, and
# `tests/test_search_config.py` holds the partition: every module under
# src/homemaker_layout must be in exactly one of OBJECTIVE_SOURCES,
# SEARCH_SOURCES or NEITHER_SOURCES, so a new module cannot land unclassified.
SEARCH_SOURCES = ("src/homemaker_layout/cpsat.py",
                  "src/homemaker_layout/driver.py",
                  "src/homemaker_layout/evolve.py",
                  "src/homemaker_layout/genome.py",
                  "src/homemaker_layout/innerloop.py",
                  "src/homemaker_layout/operators.py",
                  "src/homemaker_layout/shapecurve.py",
                  "src/homemaker_layout/solver.py")

# Neither: entry points, dead prototypes, and tooling that produces INPUTS
# rather than participating in a run. No score loads them and no search step
# calls them, so neither stamp is the right place to record a change to one.
#
# `compose.py`/`compose_cmd.py` are the closest call: they build the human
# reference corpus (homemaker-py-2g7.1), so changing one changes the artefacts
# that `homemaker-py-2g7.2` will calibrate the objective against. That matters,
# but it is a property of that corpus and belongs to its own bead -- not to a
# stamp on a coldstart row, which no composed artefact ever appears in.
NEITHER_SOURCES = ("src/homemaker_layout/__init__.py",
                   "src/homemaker_layout/bubble.py",
                   "src/homemaker_layout/collapse_cmd.py",
                   "src/homemaker_layout/compose.py",
                   "src/homemaker_layout/compose_cmd.py",
                   "src/homemaker_layout/fitness_cmd.py")

# The search knobs a row must pin down. Everything else in `homemaker-evolve`'s
# namespace is per-run (budget, seed, workers, output paths) and already in the
# row or irrelevant to it.
SEARCH_KNOBS = ("bridge_circulation", "child_budget", "collapse",
                "collapse_insearch", "collapse_local_search", "conn_grade",
                "leaf_share_factor", "leaf_sharing", "multi_use", "pop",
                "ruin_recreate", "shapecurve_prune", "shapecurve_warmstart",
                "superpose", "support_outside", "use_tiers", "anneal_grain",
                "polish_budget")


def search_commit() -> str:
    """Short commit of the last change to any of SEARCH_SOURCES."""
    r = subprocess.run(["git", "log", "-1", "--format=%h", "--", *SEARCH_SOURCES],
                       cwd=REPO, capture_output=True, text=True)
    return r.stdout.strip() or "unknown"


def search_config() -> "tuple[str, dict]":
    """``(hash, config)`` for the search `homemaker-evolve` will actually run.

    Read from `evolve._parse_args` rather than from `driver.search`'s signature,
    because that is the code the subprocess runs and it is where an environment
    override lands. The runner passes no flag for any of SEARCH_KNOBS, so the
    parser's resolved defaults ARE what every worker will use.
    """
    import hashlib
    import json as _json
    from homemaker_layout import evolve as _evolve

    ns = vars(_evolve._parse_args(["init.dom"]))
    conf = {k: ns[k] for k in SEARCH_KNOBS if k in ns}
    canon = _json.dumps(conf, sort_keys=True, default=str)
    return hashlib.blake2b(canon.encode(), digest_size=5).hexdigest(), conf


def write_search_config(h: str, conf: dict) -> "Path | None":
    """Persist `conf` under its hash; return the path if it was new."""
    import json as _json

    SEARCH_CONFIGS.mkdir(parents=True, exist_ok=True)
    out = SEARCH_CONFIGS / f"{h}.json"
    if out.exists():
        return None
    out.write_text(_json.dumps(conf, indent=2, sort_keys=True, default=str) + "\n")
    return out


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
    # ALL of OBJECTIVE_SOURCES, not just fitness.py, and the set has had to grow
    # twice. geometry.py decides every leaf's area, aspect and width, so a
    # change there changes what every term evaluates; stamping only fitness.py
    # meant an orthogonal-division sweep (homemaker-py-32t) took the SAME stamp
    # as a non-orthogonal one and would have written over its artefacts: two
    # objectives under one name, which is precisely what §39.32 exists to stop.
    # dom.py and graph.py are in the scoring path just as directly (§39.63) and
    # were missing for the same reason: the list was written from memory of what
    # "the objective" means rather than from what a score actually executes.
    r = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", *OBJECTIVE_SOURCES],
        cwd=REPO, capture_output=True, text=True)
    stamp = r.stdout.strip() or "unknown"
    # ...and the run-time switch, which no commit records. ORTHOGONAL_DIVISION
    # is selected by the environment (so it crosses the worker fork), so the
    # same commit can produce two different objectives; the stamp has to say
    # which one ran.
    if os.environ.get(ORTH_ENV, "") == "1":
        stamp += ORTH_SUFFIX
    return stamp


def uncommitted(paths, repo: Path = REPO) -> "list[str]":
    """Which of ``paths`` differ from HEAD -- staged, unstaged or untracked."""
    r = subprocess.run(["git", "status", "--porcelain", "--", *paths],
                       cwd=repo, capture_output=True, text=True)
    return sorted(ln[3:].strip() for ln in r.stdout.splitlines() if ln.strip())


def uncommitted_objective_sources(repo: Path = REPO) -> "list[str]":
    """The objective's own source files that are not in any commit.

    `objective_commit` asks `git log`, and git log cannot see the working tree.
    So a sweep started over uncommitted edits to any of `OBJECTIVE_SOURCES`
    stamps every row -- and names every artefact -- with the commit BEFORE those
    edits: a week of runs labelled as an objective that is not the one that
    scored them, and filenames that can overwrite the real one's. That is §39.42
    again, arriving through the working tree instead of through the file list
    (homemaker-py-jui).

    Caught the honest way: while landing §39.50 the verifier reported twelve
    mismatches at the old stamp, having correctly noticed that scoring had
    changed and wrongly attributed it to the objective that had not.
    """
    return uncommitted(OBJECTIVE_SOURCES, repo)


def other_dirty_sources(repo: Path = REPO) -> "list[str]":
    """Dirty `src/` files that are NOT part of the objective.

    A different and lesser problem, so it warns rather than refuses. An edited
    `driver.py` or `operators.py` changes how the search moves but not what it
    is scored against, so the rows are still labelled correctly -- they just
    cannot be reproduced from any commit.
    """
    return [p for p in uncommitted(["src"], repo) if p not in OBJECTIVE_SOURCES]


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


# Lines git prints on the way to an error that do not say what the error was.
# `git push` opens with the remote URL, so the FIRST stderr line of a rejected
# push is "To github.com:owner/repo.git" -- which is what the runner reported
# for a whole class of failures, naming the remote it was talking to instead of
# what went wrong (DESIGN.md §39.45).
_GIT_BANNER = ("To ", "remote:", "hint:", "Everything up-to-date", "Enumerating",
               "Counting", "Compressing", "Writing", "Total ", "Resolving",
               "Delta compression")


def git_error_line(r: "subprocess.CompletedProcess") -> str:
    """The one line of a failed git command that says what actually went wrong.

    Ordered by how specific the line is, not by where it appears: `fatal:`
    first, then the `! [rejected] ...` line -- which names the branch AND the
    reason, and is more use than the `error: failed to push some refs` that
    follows it -- then `error:`, then the first line that is not git's own
    progress chatter.
    """
    lines = [ln.rstrip() for ln in
             ((r.stderr or "") + "\n" + (r.stdout or "")).splitlines() if ln.strip()]
    for ln in lines:
        if ln.lower().startswith("fatal:"):
            return ln
    for ln in lines:
        if ln.lstrip().startswith("!"):
            return ln.strip()
    for ln in lines:
        if ln.lower().startswith("error:"):
            return ln
    for ln in lines:
        if not ln.startswith(_GIT_BANNER):
            return ln
    return lines[0] if lines else f"exit {r.returncode}"


def recorded_pairs(objective: str, budget: int) -> "set[tuple[str, int]]":
    """(programme, seed) already in the table for this objective and budget."""
    if not RESULTS.exists():
        return set()
    return {(r["programme"], int(r["seed"]))
            for r in csv.DictReader(RESULTS.open(), delimiter="\t")
            if r["objective"] == objective and int(r["budget"]) == budget}


def drop_rows(objective: str, budget: int) -> int:
    """Remove this objective+budget's rows from the table; return how many.

    For `--restart`, which is about to re-run those pairs and overwrite the
    artefacts they name. Dropping the rows first is what keeps the table from
    describing files that no longer exist: artefact names are built from the
    objective, so a re-run of the same objective REPLACES them in place, and a
    row left behind then points at someone else's layout (DESIGN.md §39.44).
    """
    rows = list(csv.DictReader(RESULTS.open(), delimiter="\t"))
    keep = [r for r in rows
            if not (r["objective"] == objective and int(r["budget"]) == budget)]
    with RESULTS.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, delimiter="\t")
        w.writeheader()
        w.writerows({k: r.get(k, "-") for k in FIELDS} for r in keep)
    return len(rows) - len(keep)


def record_failure(prog: str, seed: int, log: Path, rc: int,
                   elapsed: float) -> None:
    """Put a crashed run's log in git, under a message that says it crashed.

    A failure used to `continue` before any git call, so it left no trace at
    all in the pushed history -- no row, no artefact, no log. From the far end
    a programme that crashes on every seed is then indistinguishable from one
    whose runs are merely slow, which is how an orthogonal-division sweep ran
    for two days with harbor-house dead in the bootstrap and nothing said so
    (DESIGN.md §39.44). This is §39.33's lesson again: the results were never
    at risk, the reporting was.

    No results-table row: a crash produced no fail count, and inventing one
    would be worse than the silence. The log is the record.
    """
    if not log.exists():
        print(f"    (no log to commit for {prog} seed {seed})", flush=True)
        return
    commit_and_push(
        [str(log.relative_to(REPO))],
        f"coldstart {prog} seed {seed}: FAILED (rc={rc}, {elapsed}s)",
        "The run produced no .dom. Committing the log so the failure is\n"
        "visible from outside the box it ran on.")


def record_and_push(row: dict, artefacts: "list[Path]") -> None:
    rows = []
    if RESULTS.exists():
        rows = list(csv.DictReader(RESULTS.open(), delimiter="\t"))
    # `.get`: rows written before §39.65 added the search columns have no
    # value for them, and "-" is the honest one -- the configuration was not
    # recorded and cannot be recovered.
    rows.append({k: str(row.get(k, "-")) for k in FIELDS})
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
    commit_and_push(paths, msg)


def commit_and_push(paths: "list[str]", msg: str, note: str = "") -> None:
    """Commit exactly ``paths`` under ``msg``, then push with backoff.

    Shared by the result path and the failure path so the two cannot drift.
    """
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
            print(f"    GIT FAILED: git {' '.join(argv[:2])} -> "
                  f"{git_error_line(r)}", flush=True)
        return r

    dropped = [p for p in paths if p not in set(committable(paths))]
    if dropped:
        print(f"    (not committing {len(dropped)} gitignored path(s): "
              f"{', '.join(sorted(Path(d).name for d in dropped))})", flush=True)
    paths = committable(paths)
    if not paths:
        print(f"    NOTHING COMMITTABLE: {msg}", flush=True)
        return

    body = (note + "\n\n" if note else
            "Cold-start re-baseline after the DESIGN.md 38.10/38.11 objective\n"
            "change. Single worker (avoids homemaker-py-b8g), scored by the\n"
            "shipped scorer from the programme directory.\n\n")

    committed = pushed = False
    with git_lock():
        _git("add", "--", *paths)
        c = _git("commit", "-q", "--only", *paths, "-m", msg + "\n\n" + body
                 + "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>\n"
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
              f"\n      -- the artefacts are on disk and complete;"
              f"\n         nothing is lost, but nothing is in git", flush=True)


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
    # A restart is the normal case here, not an edge case: these sweeps run for
    # days and get stopped. There is no resume, so a restart re-runs the whole
    # queue -- and because artefact names are built from the objective, it
    # OVERWRITES the earlier attempt's .dom files while their rows stay in the
    # table describing layouts that no longer exist. That happened on the 32t
    # sweep (DESIGN.md §39.44). The stamp cannot catch it: two runs of one
    # objective legitimately share a name. So the runner asks.
    ap.add_argument("--resume", action="store_true",
                    help="skip (programme, seed) pairs already recorded at this "
                         "objective and budget, and keep their rows")
    ap.add_argument("--restart", action="store_true",
                    help="re-run those pairs, dropping their now-superseded "
                         "rows first (their .dom files are overwritten)")
    args = ap.parse_args()
    if args.resume and args.restart:
        ap.error("--resume and --restart are opposites; pick one")
    checkpoint_every = (args.checkpoint_every if args.checkpoint_every is not None
                        else max(1, args.budget // 20))
    # Before the stamp is taken, not after: a stamp computed over uncommitted
    # edits is a label for an objective that does not exist anywhere (§39.51).
    dirty = uncommitted_objective_sources()
    if dirty:
        print(f"the objective's own source is not committed:\n"
              + "".join(f"  {p}\n" for p in dirty)
              + f"\n`objective_commit` asks `git log`, which cannot see the "
                f"working tree, so every\nrow of this sweep would be stamped "
                f"with the commit BEFORE these edits -- and the\nartefacts "
                f"named from it, where they can overwrite that objective's "
                f"(DESIGN.md\n§39.32, §39.51).\n\n"
                f"Commit them and run again. There is deliberately no override: "
                f"a stamp nobody\ncan check is worse than a sweep that did not "
                f"start.",
              flush=True)
        raise SystemExit(2)
    stale = other_dirty_sources()
    if stale:
        print(f"WARNING: {len(stale)} uncommitted src/ file(s) that are not the "
              f"objective:\n" + "".join(f"  {p}\n" for p in stale)
              + "These do not change what the runs are scored against, so the "
                "rows stay\ncorrectly labelled -- but the search that produced "
                "them is not in any commit,\nso nobody can reproduce it. "
                "Continuing.\n", flush=True)

    # Read once, at the start: every row of this sweep is stamped with the same
    # objective, and a mid-sweep edit to fitness.py would otherwise split the
    # sweep in two without saying so.
    objective = objective_commit()
    # Taken ONCE, here, for the same reason the objective stamp is: every worker
    # is a separate process reading the same installed code, and a mid-sweep edit
    # must not silently relabel half the rows (§39.65).
    search_c = search_commit()
    search_h, search_conf = search_config()
    # NOT under --dry-run: a dry run must leave the tree alone, which is the
    # rule `test_a_dry_run_never_edits_the_table` exists for -- and a sidecar
    # is as much a write as a table row.
    search_json = (None if args.dry_run
                   else write_search_config(search_h, search_conf))

    # seed-major: all programmes at seed 0, then seed 1, ...
    queue = [(p, s) for s in range(args.seeds) for p in args.programmes]

    done = recorded_pairs(objective, args.budget) & set(queue)
    if done and not (args.resume or args.restart):
        listing = ", ".join(f"{p} s{s}" for p, s in sorted(done))
        print(f"objective {objective} already has {len(done)} row(s) in "
              f"{RESULTS.name} at budget {args.budget}:\n  {listing}\n\n"
              f"Running the queue again would overwrite the .dom files those "
              f"rows name,\nleaving the table describing layouts that no longer "
              f"exist (DESIGN.md §39.44).\nSay which you meant:\n"
              f"  --resume   keep those rows and run only the {len(queue) - len(done)} "
              f"remaining pair(s)\n"
              f"  --restart  drop those rows and re-run everything",
              flush=True)
        raise SystemExit(2)
    if args.resume and done:
        queue = [(p, s) for p, s in queue if (p, s) not in done]
        print(f"resuming: {len(done)} pair(s) already recorded at {objective}, "
              f"{len(queue)} to run", flush=True)
    elif args.restart and done and not args.dry_run:
        print(f"restarting: dropped {drop_rows(objective, args.budget)} "
              f"superseded row(s) at {objective}", flush=True)

    if not queue:
        print(f"nothing to do: every pair is already recorded at {objective}.",
              flush=True)
        return

    print(f"{len(queue)} runs, budget {args.budget}, {args.slots} slots, "
          f"checkpoint every {checkpoint_every} evals, seed-major order"
          f"\nobjective: {objective} "
          f"(last change to OBJECTIVE_SOURCES, +orth if the "
          f"orthogonal-division switch is on)"
          f"\nsearch   : {search_c} config {search_h}"
          + (f" (new, written to {search_json.name})" if search_json else "")
          + (" [dry run: sidecar not written]" if args.dry_run else "")
          + "\n           "
          + ", ".join(f"{k}={search_conf[k]}" for k in sorted(search_conf)
                      if k in ("support_outside", "bridge_circulation",
                               "ruin_recreate", "use_tiers", "leaf_sharing",
                               "collapse_insearch"))
          + "\n",
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
            # `log` belongs in here, not read back from the enclosing scope at
            # reap time. Python leaks the dispatch loop's variables, so
            # `record_and_push` was handed whichever log was opened LAST --
            # i.e. a different, still-running run's. Verified in the two
            # commits 0069eff and 2e399b6: the health-centre s0 result carries
            # health-centre s1's log, and the s1 result carries maple-court
            # s2's. Each finished run therefore lost its own log, and a partial
            # snapshot of an in-flight job was committed under a message naming
            # someone else -- exactly what `commit --only` was introduced to
            # stop, arriving through the argument list instead of the index.
            running[proc.pid] = (proc, prog, seed, out, log, fh, time.monotonic())
            print(f"  start {prog} seed {seed} -> {out.name}", flush=True)

        time.sleep(10)
        for pid, (proc, prog, seed, out, log, fh, t0) in list(running.items()):
            if proc.poll() is None:
                continue
            fh.close()
            del running[pid]
            elapsed = round(time.monotonic() - t0, 1)
            if not out.exists():
                print(f"    FAILED {prog} seed {seed} (rc={proc.returncode}, "
                      f"{elapsed}s) -- see the .log", flush=True)
                record_failure(prog, seed, log, proc.returncode, elapsed)
                continue
            n, hard, soft, val = score(out)
            print(f"    done {prog} seed {seed}: {n} fails "
                  f"({hard}h/{soft}s) score {val:.4g} in {elapsed}s", flush=True)
            record_and_push(
                dict(objective=objective, programme=prog, seed=seed,
                     budget=args.budget,
                     fails=n, hard=hard, soft=soft, score=f"{val:.6g}",
                     elapsed_s=elapsed, dom=out.name,
                     search_commit=search_c, search_config=search_h),
                [out, log, out.with_suffix(".dom.score"), out.with_suffix(".dom.fails")]
                + ([search_json] if search_json else []))

    print("\n=== all runs complete ===", flush=True)


if __name__ == "__main__":
    main()

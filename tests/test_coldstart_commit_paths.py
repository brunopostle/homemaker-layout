"""The coldstart runner must not hand git a path git is told to ignore (7ry).

`.score` and `.fails` match `*.dom.score` / `*.dom.fails` in .gitignore.
``record_and_push`` passed them to ``git add`` anyway; ``git add`` refuses an
ignored path and exits non-zero, and ``git commit --only`` is then handed a
pathspec naming a file that was never staged, so it fails with "did not match
any file(s) known to git". Two ignored sidecars killed the whole commit and took
the .dom, the .log and the results table with them.

That is the mechanism behind DESIGN.md §39.33: twelve `bk9` runs, zero
runner-authored commits, every artefact hand-carried. The guard here is cheap
and the bug cost a sweep.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parent.parent / "experiments" / "run_coldstart_baseline.py"
pytestmark = pytest.mark.skipif(not RUNNER.is_file(), reason="runner absent")


def _runner():
    spec = importlib.util.spec_from_file_location("coldstart_runner", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *argv):
    return subprocess.run(["git", *argv], cwd=repo, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q", ".")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text("*.dom.score\n*.dom.fails\n")
    _git(tmp_path, "add", ".gitignore")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def test_ignored_sidecars_are_dropped(repo):
    for name in ("a.dom", "a.dom.log", "a.dom.score", "a.dom.fails"):
        (repo / name).write_text("x\n")
    kept = _runner().committable(
        ["a.dom", "a.dom.log", "a.dom.score", "a.dom.fails"], repo=repo)
    assert kept == ["a.dom", "a.dom.log"]


def test_nothing_is_dropped_when_nothing_is_ignored(repo):
    (repo / ".gitignore").write_text("")
    for name in ("a.dom", "a.dom.score"):
        (repo / name).write_text("x\n")
    kept = _runner().committable(["a.dom", "a.dom.score"], repo=repo)
    assert kept == ["a.dom", "a.dom.score"]


def test_the_empty_case_is_not_a_git_call(repo):
    assert _runner().committable([], repo=repo) == []


def test_add_and_commit_only_succeed_on_the_filtered_list(repo):
    """The end-to-end shape of the bug: `git add` plus `git commit --only` over
    the UNFILTERED list fails, and over the filtered list succeeds."""
    for name in ("a.dom", "a.dom.score"):
        (repo / name).write_text("x\n")
    raw = ["a.dom", "a.dom.score"]

    assert _git(repo, "add", "--", *raw).returncode != 0, (
        "git add should refuse an ignored path -- if this ever starts passing, "
        "the filter is still right but this test no longer proves why")
    assert _git(repo, "commit", "-q", "--only", *raw, "-m", "x").returncode != 0

    kept = _runner().committable(raw, repo=repo)
    assert _git(repo, "add", "--", *kept).returncode == 0
    assert _git(repo, "commit", "-q", "--only", *kept, "-m", "x").returncode == 0
    assert "a.dom" in _git(repo, "show", "--stat", "--format=", "HEAD").stdout


# --------------------------------------------------------------------------- #
# Push ordering on a dirty tree (homemaker-py-cna)
# --------------------------------------------------------------------------- #

def test_push_is_attempted_before_any_pull(repo):
    """The retry loop must push FIRST.

    It used to `git pull --rebase` before every attempt, including the first, so
    on a development box -- where the tree is dirty as a matter of course -- the
    pull failed with "cannot pull with rebase: You have unstaged changes" even
    when the push needed no reconciling at all. A source check, because the bug
    is an ORDER and there is no value to assert.
    """
    src = RUNNER.read_text()
    body = src[src.index("if committed:"):src.index("if pushed and not missed")
                if "if pushed and not missed" in src else len(src)]
    push_at = body.index('_git("push"')
    pull_at = body.index('_git("pull"')
    assert push_at < pull_at, (
        "the pull is attempted before the push -- a dirty tree then blocks a "
        "push that needed no reconciling (homemaker-py-cna)")


def test_the_runner_does_not_autostash_the_owners_tree(repo):
    """autoStash makes the pull succeed on a dirty tree, but when the stashed
    edit conflicts with what was pulled it leaves the tree CONFLICTED with the
    work in a stash. The runner does not own this tree: a loud "not pushed" is
    recoverable, a conflicted working copy mid-sweep is not its call."""
    src = RUNNER.read_text()
    # the USE, not the word: the comment above the pull explains why it is
    # avoided, and a test that cannot tell those apart is worthless.
    assert "rebase.autoStash=true" not in src
    assert "--autostash" not in src.lower().replace("rebase.autostash", "")


def test_a_dirty_tree_blocks_rebase_which_is_why_order_matters(repo):
    """The behaviour the ordering works around, asserted rather than assumed."""
    (repo / "tracked.txt").write_text("base\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-qm", "base")
    (repo / "tracked.txt").write_text("edited, uncommitted\n")
    r = _git(repo, "pull", "--rebase", "-q", ".", "HEAD")
    assert r.returncode != 0
    assert "unstaged" in (r.stderr + r.stdout).lower()


# --------------------------------------------------------------------------- #
# The objective stamp must name the whole objective (homemaker-py-32t fallout)
# --------------------------------------------------------------------------- #

def test_the_stamp_covers_geometry_not_just_the_scorer():
    """geometry.py decides every leaf's area, aspect and width, so a change
    there changes what every term evaluates. Stamping only fitness.py let an
    orthogonal-division sweep take the same stamp as a non-orthogonal one --
    and, because artefact filenames are built from the stamp, write over its
    results. Two objectives under one name is what §39.32 exists to stop."""
    src = RUNNER.read_text()
    i = src.index("def objective_commit")
    body = src[i:i + 2000]
    assert "geometry.py" in body, "the stamp ignores geometry.py"
    assert "fitness.py" in body


def test_the_runtime_switch_is_in_the_stamp(monkeypatch):
    """ORTHOGONAL_DIVISION is selected by the environment so it crosses the
    worker fork, which means one commit can produce two different objectives.
    No commit records which ran, so the stamp has to."""
    mod = _runner()
    monkeypatch.delenv("HOMEMAKER_ORTHOGONAL_DIVISION", raising=False)
    off = mod.objective_commit()
    monkeypatch.setenv("HOMEMAKER_ORTHOGONAL_DIVISION", "1")
    on = mod.objective_commit()
    assert off != on, "the same stamp for two different geometries"
    assert on.endswith("+orth")
    assert on.startswith(off)


VERIFIER = RUNNER.parent / "verify_results_table.py"


def _verifier():
    if not VERIFIER.is_file():
        pytest.skip("verifier absent")
    spec = importlib.util.spec_from_file_location("coldstart_verifier", VERIFIER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_verifier_does_not_keep_its_own_copy_of_the_rule():
    """Two copies of this rule drifted apart once already. A verifier that
    computes the stamp its own way cannot detect that -- it agrees with
    itself."""
    if not VERIFIER.is_file():
        pytest.skip("verifier absent")
    src = VERIFIER.read_text()
    i = src.index("def source_commit")
    body = src[i:i + 1200]
    assert "objective_commit" in body, (
        "the verifier re-derives the stamp instead of asking the runner")


def test_the_verifier_reads_the_switch_off_the_row_not_the_environment(monkeypatch):
    """Which rows are live is a question about the SOURCE; which geometry a row
    was measured under is a question about the ROW. Deriving both from the
    environment meant one invocation could only ever check the half of the
    table that matched it -- and forgetting the variable skipped every
    orthogonal row while printing "0 mismatched", which reads like success."""
    mod = _verifier()
    monkeypatch.delenv("HOMEMAKER_ORTHOGONAL_DIVISION", raising=False)
    off = mod.source_commit()
    monkeypatch.setenv("HOMEMAKER_ORTHOGONAL_DIVISION", "1")
    assert mod.source_commit() == off, (
        "the set of live rows moves when the environment does")
    assert mod.split_objective(off + "+orth") == (off, True)
    assert mod.split_objective(off) == (off, False)


def test_the_verifier_scores_each_row_under_its_own_switch():
    """A row measured with orthogonal division on only reproduces with the
    switch on: scoring it with the switch off yields a different layout and a
    mismatch that says nothing about the table. So the scorer's environment is
    built per row, not inherited."""
    src = VERIFIER.read_text() if VERIFIER.is_file() else pytest.skip("verifier absent")
    i = src.index("def score(")
    body = src[i:src.index("def main")]
    assert "env=env" in body, "the scorer inherits the switch instead of being told"
    assert "ORTH_ENV" in body, "the verifier hardcodes the variable name"


def test_the_switch_and_its_suffix_are_named_once():
    """Three places have to agree on the spelling of the variable and the
    suffix: the runner, the verifier, and anything that re-scores an artefact.
    A literal in each is three chances to typo one."""
    mod = _runner()
    assert mod.ORTH_ENV == "HOMEMAKER_ORTHOGONAL_DIVISION"
    assert mod.ORTH_SUFFIX == "+orth"
    if VERIFIER.is_file():
        assert '"+orth"' not in VERIFIER.read_text(), (
            "the verifier spells the suffix itself instead of asking the runner")


def test_scoring_a_row_ignores_the_ambient_switch(monkeypatch):
    """End-to-end: the same artefact, scored both ways, must give two different
    answers (or the switch is not reaching the scorer at all), and each answer
    must not move when the ambient environment is set the other way.

    The numbers are not pinned -- only that they differ and that they are the
    verifier's to choose. On the corpus this gap is around ten failures, which
    is what a mis-scored half of the table would have reported as mismatches.
    """
    mod = _verifier()
    repo = RUNNER.parent.parent
    import csv as _csv
    table = repo / "experiments" / "results" / "coldstart_baseline.tsv"
    if not table.is_file():
        pytest.skip("results table absent")
    rows = [r for r in _csv.DictReader(table.open(), delimiter="\t")
            if (repo / "examples" / r["programme"] / r["dom"]).is_file()]
    if not rows:
        pytest.skip("no committed artefacts to score")
    row = rows[0]

    monkeypatch.setenv("HOMEMAKER_ORTHOGONAL_DIVISION", "0")
    off = mod.score(row["programme"], row["dom"], orthogonal=False)
    on = mod.score(row["programme"], row["dom"], orthogonal=True)
    assert off is not None and on is not None
    assert off != on, "the orthogonal switch does not reach the scorer"

    monkeypatch.setenv("HOMEMAKER_ORTHOGONAL_DIVISION", "1")
    assert mod.score(row["programme"], row["dom"], orthogonal=False) == off
    assert mod.score(row["programme"], row["dom"], orthogonal=True) == on


# --------------------------------------------------------------------------- #
# A finished run must be committed with its OWN log, and a crash must leave a
# trace at all (homemaker-py-32t fallout, DESIGN.md §39.44)
# --------------------------------------------------------------------------- #

def _main_fn():
    import ast
    tree = ast.parse(RUNNER.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("no main() in the runner")


def test_the_reap_loop_takes_the_log_from_the_job_it_reaped():
    """Python leaks a loop's variables, so reading `log` at reap time got
    whichever log was opened LAST -- a different, still-running job's.

    Verified in the pushed history: commit 0069eff records health-centre seed 0
    and carries health-centre s1's log; 2e399b6 records seed 1 and carries
    maple-court s2's. Every finished run lost its own log, and a partial
    snapshot of an in-flight job rode in under a message naming someone else.
    The state a reap needs belongs in `running`, not in the enclosing scope.
    """
    import ast
    for node in ast.walk(_main_fn()):
        if not (isinstance(node, ast.For) and isinstance(node.target, ast.Tuple)):
            continue
        names = {n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)}
        if {"proc", "prog", "seed", "out"} <= names:
            assert "log" in names, (
                "the reap loop reads `log` from the dispatch loop's scope, so a "
                "result is committed with another run's log")
            return
    raise AssertionError("no reap loop found in main()")


def test_a_crashed_run_is_not_silent_in_git():
    """A failure used to `continue` before any git call: no row, no artefact,
    no log. A programme that crashes on every seed then looks, from the far
    end, exactly like one whose runs are slow -- which is how an orthogonal
    sweep ran two days with harbor-house dead in the bootstrap."""
    import ast
    calls = [n for n in ast.walk(_main_fn())
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "record_failure"]
    assert calls, "a crashed run records nothing"

    for node in ast.walk(_main_fn()):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.UnaryOp)
                and isinstance(node.test.op, ast.Not)):
            src = ast.dump(node.test)
            if "exists" in src and "out" in src:
                assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                           and n.func.id == "record_failure"
                           for n in ast.walk(node)), (
                    "the `no .dom` branch does not record the failure")
                return
    raise AssertionError("no `not out.exists()` branch found")


def test_a_failure_commits_no_results_row():
    """A crash produced no fail count. Inventing one would be worse than the
    silence it replaces, so `record_failure` commits the log and nothing else."""
    import inspect
    mod = _runner()
    src = inspect.getsource(mod.record_failure)
    assert "RESULTS" not in src, "a failure writes a results-table row"


def test_record_failure_survives_a_missing_log(capsys, monkeypatch):
    """The log is opened at dispatch, so it normally exists -- but a failure
    path that raises would take the whole sweep down with it."""
    mod = _runner()
    called = []
    monkeypatch.setattr(mod, "commit_and_push",
                        lambda *a, **k: called.append(a))
    mod.record_failure("harbor-house", 0, Path("/nonexistent/x.log"), 1, 3.0)
    assert not called
    assert "no log to commit" in capsys.readouterr().out


def test_every_row_names_an_artefact_that_exists():
    """At EVERY objective, not just the current one.

    Re-scoring can only speak for rows at the current commit, so a row whose
    .dom was deleted or overwritten under an older objective went unchallenged.
    That is how two rows describing a crashed orthogonal sweep outlived the
    files they described: the artefact was overwritten by a restart, the row
    stayed, and the verifier skipped it as "another objective" (§39.44).
    """
    import csv as _csv
    repo = RUNNER.parent.parent
    table = repo / "experiments" / "results" / "coldstart_baseline.tsv"
    if not table.is_file():
        pytest.skip("results table absent")
    orphans = [f"{r['objective']} {r['programme']} s{r['seed']} -> {r['dom']}"
               for r in _csv.DictReader(table.open(), delimiter="\t")
               if not (repo / "examples" / r["programme"] / r["dom"]).is_file()]
    assert not orphans, (
        "rows naming artefacts that are not in the tree:\n  "
        + "\n  ".join(orphans))


def test_the_verifier_checks_orphans_before_it_skips():
    """The check must not sit behind the objective filter -- that is the filter
    that hid the problem."""
    if not VERIFIER.is_file():
        pytest.skip("verifier absent")
    src = VERIFIER.read_text()
    body = src[src.index("def main("):]
    assert "orphans" in body, "the verifier does not look for orphaned rows"
    assert body.index("orphans") < body.index('if commit != want'), (
        "the orphan check runs after the objective filter, so rows at other "
        "objectives are skipped before they are checked")


# --------------------------------------------------------------------------- #
# A restart must not overwrite the previous attempt's artefacts silently
# (homemaker-py-9cu, DESIGN.md §39.44)
# --------------------------------------------------------------------------- #

def _table(tmp_path, rows):
    import csv as _csv
    mod = _runner()
    p = tmp_path / "coldstart_baseline.tsv"
    with p.open("w", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=mod.FIELDS, delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in mod.FIELDS})
    return p


def _row(objective, programme, seed, budget=500000):
    return dict(objective=objective, programme=programme, seed=seed,
                budget=budget, fails=1, hard=0, soft=1, score="0.1",
                elapsed_s=1.0, dom=f"coldstart-{objective}-{budget}-s{seed}.dom")


def test_recorded_pairs_is_scoped_to_objective_and_budget(tmp_path, monkeypatch):
    mod = _runner()
    monkeypatch.setattr(mod, "RESULTS", _table(tmp_path, [
        _row("aaa1111", "harbor-house", 0),
        _row("aaa1111", "maple-court", 1),
        _row("bbb2222", "harbor-house", 2),          # another objective
        _row("aaa1111", "health-centre", 0, 2000),   # another budget
    ]))
    assert mod.recorded_pairs("aaa1111", 500000) == {
        ("harbor-house", 0), ("maple-court", 1)}


def test_drop_rows_leaves_every_other_objective_alone(tmp_path, monkeypatch):
    mod = _runner()
    monkeypatch.setattr(mod, "RESULTS", _table(tmp_path, [
        _row("aaa1111", "harbor-house", 0),
        _row("bbb2222", "harbor-house", 0),
        _row("aaa1111", "maple-court", 0, 2000),
    ]))
    assert mod.drop_rows("aaa1111", 500000) == 1
    left = mod.recorded_pairs("bbb2222", 500000) | mod.recorded_pairs("aaa1111", 2000)
    assert left == {("harbor-house", 0), ("maple-court", 0)}


def _run_main(mod, monkeypatch, argv):
    import sys as _sys
    monkeypatch.setattr(_sys, "argv", ["run_coldstart_baseline.py", *argv])
    return mod.main()


def test_a_colliding_sweep_refuses_rather_than_overwriting(tmp_path, monkeypatch,
                                                           capsys):
    """This is the failure it exists for: artefact names are built from the
    objective, so re-running a queue REPLACES the earlier attempt's .dom files
    while their rows stay behind describing layouts that are gone. The stamp
    cannot catch it -- two runs of one objective legitimately share a name."""
    mod = _runner()
    monkeypatch.setattr(mod, "objective_commit", lambda: "aaa1111")
    monkeypatch.setattr(mod, "RESULTS", _table(tmp_path, [
        _row("aaa1111", "harbor-house", 0)]))
    with pytest.raises(SystemExit) as e:
        _run_main(mod, monkeypatch,
                  ["--budget", "500000", "--seeds", "1", "--dry-run"])
    assert e.value.code == 2
    out = capsys.readouterr().out
    assert "--resume" in out and "--restart" in out
    assert "harbor-house s0" in out


def test_resume_runs_only_what_is_missing(tmp_path, monkeypatch, capsys):
    mod = _runner()
    monkeypatch.setattr(mod, "objective_commit", lambda: "aaa1111")
    monkeypatch.setattr(mod, "RESULTS", _table(tmp_path, [
        _row("aaa1111", "harbor-house", 0)]))
    _run_main(mod, monkeypatch,
              ["--budget", "500000", "--seeds", "1", "--resume", "--dry-run"])
    out = capsys.readouterr().out
    assert "would run harbor-house seed 0" not in out
    assert "would run maple-court seed 0" in out
    # the row it skipped is still there
    assert mod.recorded_pairs("aaa1111", 500000) == {("harbor-house", 0)}


def test_a_dry_run_never_edits_the_table(tmp_path, monkeypatch):
    """--restart drops rows. A dry run that did it anyway would destroy the
    thing the operator was checking on."""
    mod = _runner()
    monkeypatch.setattr(mod, "objective_commit", lambda: "aaa1111")
    monkeypatch.setattr(mod, "RESULTS", _table(tmp_path, [
        _row("aaa1111", "harbor-house", 0)]))
    _run_main(mod, monkeypatch,
              ["--budget", "500000", "--seeds", "1", "--restart", "--dry-run"])
    assert mod.recorded_pairs("aaa1111", 500000) == {("harbor-house", 0)}


def test_resume_and_restart_are_mutually_exclusive(tmp_path, monkeypatch):
    mod = _runner()
    monkeypatch.setattr(mod, "objective_commit", lambda: "aaa1111")
    with pytest.raises(SystemExit):
        _run_main(mod, monkeypatch, ["--resume", "--restart", "--dry-run"])


def test_a_fully_recorded_objective_does_nothing(tmp_path, monkeypatch, capsys):
    mod = _runner()
    monkeypatch.setattr(mod, "objective_commit", lambda: "aaa1111")
    monkeypatch.setattr(mod, "RESULTS", _table(tmp_path, [
        _row("aaa1111", p, 0) for p in mod.PROGRAMMES]))
    _run_main(mod, monkeypatch,
              ["--budget", "500000", "--seeds", "1", "--resume", "--dry-run"])
    assert "nothing to do" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# A failure report must name the failure (DESIGN.md §39.45)
# --------------------------------------------------------------------------- #

def _diverged(tmp_path):
    """Two clones that have both moved on: pushing from `a` is rejected."""
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    a = tmp_path / "a"
    a.mkdir()
    _git(a, "init", "-q", "-b", "main", ".")
    _git(a, "config", "user.email", "t@t")
    _git(a, "config", "user.name", "t")
    (a / "f").write_text("one\n")
    _git(a, "add", "f")
    _git(a, "commit", "-qm", "one")
    _git(a, "remote", "add", "origin", str(bare))
    _git(a, "push", "-q", "origin", "main")

    b = tmp_path / "b"
    _git(tmp_path, "clone", "-q", str(bare), str(b))
    _git(b, "config", "user.email", "t@t")
    _git(b, "config", "user.name", "t")
    _git(b, "checkout", "-q", "-B", "main", "origin/main")
    (b / "g").write_text("two\n")
    _git(b, "add", "g")
    _git(b, "commit", "-qm", "two")
    assert _git(b, "push", "-q", "origin", "main").returncode == 0

    (a / "h").write_text("three\n")
    _git(a, "add", "h")
    _git(a, "commit", "-qm", "three")
    return a


def test_a_rejected_push_is_reported_as_a_rejection(tmp_path):
    """`git push` opens its stderr with the remote URL, so the first line of a
    rejected push is "To github.com:owner/repo.git" -- the remote it was
    talking to, not what went wrong. That is what the runner printed for a
    whole class of failures, under a banner reading GIT FAILED.

    Not hypothetical: it is what the owner saw when a push of mine landed
    first and the runner's push was rejected. The retry loop recovered, so the
    only casualty was the diagnosis -- which is the entire job of this line.
    """
    mod = _runner()
    a = _diverged(tmp_path)
    r = _git(a, "push", "origin", "main")
    assert r.returncode != 0, "the fixture did not produce a rejection"

    first = (r.stderr or r.stdout or "").strip().splitlines()[0]
    assert first.startswith("To "), "git changed its output shape"

    line = mod.git_error_line(r)
    assert "rejected" in line, f"reported {line!r} instead of the rejection"
    assert not line.startswith("To ")


def test_a_real_dirty_tree_rebase_is_reported_by_its_reason(tmp_path):
    """The other failure the runner actually hits (homemaker-py-cna)."""
    mod = _runner()
    _git(tmp_path, "init", "-q", ".")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "tracked.txt").write_text("base\n")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-qm", "base")
    (tmp_path / "tracked.txt").write_text("edited, uncommitted\n")
    r = _git(tmp_path, "pull", "--rebase", "-q", ".", "HEAD")
    assert r.returncode != 0
    assert "unstaged" in mod.git_error_line(r).lower()


def test_the_banner_is_only_skipped_when_something_else_is_there():
    """Skipping git's chatter must never turn a failure into silence."""
    mod = _runner()

    class R:
        returncode = 128
        stdout = ""
        stderr = "To github.com:owner/repo.git\nremote: some server noise\n"
    assert mod.git_error_line(R()).startswith("To github.com")

    class Empty:
        returncode = 128
        stdout = stderr = ""
    assert mod.git_error_line(Empty()) == "exit 128"


def test_fatal_outranks_everything():
    mod = _runner()

    class R:
        returncode = 128
        stdout = ""
        stderr = ("To github.com:owner/repo.git\n"
                  " ! [rejected]  main -> main (fetch first)\n"
                  "fatal: could not read Username for 'https://github.com'\n")
    assert mod.git_error_line(R()).startswith("fatal:")


# --------------------------------------------------------------------------- #
# The stamp must describe the code that is actually running
# (homemaker-py-jui, DESIGN.md §39.51)
# --------------------------------------------------------------------------- #

def _repo_with_objective_sources(tmp_path):
    """A git repo carrying the two files the objective stamp is computed from."""
    mod = _runner()
    _git(tmp_path, "init", "-q", ".")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    for rel in mod.OBJECTIVE_SOURCES:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("# committed\n")
    (tmp_path / "src" / "homemaker_layout" / "driver.py").write_text("# committed\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def test_a_clean_tree_reports_nothing_dirty(tmp_path):
    mod = _runner()
    repo = _repo_with_objective_sources(tmp_path)
    assert mod.uncommitted_objective_sources(repo) == []
    assert mod.other_dirty_sources(repo) == []


@pytest.mark.parametrize("which", [0, 1])
def test_an_edited_objective_source_is_detected(tmp_path, which):
    """Either file. geometry.py counts as much as fitness.py -- §39.42 settled
    that, and this is the same rule reaching the working tree."""
    mod = _runner()
    repo = _repo_with_objective_sources(tmp_path)
    rel = mod.OBJECTIVE_SOURCES[which]
    (repo / rel).write_text("# edited, not committed\n")
    assert mod.uncommitted_objective_sources(repo) == [rel]


def test_a_staged_but_uncommitted_edit_still_counts(tmp_path):
    """`git log` cannot see the index either. Staging is not committing."""
    mod = _runner()
    repo = _repo_with_objective_sources(tmp_path)
    rel = mod.OBJECTIVE_SOURCES[0]
    (repo / rel).write_text("# staged\n")
    _git(repo, "add", "--", rel)
    assert mod.uncommitted_objective_sources(repo) == [rel]


def test_a_dirty_non_objective_source_is_separated_out(tmp_path):
    """An edited driver.py changes how the search moves, not what it is scored
    against -- a warning, not a refusal, and it must not be confused with one."""
    mod = _runner()
    repo = _repo_with_objective_sources(tmp_path)
    (repo / "src/homemaker_layout/driver.py").write_text("# edited\n")
    assert mod.uncommitted_objective_sources(repo) == []
    assert mod.other_dirty_sources(repo) == ["src/homemaker_layout/driver.py"]


def test_the_stamp_and_the_dirty_check_read_the_same_files():
    """Two lists of "what the objective is" would drift, which is exactly how
    §39.42 happened. There is one constant."""
    mod = _runner()
    src = RUNNER.read_text()
    i = src.index("def objective_commit")
    body = src[i:i + 2000]
    assert "OBJECTIVE_SOURCES" in body, "the stamp hardcodes its own file list"
    i = src.index("def uncommitted_objective_sources")
    assert "OBJECTIVE_SOURCES" in src[i:i + 1500]


def test_a_sweep_refuses_to_start_over_uncommitted_objective_edits(monkeypatch,
                                                                   capsys):
    """The whole point: a week of runs stamped with the commit BEFORE the edits
    that scored them, and artefacts named from it that can overwrite that
    objective's."""
    mod = _runner()
    monkeypatch.setattr(mod, "uncommitted_objective_sources",
                        lambda *a, **k: ["src/homemaker_layout/fitness.py"])
    import sys as _sys
    monkeypatch.setattr(_sys, "argv",
                        ["run_coldstart_baseline.py", "--seeds", "1", "--dry-run"])
    with pytest.raises(SystemExit) as e:
        mod.main()
    assert e.value.code == 2
    out = capsys.readouterr().out
    assert "src/homemaker_layout/fitness.py" in out
    assert "no override" in out
    assert "would run" not in out, "it listed the queue despite refusing"


def test_a_dirty_non_objective_source_warns_but_runs(monkeypatch, capsys):
    mod = _runner()
    monkeypatch.setattr(mod, "uncommitted_objective_sources", lambda *a, **k: [])
    monkeypatch.setattr(mod, "other_dirty_sources",
                        lambda *a, **k: ["src/homemaker_layout/driver.py"])
    monkeypatch.setattr(mod, "objective_commit", lambda: "deadbee")
    monkeypatch.setattr(mod, "recorded_pairs", lambda *a, **k: set())
    import sys as _sys
    monkeypatch.setattr(_sys, "argv",
                        ["run_coldstart_baseline.py", "--seeds", "1", "--dry-run"])
    mod.main()
    out = capsys.readouterr().out
    assert "WARNING" in out and "driver.py" in out
    assert "would run" in out, "a non-objective edit must not stop the sweep"


def test_the_refusal_happens_before_the_stamp_is_taken():
    """A stamp computed over uncommitted edits is a label for an objective that
    exists nowhere. Order is the whole fix, and there is no value to assert."""
    src = RUNNER.read_text()
    body = src[src.index("def main("):]
    assert (body.index("uncommitted_objective_sources")
            < body.index("objective = objective_commit()")), (
        "the stamp is taken before the tree is checked")


def test_the_verifier_explains_mismatches_when_the_tree_is_dirty():
    """A wall of mismatches has one likely cause and one unlikely one. Saying
    which is the difference between "the table drifted" and "you have edits"."""
    if not VERIFIER.is_file():
        pytest.skip("verifier absent")
    src = VERIFIER.read_text()
    body = src[src.index("def main("):]
    assert "uncommitted_objective_sources" in body, (
        "the verifier never mentions a dirty objective source")
    # gated on there being something to explain, or it is just noise
    i = body.index("uncommitted_objective_sources")
    assert "bad or missing" in body[i:i + 300]

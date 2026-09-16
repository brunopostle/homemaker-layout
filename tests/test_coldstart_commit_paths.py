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

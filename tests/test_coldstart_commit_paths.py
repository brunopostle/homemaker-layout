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

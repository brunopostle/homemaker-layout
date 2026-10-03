"""The coldstart runner must push the branch it committed to, and must not call
a push "pushed" until the remote actually holds the commit.

On 2026-10-01 the runner pushed a hardcoded, stale agent branch while its
commits landed on `main`. `git push origin <up-to-date-branch>` exits 0, so the
first two rows of the 07b2058+orth sweep printed "pushed:" and reached nobody.
The negative control below reproduces that push and shows the exit status lies.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parent.parent / "experiments" / "run_coldstart_baseline.py"
pytestmark = pytest.mark.skipif(not RUNNER.is_file(), reason="runner absent")


def _runner():
    spec = importlib.util.spec_from_file_location("coldstart_runner_push", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *argv):
    r = subprocess.run(["git", *argv], cwd=repo, capture_output=True, text=True)
    return r


@pytest.fixture
def clone(tmp_path):
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        _git(work, "config", k, v)
    _git(work, "checkout", "-q", "-b", "main")
    (work / "a").write_text("1")
    _git(work, "add", "a")
    _git(work, "commit", "-q", "-m", "one")
    _git(work, "push", "-q", "origin", "main")
    _git(work, "branch", "stale")          # an agent branch nobody moves
    (work / "a").write_text("2")
    _git(work, "commit", "-q", "-am", "two")  # a result row, on main
    return work


def test_current_branch_is_the_checked_out_one(clone):
    assert _runner().current_branch(clone) == "main"


def test_stale_branch_push_exits_zero_but_publishes_nothing(clone):
    # Negative control: this is the push the runner used to make.
    m = _runner()
    assert _git(clone, "push", "-q", "origin", "stale").returncode == 0
    assert not m.remote_has_head("main", clone)


def test_pushing_head_to_the_current_branch_publishes(clone):
    m = _runner()
    assert not m.remote_has_head("main", clone)
    assert _git(clone, "push", "-q", "origin", "HEAD:refs/heads/main").returncode == 0
    assert m.remote_has_head("main", clone)


def test_no_branch_is_hardcoded():
    assert "beads-project-intro" not in RUNNER.read_text().split("used to name one here")[0]


def test_git_busy_is_quiet_on_a_clean_branch(clone):
    assert _runner().git_busy(clone) == ""


def test_git_busy_catches_a_detached_head(clone):
    _git(clone, "checkout", "-q", "--detach")
    assert "detached" in _runner().git_busy(clone)


def test_git_busy_catches_a_conflicted_rebase(clone):
    # The 2026-10-02 state: a pull --rebase that stopped on a conflict.
    _git(clone, "checkout", "-q", "-b", "other", "main~1")
    (clone / "a").write_text("conflict")
    _git(clone, "commit", "-q", "-am", "other")
    _git(clone, "checkout", "-q", "main")
    assert _git(clone, "rebase", "other").returncode != 0
    assert "rebase" in _runner().git_busy(clone)
    _git(clone, "rebase", "--abort")
    assert _runner().git_busy(clone) == ""

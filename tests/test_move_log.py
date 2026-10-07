"""`HOMEMAKER_MOVE_LOG` records every child of a search and changes nothing
(`homemaker-py-urzf`, DESIGN.md §39.120).

A book of moves needs to know what was tried, on what, and what came of it.
The recorder is a file named by an environment variable; the first thing held
here is that a search with it set is the same search.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from homemaker_layout import evolve

REPO = Path(__file__).resolve().parent.parent
PH = REPO / "examples" / "programme-house"

pytestmark = pytest.mark.skipif(not PH.is_dir(), reason="examples absent")


def _run(tmp_path: Path, name: str, monkeypatch, log: "Path | None") -> Path:
    work = tmp_path / name
    work.mkdir()
    for f in ("init.dom", "patterns.config", "costs.config"):
        if (PH / f).exists():
            shutil.copy(PH / f, work / f)
    if log is None:
        monkeypatch.delenv("HOMEMAKER_MOVE_LOG", raising=False)
    else:
        monkeypatch.setenv("HOMEMAKER_MOVE_LOG", str(log))
    monkeypatch.setenv("HOMEMAKER_ORTHOGONAL_DIVISION", "1")
    out = work / "out.dom"
    assert evolve.main([str(work / "init.dom"), "--budget", "1500", "--seed", "5",
                        "--workers", "1", "--output", str(out)]) == 0
    return out


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("movelog")
    mp = pytest.MonkeyPatch()
    try:
        from homemaker_layout import geometry
        was = geometry.ORTHOGONAL_DIVISION
        geometry.ORTHOGONAL_DIVISION = True
        log = tmp / "moves.jsonl"
        plain = _run(tmp, "plain", mp, None)
        logged = _run(tmp, "logged", mp, log)
        geometry.ORTHOGONAL_DIVISION = was
        geometry.clear_cache()
    finally:
        mp.undo()
    return plain, logged, [json.loads(ln) for ln in log.read_text().splitlines()]


def test_a_recorded_search_is_the_same_search(runs):
    plain, logged, _ = runs
    assert plain.read_text() == logged.read_text()


def test_every_child_is_recorded_with_what_it_was_played_on(runs):
    _, _, records = runs
    bred = [r for r in records if r["parent_fails"] is not None]
    assert len(bred) >= 5
    for r in records:
        assert r["status"] in ("best", "kept", "duplicate", "rejected", "pruned")
        assert isinstance(r["fails"], list) and r["used"] >= 1
    for r in bred:
        assert isinstance(r["parent_fails"], list) and r["parent_fitness"] is not None
        assert r["move"].split()[0] in {
            "crossover", *__import__("homemaker_layout.operators",
                                     fromlist=["MUTATIONS"]).MUTATIONS}
    # seeds and constructed individuals have no parent, and say so
    assert any(r["parent_fails"] is None for r in records)
    # the evaluations recorded are the evaluations spent, search by search
    # (a run is several searches end to end, each counting from zero)
    phases = sorted({r["phase"] for r in records})
    assert len(phases) >= 1
    for ph in phases:
        mine = [r for r in records if r["phase"] == ph]
        assert mine[-1]["evals"] == sum(r["used"] for r in mine)


def test_the_log_agrees_with_the_run_about_its_best(runs):
    """The check that the statuses mean something: the last record marked
    `best` carries the fail lines of the design the run wrote."""
    plain, _, records = runs
    best = [r for r in records if r["status"] == "best"][-1]
    from homemaker_layout import dom, geometry
    from homemaker_layout.fitness import Fitness, load_config

    was = geometry.ORTHOGONAL_DIVISION
    geometry.ORTHOGONAL_DIVISION = True
    try:
        _, fails = Fitness(*load_config(PH)).score_with_fails(dom.load(str(plain)))
    finally:
        geometry.ORTHOGONAL_DIVISION = was
        geometry.clear_cache()
    # the run finishes with a collapse and a polish the log does not cover, so
    # the written design may be better than the last recorded best, never worse
    assert len(fails) <= len(best["fails"])


def test_nothing_is_written_unless_asked(tmp_path, monkeypatch):
    from homemaker_layout import driver

    monkeypatch.delenv("HOMEMAKER_MOVE_LOG", raising=False)
    assert driver._move_logger() is None
    monkeypatch.setenv("HOMEMAKER_MOVE_LOG", str(tmp_path / "x.jsonl"))
    log = driver._move_logger()
    log(move="divide l", status="kept")
    got = json.loads((tmp_path / "x.jsonl").read_text())
    assert (got["move"], got["status"]) == ("divide l", "kept") and "phase" in got

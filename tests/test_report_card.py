"""The report card's negative control (`homemaker-py-5fje.1`, DESIGN.md §39.205).

`experiments/report_card.py` is the arm-neutral yardstick for the aggregation
review: plain facts about a plan, none of them a score. Its `--self-test`
applies known edits to real designs (a room shrunk, a room left out, a storey
cut off, a stair stopped short) and requires the column each is about to move
the way it must, and the columns it is not about to hold. This runs it.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from homemaker_layout import geometry

REPO = Path(__file__).resolve().parent.parent
Q = REPO / "experiments" / "results" / "questionnaire"
pytestmark = pytest.mark.skipif(not (Q / "O1-0-a.dom").is_file(), reason="no questionnaire designs")


@pytest.fixture(scope="module")
def rc():
    sys.path.insert(0, str(REPO / "experiments"))
    spec = importlib.util.spec_from_file_location(
        "report_card", REPO / "experiments" / "report_card.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def test_negative_control(rc, capsys):
    ok = rc.self_test(rc.Programmes())
    out = capsys.readouterr().out
    assert ok, out
    assert "BAD" not in out


def test_card_reads_no_score(rc):
    """A design's card must not change when the score's own parameters do:
    double every value rate and the facts stay where they are."""
    progs = rc.Programmes()
    path = rc.CLEAN9
    before, rooms = rc.card_of(progs, path, "maple-court")
    _, fit, _ = progs(path, "maple-court")
    saved = fit.value_rate
    fit.value_rate = lambda leaf: 2 * saved(leaf)
    try:
        after, _ = rc.card_of(progs, path, "maple-court")
    finally:
        del fit.value_rate
    assert before == after
    assert rooms and all(r["area"] > 0 for r in rooms)

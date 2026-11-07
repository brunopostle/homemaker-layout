"""Owner's rulings on stairs, 2026-11-07 (DESIGN.md §39.211, `homemaker-py-5fje.11`):

  "every stair should be scored for fit and stairs that can't hold a flight
  should be missing stairs"

with the owner's choice of a 0.9 m minimum (a domestic flight), not the 1.25 m
``stair_width``, for a cell too narrow to hold one. Until then the scorer took
the BEST stair's fit (Perl's rule), so in maple-court, which asks for two
stairs, the second could be 1.5 m² at no cost and still count (§39.210).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from homemaker_layout import dom, geometry
from homemaker_layout.fitness import Fitness

REPO = Path(__file__).resolve().parent.parent
P1 = REPO / "experiments" / "results" / "phase1"
pytestmark = pytest.mark.skipif(not P1.is_dir(), reason="no phase1 twins")


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


@pytest.fixture(scope="module")
def maple():
    sys.path.insert(0, str(REPO / "experiments"))
    import report_card as rc
    return rc.Programmes()(str(P1 / "x.dom"), "maple-court")[1]


def _fails(fit, name):
    root = dom.load(str(P1 / name))
    dom.link(root)
    return fit.score_with_fails(root)[1]


def test_every_stair_multiplies(maple):
    one, short = maple._one_stair_volume(1.0), maple._one_stair_volume(0.33)
    assert maple.quality_staircase_volume(1.0, 0.33) == pytest.approx(one * short)
    assert maple.quality_staircase_volume() == 0.09
    # control: Perl's best-stair rule, which this replaced, ignores the second
    assert max(one, short) == one != pytest.approx(one * short)


def test_a_stair_too_short_for_its_flight_is_missing(maple):
    # the P1 twin's second stair is 1.5 m² (fit 0.33): missing, so too few
    assert any(f.startswith("too few stairs (1, min 2)")
               for f in _fails(maple, "split-stair-race--final-double-1--P1.dom"))
    # control: its A0 twin's is 5.1 m², 1.17 m wide (narrower than stair_width
    # but wider than a flight's minimum): a stair, and the count is met
    assert not any(f.startswith("too few stairs")
                   for f in _fails(maple, "split-stair-race--final-double-1--A0.dom"))


def test_a_stair_too_long_still_holds_its_flight(maple):
    # a 28.7 m x 1.17 m stair column reads short across, long along: it holds
    # a flight, so it counts, and is scored as oversized
    fails = _fails(maple, "join-clean9--final-double-1--A0.dom")
    assert not any(f.startswith("too few stairs") for f in fails)
    assert "staircase volume" in fails

"""Two stairs count as two only if they are separated.

Owner's ruling, 2026-10-14 (DESIGN.md §39.143): "a building this size needs
two stairs and they need to be separated from each other". The distance is
the US building code's rule for two exits (IBC 1007.1.1, unsprinklered): at
least half the building's overall diagonal, centroid to centroid. Two stairs
closer than that are one way out.

The designs and the brief are copies under tests/data/stair-separation, so a
later change to harbor-house's brief or to a committed design cannot quietly
stop these from firing (§39.136):

* ``hand2a.dom`` -- the owner's drawing, two cores 19.9 m apart on a
  37.9 m diagonal: separated;
* ``close-stairs.dom`` -- a hand-seeded run (`handseed-4428262+orth` s2)
  whose search pulled the second stair to 5 m from the first.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from homemaker_layout import dom, geometry
from homemaker_layout.fitness import Fitness, load_config

DATA = Path(__file__).resolve().parent / "data" / "stair-separation"


@pytest.fixture(autouse=True)
def orthogonal(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _stair_fails(name: str, separation=None) -> list[str]:
    conf, cost = load_config(DATA)
    if separation is not None:
        conf = dict(conf, staircase_separation=separation)
    fit = Fitness(conf, cost)
    _score, fails = fit.score_with_fails(dom.load(str(DATA / name)))
    return [f for f in fails if "stairs" in f]


def test_the_owners_drawing_has_two_separated_stairs():
    assert _stair_fails("hand2a.dom") == []


def test_two_stairs_five_metres_apart_are_one_way_out():
    assert _stair_fails("close-stairs.dom") == ["too few stairs (1, min 2)"]


def test_negative_control_without_the_rule_both_stairs_count():
    """The fail above comes from the separation rule and nothing else."""
    assert _stair_fails("close-stairs.dom", separation=0) == []


def test_the_rule_reads_the_diagonal():
    """19.9 m apart passes at half a 37.9 m diagonal (18.9 m) and fails once
    the fraction asks for more than 19.9 m."""
    assert _stair_fails("hand2a.dom", separation=0.5) == []
    assert _stair_fails("hand2a.dom", separation=0.55) == ["too few stairs (1, min 2)"]

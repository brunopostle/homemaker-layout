"""Owner's rulings of 2026-11-16 (DESIGN.md §39.237, `homemaker-py-5fje.23`),
on the health-centre that won §39.236 at 0 fails:

- a stair more than `fitness.STAIR_TOO_LONG` times its flight's length is a
  stair doubling as a corridor, and fails `stair too long`;
- every storey's circulation must be one piece on that storey: a visitor must
  not have to go upstairs and down again to cross the building, so a stair no
  longer joins the pieces of the storeys it serves (`graph.STAIRS_JOIN_STOREYS`).

The winner breaks both, and each test carries the control that the old rule
let it pass.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from homemaker_layout import dom, fitness, geometry, graph
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parent.parent
WINNER = REPO / "experiments/results/halving-health-swap/winner.dom"


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _fails():
    if not WINNER.is_file():
        pytest.skip("no winner")
    fit = Fitness(*load_config(REPO / "examples/health-centre"))
    root = dom.load(str(WINNER))
    dom.link(root)
    geometry.clear_cache()
    return fit.score_with_fails(root)[1]


def test_the_wing_length_stair_fails():
    assert "0/llrr stair too long" in _fails()


def test_a_stair_of_its_flights_length_does_not(monkeypatch):
    # control: the south stair is 2.01x its flight; with the line above that,
    # nothing fails, and the other stair (1.03x) never did
    monkeypatch.setattr(fitness, "STAIR_TOO_LONG", 2.5)
    assert not any("stair too long" in f for f in _fails())


def test_a_storey_joined_only_through_the_floor_above_is_not_connected():
    assert "level 0 not connected" in _fails()


def test_the_old_rule_joined_it(monkeypatch):
    # control: with stairs as links (§39.125) the ground floor passed
    monkeypatch.setattr(graph, "STAIRS_JOIN_STOREYS", True)
    assert not any("not connected" in f for f in _fails())

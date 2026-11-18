"""Owner's ruling of 2026-11-17 (DESIGN.md §39.246): one-direction escape
travel, measured from a room's door in the corridor, may not exceed the UK's
11 m -- to a stair core above the ground, and on the ground to the street or a
courtyard or garden with street access. Each circulation cell holding a room
door further than that from two directions of escape fails `dead end`.

The corridors race winner fails once upstairs (14.1 m), the rulings race
winner once on its one storey (15.4 m). Controls: with the rule off, or the
limit raised past both, neither does; the swap race winner (9.8 m upstairs)
does not."""
from __future__ import annotations

from pathlib import Path

import pytest

from homemaker_layout import dom, geometry, graph
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parent.parent
R = REPO / "experiments/results"
CORRIDORS = R / "halving-health-corridors/winner.dom"
RULINGS = R / "halving-health-rulings/winner.dom"
SWAP = R / "halving-health-swap/winner.dom"


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _fails(path, **conf):
    if not path.is_file():
        pytest.skip("no design")
    fit = Fitness(*load_config(REPO / "examples" / "health-centre"))
    for k, v in conf.items():
        fit._conf[k] = v
    root = dom.load(str(path))
    dom.link(root)
    geometry.clear_cache()
    return [f for f in fit.score_with_fails(root)[1] if f.endswith("dead end")]


def test_upper_storey_dead_end_to_the_stairs():
    assert _fails(CORRIDORS) == ["1/rll dead end"]


def test_ground_storey_dead_end_to_the_street():
    assert _fails(RULINGS) == ["0/llrr dead end"]


def test_control_rule_off():
    assert _fails(CORRIDORS, dead_end_max=False) == []
    assert _fails(RULINGS, dead_end_max=False) == []


def test_control_limit_past_both():
    assert _fails(CORRIDORS, dead_end_max=16.0) == []
    assert _fails(RULINGS, dead_end_max=16.0) == []


def test_control_short_dead_end_passes():
    assert _fails(SWAP) == []


def test_no_escape_reports_nothing():
    """A storey with no escape is charged elsewhere, not here."""
    if not CORRIDORS.is_file():
        pytest.skip("no design")
    fit = Fitness(*load_config(REPO / "examples" / "health-centre"))
    root = dom.load(str(CORRIDORS))
    dom.link(root)
    dom.merge_divided(root)
    dom.link(root)
    geometry.clear_cache()
    gb, gc, _ = graph.storey_graphs(root, 1.2, fit.usages())
    # with neither street doors nor any outdoor space, the ground has no escape
    no_yard = gb[0].copy()
    no_yard.remove_nodes_from([v for v in list(no_yard) if dom.is_outside(v)])
    assert graph.dead_ends(gc[0], no_yard, 0, lambda v: False) == {}

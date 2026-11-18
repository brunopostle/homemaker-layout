"""Owner's rulings of 2026-11-18 (DESIGN.md §39.249), on the dead-end race's
winner, whose Minor Surgery Room `ms1` was a 1.22 m x 17 m strip that other
rooms opened off, across a roof terrace:

* a room (not a corridor, not a WC) longer than 2.5 times its width, or than
  its own proportion target if higher, fails `narrow room` -- per programme,
  health-centre first;
* outdoor space is not circulation: a storey's rooms must join without
  crossing a terrace or a court (`graph.OUTDOOR_CIRCULATION`);
* a token room -- under 25% of its target area, or a sliver -- is scored as
  missing, and `operators.mutate_remove_token` gives its cell away.

Each with its control.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, geometry, graph, operators
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parent.parent
R = REPO / "experiments/results"
DEADEND = R / "halving-health-deadend/winner.dom"
CORRIDORS = R / "halving-health-corridors/winner.dom"
LONG_WC = R / "halving-health-corridors/drawings/s5-one-1.dom"   # 0/rrlr t11, aspect 5.8


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _fit(programme="health-centre", **conf):
    fit = Fitness(*load_config(REPO / "examples" / programme))
    fit._conf.update(conf)
    return fit


def _load(path):
    if not path.is_file():
        pytest.skip("no design")
    root = dom.load(str(path))
    dom.link(root)
    geometry.clear_cache()
    return root


def _fails(path, fit=None):
    return (fit or _fit()).score_with_fails(_load(path))[1]


# --- narrow room ----------------------------------------------------------

def test_strip_room_is_narrow():
    assert "1/llr narrow room" in _fails(DEADEND)


def test_control_narrow_room_is_per_programme():
    assert not [f for f in _fails(DEADEND, _fit(room_aspect_max=None))
                if f.endswith("narrow room")]


def test_control_wc_is_exempt():
    assert "0/rrlr narrow room" not in _fails(LONG_WC)


def test_programme_target_wins(monkeypatch):
    fit = _fit()
    root = _load(DEADEND)
    dom.merge_divided(root)
    dom.link(root)
    geometry.clear_cache()
    ms1 = dom.levels(root)[1].by_id("llr")
    assert fit._narrow_room(ms1)
    monkeypatch.setattr(fit._programme["ms1"], "proportion", 20.0)
    assert not fit._narrow_room(ms1)


# --- outdoor space is not circulation ------------------------------------

def test_rooms_joined_across_a_terrace_are_inaccessible():
    assert "1 inaccessible usable space" in _fails(DEADEND)


def test_control_outdoor_circulation_on(monkeypatch):
    monkeypatch.setattr(graph, "OUTDOOR_CIRCULATION", True)
    assert "1 inaccessible usable space" not in _fails(DEADEND)


# --- token rooms ------------------------------------------------------------

def test_token_room_scores_as_missing():
    assert "missing required space: wa1" in _fails(CORRIDORS)


def test_control_token_rule_off():
    assert "missing required space: wa1" not in _fails(CORRIDORS, _fit(token_fraction=False))


def test_remove_token_gives_the_cell_away():
    fit = _fit()
    child, msg = operators.mutate_remove_token(_load(CORRIDORS), np.random.default_rng(0),
                                               [], fit=fit)
    assert msg == "remove_token 0/llrlrl (wa1 to ph1)"
    dom.link(child)
    geometry.clear_cache()
    assert not any(fit.is_token(lf) for lv in dom.levels(child) for lf in lv.leaves()
                   if lf.type == "wa1")


def test_control_remove_token_without_fit_is_noop():
    _, msg = operators.mutate_remove_token(_load(CORRIDORS), np.random.default_rng(0), [])
    assert msg == "remove_token noop"

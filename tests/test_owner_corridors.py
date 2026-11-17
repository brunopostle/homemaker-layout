"""Owner's corridor rulings of 2026-11-17 (DESIGN.md §39.241,
`homemaker-py-5fje.24`-`.26`), each with its control:

- a `C` cell more than `width_circulation_max` wide fails `corridor too wide`,
  but the lobby (the front door's cell) does not;
- a `C` cell nothing needs fails `superfluous circulation`, and
  `operators.mutate_merge_circulation` gives it to the cell beside it;
- the health centre fails each double-loaded corridor once.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, geometry, graph, operators
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parent.parent
HEALTH = REPO / "experiments/results/halving-health-rulings/winner.dom"
HARBOR = REPO / "experiments/results/halving-harbor-guard/winner.dom"


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _load(path):
    if not path.is_file():
        pytest.skip("no design")
    root = dom.load(str(path))
    dom.link(root)
    geometry.clear_cache()
    return root


def _fit(prog, **conf):
    fit = Fitness(*load_config(REPO / "examples" / prog))
    fit._conf.update(conf)
    return fit


def test_a_wide_corridor_fails_and_the_lobby_does_not():
    root = _load(HARBOR)
    fails = _fit("harbor-house").score_with_fails(root)[1]
    assert "0/rlrlrrll corridor too wide" in fails
    # the lobby, 5.4 m wide, is exempt
    lvl = dom.levels(root)[0]
    assert geometry.usable_width(lvl.by_id("lrlll")) > 5
    assert "0/lrlll corridor too wide" not in fails
    # control: with the cap off nothing fails it
    geometry.clear_cache()
    off = _fit("harbor-house", width_circulation_max=False).score_with_fails(_load(HARBOR))[1]
    assert not any("too wide" in f for f in off)


def test_the_north_wing_vestibule_is_superfluous():
    fails = _fit("health-centre").score_with_fails(_load(HEALTH))[1]
    assert "0/lrrlrr superfluous circulation" in fails
    # the corridors that serve several rooms are not
    assert not any(f.startswith(("0/rl ", "0/llrr ", "0/lrrll ")) and "superfluous" in f
                   for f in fails)
    off = _fit("health-centre", superfluous_circulation=False).score_with_fails(_load(HEALTH))[1]
    assert not any("superfluous" in f for f in off)


def test_the_merge_move_gives_the_cell_to_its_room():
    fit = _fit("health-centre")
    root = _load(HEALTH)
    child, msg = operators.mutate_merge_circulation(root, np.random.default_rng(0), [], fit=fit)
    assert msg == "merge_circulation 0/lrrlr (kept mo1)"
    dom.link(child)
    geometry.clear_cache()
    assert not any("superfluous" in f for f in fit.score_with_fails(child)[1])
    # control: without a scorer it does nothing
    _, msg = operators.mutate_merge_circulation(root, np.random.default_rng(0), [])
    assert msg.endswith("noop")


def test_the_health_centre_fails_its_double_loaded_south_corridor():
    fails = _fit("health-centre").score_with_fails(_load(HEALTH))[1]
    assert fails.count("0 double-loaded corridor") == 1
    assert len(graph.double_loaded_corridors(_load(HEALTH))) == 1
    # control: a programme that does not ask for it is not charged
    fit = _fit("health-centre")
    fit._double_loaded_fails = 0
    assert "0 double-loaded corridor" not in fit.score_with_fails(_load(HEALTH))[1]

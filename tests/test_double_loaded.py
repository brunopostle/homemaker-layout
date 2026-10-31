"""A double-loaded corridor priced in fails (`homemaker-py-srl0`).

Off by default, so no score moves until an owner ruling turns it on. When on it
must act in n_fails, read walls only, and not be dodged by a wall across the
corridor.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from homemaker_layout import dom, driver, geometry, graph
from homemaker_layout.fitness import Fitness, classify_fail_tier
from homemaker_layout.fitness_cmd import load_config

REPO = Path(__file__).resolve().parent.parent
PH = REPO / "examples" / "programme-house"


@pytest.fixture(autouse=True)
def orthogonal(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def strips(top="r", cut=None, node=None):
    """Three strips up a 12 x 10 m plot: rooms, a 2 m corridor, then ``top``.
    ``cut`` puts a wall across the corridor at that fraction of its length."""
    corridor = {"type": "C"}
    if cut is not None:
        corridor = {"rotation": 1, "division": [cut, cut], "l": {"type": "C"}, "r": {"type": "C"}}
    d = {"node": node or [[0.0, 0.0], [12.0, 0.0], [12.0, 10.0], [0.0, 10.0]],
         "perimeter": {k: None for k in "abcd"}, "height": 3.0, "elevation": 0.0,
         "wall_inner": 0.08, "wall_outer": 0.25,
         "rotation": 1, "division": [0.4, 0.4],
         "l": {"type": "r"},
         "r": {"rotation": 0, "division": [1 / 3, 1 / 3],
               "l": corridor, "r": {"type": top}}}
    root = dom._parse(d)
    dom.link(root)
    return root


def test_fires_with_rooms_both_sides_and_not_with_one():
    assert len(graph.double_loaded_corridors(strips("r"))) == 1
    assert graph.double_loaded_corridors(strips("O")) == []


def test_a_wall_across_the_corridor_does_not_dodge_it():
    root = strips("r", cut=0.5)
    # each piece alone is 6 x 2 m: the rule per cell would pass it
    pieces = [x for x in root.leaves() if x.type == "C"]
    assert len(pieces) == 2
    found = graph.double_loaded_corridors(root)
    assert len(found) == 1
    assert found[0][1] == pytest.approx(12.0)


def test_answer_does_not_turn_with_the_plot():
    # the same plot, its corners listed from another one and turned 30 degrees
    import math
    c, s = math.cos(math.radians(30)), math.sin(math.radians(30))
    turned = [[c * x - s * y, s * x + c * y]
              for x, y in [[0.0, 0.0], [12.0, 0.0], [12.0, 10.0], [0.0, 10.0]]]
    found = graph.double_loaded_corridors(strips("r", cut=0.25, node=turned))
    assert len(found) == 1
    assert found[0][1] == pytest.approx(12.0)


def fit(**over):
    conf, cost = load_config(PH, over)
    return Fitness(conf, cost)


def test_off_by_default_and_counted_in_fails_when_on():
    base = fit().score_with_fails(strips("r"))
    assert not any("double-loaded" in f for f in base[1])
    two = fit(double_loaded_fails=2).score_with_fails(strips("r"))
    extra = [f for f in two[1] if "double-loaded" in f]
    assert extra == ["0 double-loaded corridor"] * 2
    assert len(two[1]) == len(base[1]) + 2
    assert two[0] == pytest.approx(base[0] * 0.25)
    assert classify_fail_tier(extra[0]) == "soft"


def test_per_metre_rounds_up():
    fails = fit(double_loaded_metres=5.0).score_with_fails(strips("r"))[1]
    assert sum("double-loaded" in f for f in fails) == 3  # 12 m


def test_corner_numbering_and_format_round_trip_change_nothing():
    spec = importlib.util.spec_from_file_location(
        "_rt", REPO / "experiments" / "diag_8b2u2_roundtrip.py")
    rt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rt)
    # the design that prompted this: the 19.6 m stem, on every storey
    f = REPO / "experiments/results/halving-maple-connect/guard/winner.dom"
    want = graph.double_loaded_corridors(dom.load(str(f)))
    assert len(want) >= 3
    geometry.clear_cache()
    got = graph.double_loaded_corridors(rt.round_trip(dom.load(str(f))))
    assert [c[0] for c in got] == [c[0] for c in want]
    assert [c[1] for c in got] == pytest.approx([c[1] for c in want])


def test_guard_counts_metres():
    assert driver.adds_double_loaded(strips("r"), strips("O"))
    assert not driver.adds_double_loaded(strips("O"), strips("r"))
    assert not driver.adds_double_loaded(strips("r"), strips("r"))

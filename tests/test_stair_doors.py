"""Where a stair core's doors go, and how many corners they cost it.

Owner's rulings, 2026-10-06 (DESIGN.md §39.95, §39.100):

* "we want to fit stairs to cores whichever way is best, so the flight can
  start at any corner and may run clockwise or counter clockwise";
* "a stair core with doors on three or four sides is going to need a single
  straight flight, unless the doors can be moved, for example doors are
  typically in the corner of a room, but can be moved to any other position
  along a shared wall if it frees up space to place stair flights".

So a wall costs the stair a corner only if no placing of its door avoids it,
and when every corner is taken the count is four -- not Urb's three.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from homemaker_layout import dom, dom_v2, geometry, graph
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parent.parent
PH = REPO / "examples" / "programme-house"


@pytest.fixture(autouse=True)
def orthogonal(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _ring(ring_cuts: dict) -> dom.Node:
    """A 9 x 9 m plot with a 3 x 3 m `C` cell in the middle. `ring_cuts` may
    divide the west and east strips, so their walls onto the core reach only
    one corner each."""
    def strip(name):
        at = ring_cuts.get(name)
        if at is None:
            return {"cell": name}
        return {"cut": "u", "at": at, "low": {"cell": name + "1"}, "high": {"cell": name + "2"}}

    doc = {"format": "homemaker-dom", "version": 2, "frame": {"u": [1.0, 0.0]},
           "plot": [[0, 0], [9, 0], [9, 9], [0, 9]], "wall_outer": 0.0,
           "storeys": [{"elevation": 0.0, "height": 3.0, "tree": {
               "cut": "v", "at": 1 / 3, "low": strip("w"),
               "high": {"cut": "v", "at": 0.5,
                        "low": {"cut": "u", "at": 1 / 3, "low": {"cell": "s"},
                                "high": {"cut": "u", "at": 0.5,
                                         "low": {"cell": "C"}, "high": {"cell": "n"}}},
                        "high": strip("e")}}}]}
    return dom_v2.from_document(doc)


def _runs(root, skip=()):
    G = geometry.leaf_graph(root)
    core = next(lf for lf in root.leaves() if lf.type == "C")
    nbs = [n for n in G.neighbors(core) if n.type not in skip]
    return sorted(sorted(r) for r in graph._corner_runs(core, G, nbs))


def test_doors_on_all_four_sides_can_share_three_corners_when_walls_reach_them():
    """Four neighbours, each along a whole side. Put each door in a corner and
    three corners serve all four walls -- any three."""
    runs = _runs(_ring({}))
    assert len(runs) == 4 and all(len(r) == 3 for r in runs)


def test_two_opposite_sides_need_two_corners_and_either_pair_will_do():
    runs = _runs(_ring({}), skip=("w", "e"))
    assert all(len(r) == 2 for r in runs) and len(runs) == 2


def test_walls_that_reach_one_corner_each_take_all_four():
    """West and east strips cut at mid-height of the core: each side now has
    two walls, each reaching one corner only. However the doors are placed
    every corner is needed, and the stair is a straight flight."""
    runs = _runs(_ring({"w": 0.5, "e": 0.5}), skip=("s", "n"))
    assert runs == [[0, 1, 2, 3]]


def _corner_counts(path: Path) -> list:
    conf, cost = load_config(PH)
    seen = []
    orig = Fitness._stair_fit

    def spy(self, leaf, corners):
        seen.append(len(corners))
        return orig(self, leaf, corners)

    Fitness._stair_fit = spy
    try:
        Fitness(conf, cost).score_with_fails(dom.load(str(path)))
    finally:
        Fitness._stair_fit = orig
    return seen


E4R = REPO / "experiments" / "results"
needs_e4r = pytest.mark.skipif(not (E4R / "e4r-tiers").is_dir(), reason="artefacts absent")


@needs_e4r
def test_the_entrance_door_may_stand_anywhere_along_its_wall():
    """e4r-tiers arm B s24: the doors upstairs need corners 2, 3 and 0, and the
    entrance is on the edge from 0 to 1. Pinned to both ends of that edge it
    took the fourth corner; standing at corner 0 it takes none."""
    assert _corner_counts(E4R / "e4r-tiers" / "e4r-armB-s24.dom") == [3]


@needs_e4r
def test_a_core_boxed_in_by_five_rooms_is_a_straight_flight():
    """e4r arm B s21, ground floor: two rooms on one long side, two on the
    other, one across the end -- four of the walls reach a different corner
    each. Urb's undef read made this three."""
    assert _corner_counts(E4R / "e4r" / "e4r-armB-s21.dom") == [4]

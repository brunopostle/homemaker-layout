"""A single-storey building needs no stair.

Owner's ruling, 2026-10-26 (DESIGN.md §39.177). Every committed health-centre
design is one storey, and each paid `too few stairs (0, min 1)` (§39.176)
because the stair count was checked whatever the storey count.

The designs and briefs are copies under tests/data/single-storey-stairs, so a
later change to a brief or a committed design cannot quietly stop these from
firing (§39.136):

* ``health-centre/one-storey.dom`` -- the pivot A/B's no-pivot seed 6, one
  storey, no `E` cell: must NOT fail on stairs;
* ``harbor-house/two-storeys-no-stair.dom`` -- a `07b2058+orth` cold run, two
  storeys and no stair: the control, which must still fail.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from homemaker_layout import dom, geometry
from homemaker_layout.fitness import Fitness, load_config

DATA = Path(__file__).resolve().parent / "data" / "single-storey-stairs"


@pytest.fixture(autouse=True)
def orthogonal(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _score(programme: str, name: str):
    root = dom.load(str(DATA / programme / name))
    _, fails = Fitness(*load_config(DATA / programme)).score_with_fails(root)
    return root, fails


def test_a_one_storey_building_is_not_charged_for_a_stair():
    root, fails = _score("health-centre", "one-storey.dom")
    assert len(dom.levels(root)) == 1
    assert not any(t.type == "E" for t in root.leaves()), "the fixture grew a stair"
    assert not [f for f in fails if f.startswith("too few stairs")], fails


def test_a_two_storey_building_without_a_stair_still_is():
    root, fails = _score("harbor-house", "two-storeys-no-stair.dom")
    assert len(dom.levels(root)) == 2
    assert [f for f in fails if f.startswith("too few stairs")] == ["too few stairs (0, min 2)"]


def test_a_stair_cell_in_a_one_storey_building_is_circulation():
    """Owner's ruling, §39.222: "a stair cell that belongs to no shaft is
    functionally a circulation cell and should be considered as such". In one
    storey nothing is climbed, so relabelling corridor cells `E` must move
    neither the score nor the fails. A pin, not a fix: the scorer already
    looked for stairs only in a ground cell with something built over it, so
    this held before the ruling too, and has no negative control that fires."""
    conf, cost = load_config(DATA / "health-centre")
    root = dom.load(str(DATA / "health-centre" / "one-storey.dom"))
    corridors = [t for t in root.leaves() if t.type == "C"]
    assert len(corridors) >= 2, "the fixture needs two corridor cells"
    geometry.clear_cache()
    plain = Fitness(conf, cost).score_with_fails(root)
    for t in corridors:
        t.type = "E"
    geometry.clear_cache()
    relabelled = Fitness(conf, cost).score_with_fails(root)
    assert relabelled == plain

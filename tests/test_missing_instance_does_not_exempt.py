"""Omitting one instance of a room code must not exempt the others from checks.

`check_adjacency`, `check_level_constraints` and `check_vertical_connectivity`
each emitted a placeholder for a missing instance and then `continue`d, so the
PRESENT instances of that code went unchecked. maple-court s1 at `07b2058+orth`
is missing one of twelve `r` and hid six `not adjacent to c` fails that way
(DESIGN.md §39.84). The owner's ruling (§39.83/§39.84): an omitted room should
be closer to a working building than one whose rooms lack circulation, so a
building must never score better for omitting a room.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from homemaker_layout import dom, geometry
from homemaker_layout.fitness import Fitness, load_config

PROG = Path(__file__).resolve().parent.parent / "examples" / "maple-court"
DOM = PROG / "coldstart-07b2058+orth-500000-s1.dom"
pytestmark = pytest.mark.skipif(not DOM.is_file(), reason="artefact absent")


@pytest.fixture
def scored(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    conf, cost = load_config(str(PROG))

    def score(root):
        geometry.clear_cache()
        s, f = Fitness(conf, cost).score_with_fails(copy.deepcopy(root))
        geometry.clear_cache()
        return s, f
    root = dom.load(str(DOM))
    dom.link(root)
    return root, score


def _cells(root, level):
    return [l for lv in dom.levels(root) for l in lv.leaves() if dom.level_of(l) == level]


def test_present_instances_keep_their_adjacency_check(scored):
    root, score = scored
    _, fails = score(root)
    assert "missing required space: r#1" in fails      # the precondition
    assert "missing r: would need adjacency to c" in fails
    hidden = [f for f in fails if f.endswith("(r) not adjacent to c")]
    assert len(hidden) == 6, hidden


def test_present_instance_on_the_wrong_level_is_still_reported(scored):
    root, score = scored
    # keep r#1 missing (eleven r, one of them moved to level 0)
    _cells(root, 2)[[l.type for l in _cells(root, 2)].index("r")].type = "C"
    _cells(root, 0)[0].type = "r"
    dom.link(root)
    _, fails = score(root)
    assert any(f.startswith("missing required space: r#") for f in fails)
    assert "missing r: would need to be on level 2" in fails
    assert "r on wrong level (level 0, expected 2)" in fails


def test_omitting_a_room_never_beats_including_it_here(scored):
    # The ruling, on the case that prompted it: half the circulation cell
    # 2/rllrlr given to the missing r must score better than the omission.
    root, score = scored
    s_omit, f_omit = score(root)
    leaf = next(l for l in _cells(root, 2) if l.id.endswith("rllrlr"))
    leaf.division, leaf.left, leaf.right, leaf.type = (
        [0.5, 0.5], dom.Node(type="C"), dom.Node(type="r"), None)
    dom.link(root)
    s_incl, fails = score(root)
    # (the room this is about: the brief has gained rooms since this design
    # was evolved -- maple-court's level-1 bathrooms, §39.132 -- and those are
    # missing on both sides of the comparison)
    assert not any(f.startswith("missing required space: r") for f in fails)
    # Under the suppression the two tied at 62 fails (score x1.01): the
    # comparison must be decisive, not a rounding margin.
    assert len(fails) < len(f_omit)
    assert s_incl > 2 * s_omit

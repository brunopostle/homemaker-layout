"""Owner's ruling, 2026-11-07 (DESIGN.md §39.215, `homemaker-py-5fje.7`): one
``level N not connected`` fail per piece of a storey's circulation beyond the
first, stairs joining storeys as before (§39.125) -- "because currently once
the storey is disconnected there may be no simple moves that resolve it, so
this would give an incremental way to resolve the problem".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from homemaker_layout import dom, geometry
from homemaker_layout import graph as graph_mod

REPO = Path(__file__).resolve().parent.parent
CLEAN9 = REPO / "experiments/results/halving-maple-clean/final-clean-9.dom"
pytestmark = pytest.mark.skipif(not CLEAN9.is_file(), reason="no clean-9")


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


@pytest.fixture(scope="module")
def rc():
    sys.path.insert(0, str(REPO / "experiments"))
    import report_card
    return report_card


def _not_connected(rc, edit=None):
    _, fit, _ = rc.Programmes()(str(CLEAN9), "maple-court")
    root = dom.load(str(CLEAN9))
    dom.link(root)
    if edit:
        edit(root)
    return [f for f in fit.score_with_fails(root)[1] if f.endswith(" not connected")]


def test_each_extra_piece_is_a_fail(rc):
    # clean-9 has its circulation in four pieces on each of its three storeys
    assert sorted(_not_connected(rc)) == [f"level {i} not connected"
                                          for i in range(3) for _ in range(3)]


def test_cutting_a_corridor_costs_exactly_one_more(rc, monkeypatch):
    before, after = _not_connected(rc), _not_connected(rc, rc.corridor_cut)
    assert len(after) == len(before) + 1
    # control: the rule this replaced, one fail per disconnected storey, cannot
    # tell the cut from the design as found -- the storey was already split
    monkeypatch.setattr(graph_mod, "circulation_pieces",
                        lambda gc, lv: 1 if graph_mod.circulation_joined(gc, lv) else 2)
    assert len(_not_connected(rc, rc.corridor_cut)) == len(_not_connected(rc)) == 3


def test_an_empty_storey_is_one_fail():
    import networkx as nx
    assert graph_mod.circulation_pieces([nx.Graph()], 0) == 0

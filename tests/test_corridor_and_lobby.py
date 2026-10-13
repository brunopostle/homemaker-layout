"""A corridor fails under a metre clear and is right at 1.6 m; the lobby is the
circulation cell with the front door and is held to more (owner's ruling,
DESIGN.md §39.139).

    "Under most regulations, any corridor under 1m wide (clear not centres)
    would be a fail, but the width increases by capacity, so an institution
    like this would be ok at 1.6m centres. A lobby is simply the circulation
    cell that meets the street with a front door."        -- owner, 2026-10-12
"""

from pathlib import Path

import pytest

from homemaker_layout import dom, geometry, graph
from homemaker_layout.dom import Node
from homemaker_layout.fitness import FAIL_THRESHOLD, Fitness, load_config

DATA = Path(__file__).parent / "data" / "service-access"
WALL = 0.16     # an internal wall: cells are measured to its centre


@pytest.fixture
def fit():
    return Fitness(*load_config(DATA))


def _width(fit, monkeypatch, metres, lobby=False):
    monkeypatch.setattr(geometry, "usable_width", lambda leaf: metres)
    return fit.quality_width(Node(type="C"), lobby=lobby)


def test_a_corridor_under_a_metre_clear_fails(fit, monkeypatch):
    assert _width(fit, monkeypatch, 0.99 + WALL) < FAIL_THRESHOLD
    assert _width(fit, monkeypatch, 1.02 + WALL) >= FAIL_THRESHOLD


def test_a_corridor_at_1_25_passes_short_of_ideal_and_1_6_is_ideal(fit, monkeypatch):
    assert FAIL_THRESHOLD < _width(fit, monkeypatch, 1.25) < 0.5
    assert _width(fit, monkeypatch, 1.6) == 1.0
    assert _width(fit, monkeypatch, 3.0) == 1.0     # wider is never worse


def test_a_lobby_is_held_to_more_than_a_corridor(fit, monkeypatch):
    assert _width(fit, monkeypatch, 1.6, lobby=True) < FAIL_THRESHOLD
    assert _width(fit, monkeypatch, 2.4, lobby=True) == 1.0


@pytest.fixture
def ground(fit, monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    root = dom.load(str(DATA / "hand2a.dom"))
    dom.link(root)
    yield root, geometry.leaf_graph(root, graph.DOOR_WIDTH)
    geometry.clear_cache()


def test_the_lobby_is_the_circulation_cell_on_the_street(fit, ground):
    root, G = ground
    lobby = fit._lobby(G)
    on_street = [n for n in root.leaves()
                 if n.type == "C" and fit._public_access(n, root) is not None]
    assert on_street == [lobby]         # the drawing has one front door
    assert fit._lobby(G) is lobby       # and it is the same cell when asked again


def test_of_several_on_the_street_the_widest_is_the_lobby(fit, ground, monkeypatch):
    """A corridor that also touches the street is still a corridor."""
    root, G = ground
    monkeypatch.setattr(fit, "_public_access",
                        lambda leaf, r: "d" if leaf.type == "C" else None)
    corridors = [n for n in root.leaves() if n.type == "C"]
    assert len(corridors) > 2
    lobby = fit._lobby(G)
    assert geometry.usable_width(lobby) == max(geometry.usable_width(n) for n in corridors)


def test_a_stair_on_the_street_is_not_a_lobby(fit, ground, monkeypatch):
    root, G = ground
    monkeypatch.setattr(fit, "_public_access",
                        lambda leaf, r: "d" if leaf.type == "E" else None)
    monkeypatch.setattr(fit, "_public_access_outside", lambda leaf, G, r: False)
    assert fit._lobby(G) is None


def test_only_the_lobby_is_scored_as_one(fit, ground, monkeypatch):
    """Every other corridor on the street is a corridor. The control: with
    `width_lobby` set beyond any cell, exactly one cell's width fails."""
    root, G = ground
    monkeypatch.setitem(fit._conf, "width_lobby", [50.0, 0.2])
    failed = []
    groups = geometry.boundary_groups(root)
    for leaf in root.leaves():
        if leaf.type == "C":
            fit.evaluate_leaf(leaf, G, 0, groups,
                              lambda f, leaf=leaf: failed.append(leaf) if f.endswith(" width") else None)
    lobby = fit._lobby(G)
    narrow = [n for n in root.leaves() if n.type == "C" and n is not lobby
              and geometry.usable_width(n) < 1.6 - 0.2 * 2.146]
    assert lobby in failed
    assert set(failed) == {lobby, *narrow}

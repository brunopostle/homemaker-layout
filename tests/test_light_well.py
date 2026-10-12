"""`mutate_light_well`: outdoor space, open to the sky, cut beside a cell that
no daylight reaches (`homemaker-py-evxm`; the owner's alley, DESIGN.md §39.125).

Synthetic fixtures: a plot with party walls on three sides and the street on
one, so that a cell at the back is buried by construction.
"""

from __future__ import annotations

import numpy as np
import pytest

from homemaker_layout import dom, geometry, operators, programme

PLOT = [[0.0, 0.0], [12.0, 0.0], [12.0, 20.0], [0.0, 20.0]]


class _Req:
    def __init__(self, usage: str, window: bool = True):
        self.usage = usage
        self.has_crinkliness, self.crinkliness = (not window), None


REQS = {"l1": _Req("living"), "b1": _Req("bedroom"), "b2": _Req("bedroom"),
        "k1": _Req("kitchen"), "st1": _Req("utility", window=False)}


def _storey(front: str, back: str, corridor: str = "C") -> dom.Node:
    """Three bands from the street back: `front` on the street (side a), a
    corridor across the plot behind it, and `back` behind that, against the
    party walls."""
    n = dom.Node(rotation=1, height=3.0, division=[0.4, 0.4])
    n.left = dom.Node(type=front)
    n.right = dom.Node(rotation=0, division=[0.25, 0.25])
    n.right.left, n.right.right = dom.Node(type=corridor), dom.Node(type=back)
    return n


def _building(back0="l1", back1="b1", front0="k1", front1="b2"):
    root = _storey(front0, back0)
    root.node = [list(p) for p in PLOT]
    root.perimeter = {"a": None, "b": "private", "c": "private", "d": "private"}
    root.elevation, root.wall_inner, root.wall_outer = 0.0, 0.08, 0.25
    root.above = _storey(front1, back1)
    dom.link(root)
    geometry.clear_cache()
    return root


def _lit(root) -> dict:
    out = {}
    for li, lvl in enumerate(dom.levels(root)):
        G = geometry.leaf_graph(lvl)
        for leaf in lvl.leaves():
            out[li, leaf.type, leaf.id] = operators._lit_wall(leaf, G)
    return out


def _buried(root):
    return sorted(k for k, v in _lit(root).items()
                  if v < 0.5 and k[1] not in ("O", "C", "E"))


def test_the_fixture_buries_what_it_means_to():
    root = _building()
    lit = {k[:2]: v for k, v in _lit(root).items()}
    street = {k for k, v in lit.items() if v > 1}
    assert street == {(0, "k1"), (1, "b2")}, lit
    assert [k[:2] for k in _buried(root)] == [(0, "l1"), (1, "b1")], lit


def test_a_well_is_open_to_the_sky_and_lights_the_cell_it_was_cut_from():
    root = _building()
    was = _buried(root)
    seen = set()
    for seed in range(12):
        child, desc = operators.mutate_light_well(root, np.random.default_rng(seed), [], reqs=REQS)
        geometry.clear_cache()
        assert desc.startswith("light_well ") and "noop" not in desc, desc
        lvls = dom.levels(child)
        wells = [lf for lvl in lvls for lf in lvl.leaves() if lf.type == "O"]
        assert wells and all(not dom.is_covered(w) for w in wells), desc
        # the cell it was cut from is no longer buried, on its storey at least
        li = int(desc.split()[1].split("/")[0])
        still = {k[:2] for k in _buried(child)}
        gone = {k[:2] for k in was} - still
        assert any(k[0] == li for k in gone), (desc, _lit(child))
        # nothing was retyped away: every room is still there
        assert {lf.type for lvl in lvls for lf in lvl.leaves()} >= {"l1", "b1", "k1", "b2"}
        # the room it was cut from still opens off the corridor, and so does
        # the well: nobody's door was taken and the well has a way in
        G = geometry.leaf_graph(lvls[li])
        room = next(lf for lf in lvls[li].leaves() if lf.type in ("l1", "b1"))
        assert any(nb.type == "C" for nb in G.neighbors(room)), desc
        well = next(w for w in wells if dom._level_root(w) is lvls[li])
        assert any(nb.type == "C" for nb in G.neighbors(well)), desc
        seen.add(li)
    assert seen == {0, 1}          # it reaches a buried room on either storey
    # ...and the parent is not touched
    assert len(_buried(root)) == 2


def test_a_well_under_the_ground_floor_cell_reaches_the_storey_above_too():
    """Cut at the ground, the well has to go up through the room over it, or
    it is a loggia: the cell above is narrowed as well and keeps its name."""
    root = _building()
    for seed in range(30):
        child, desc = operators.mutate_light_well(root, np.random.default_rng(seed), [], reqs=REQS)
        if desc.startswith("light_well 0/"):
            assert "(2 storey(s) cut" in desc, desc
            geometry.clear_cache()
            assert not _buried(child), _lit(child)
            return
    pytest.fail("no draw chose the ground-floor cell")


def test_a_room_that_asks_for_no_window_is_not_given_one():
    root = _building(back0="st1", back1="st1")
    for seed in range(6):
        _child, desc = operators.mutate_light_well(root, np.random.default_rng(seed), [], reqs=REQS)
        assert "noop (no buried room)" in desc, desc


def test_nothing_buried_nothing_cut():
    root = _building()
    root.perimeter = {"a": None, "b": None, "c": None, "d": None}   # streets all round
    geometry.clear_cache()
    _child, desc = operators.mutate_light_well(root, np.random.default_rng(0), [], reqs=REQS)
    assert "noop" in desc


def test_circulation_is_never_cut_however_buried():
    """A corridor in the middle of a plan has no window and is not given a
    well: a strip out of it parts the corridor (the first census: two
    `inaccessible usable space` and an `access` fail for each room beyond)."""
    for buried in ("C", "E"):
        root = _building(back0=buried, back1=buried)
        for seed in range(6):
            child, desc = operators.mutate_light_well(
                root, np.random.default_rng(seed), [], reqs=REQS)
            assert "noop" in desc, desc


def test_a_room_keeps_its_door_and_a_well_has_a_way_in():
    """Of the ways to slice, the one that puts the well between the room and
    its corridor is never played."""
    def shut_in(child, desc) -> bool:
        li = int(desc.split()[1].split("/")[0])
        lvl = dom.levels(child)[li]
        G = geometry.leaf_graph(lvl)
        room = next(lf for lf in lvl.leaves() if lf.type in ("l1", "b1"))
        return not any(nb.type == "C" for nb in G.neighbors(room))

    root = _building()
    for seed in range(16):
        child, desc = operators.mutate_light_well(root, np.random.default_rng(seed), [], reqs=REQS)
        geometry.clear_cache()
        assert "noop" not in desc and not shut_in(child, desc), desc
    # The rule has to be able to say no. On a plot too narrow to slice a
    # room at right angles to its corridor, a well can only go between a
    # bedroom and the corridor (the room is shut in) or at its far end (the
    # well has no way in): nothing is cut. Give the same room a use that
    # opens onto outdoor space and the far-end well is allowed.
    def narrow(back: str):
        root = _building(back0=back, back1=back)
        root.node = [[0.0, 0.0], [4.0, 0.0], [4.0, 20.0], [0.0, 20.0]]
        dom.link(root)
        geometry.clear_cache()
        return root

    for seed in range(8):
        _c, desc = operators.mutate_light_well(narrow("b1"), np.random.default_rng(seed),
                                               [], reqs=REQS)
        assert "noop" in desc, desc
    child, desc = operators.mutate_light_well(narrow("l1"), np.random.default_rng(0),
                                              [], reqs=REQS)
    geometry.clear_cache()
    assert "reached through the room" in desc and not shut_in(child, desc), desc


def test_the_search_does_not_draw_it_unless_asked(monkeypatch):
    from homemaker_layout import driver
    from pathlib import Path

    PH = Path(__file__).resolve().parent.parent / "examples" / "harbor-house"
    if not (PH / "init.dom").exists():
        pytest.skip("examples absent")
    drawn = []
    real = operators.mutate_light_well
    monkeypatch.setitem(operators.MUTATIONS, "light_well",
                        lambda *a, **k: (drawn.append(1), real(*a, **k))[1])
    monkeypatch.delenv("HOMEMAKER_LIGHT_WELL", raising=False)
    driver.search(dom.load(str(PH / "init.dom")), str(PH), budget=1500, child_budget=20, seed=1)
    assert not drawn
    monkeypatch.setenv("HOMEMAKER_LIGHT_WELL", "1")
    driver.search(dom.load(str(PH / "init.dom")), str(PH), budget=1500, child_budget=20, seed=1)
    assert drawn, "the flagged search never drew the move: a vacuous test"

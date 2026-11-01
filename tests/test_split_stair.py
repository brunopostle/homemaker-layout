"""`mutate_split_stair` (homemaker-py-yd6t): the owner's ruling that a long stair
is a stair and a corridor (§39.193). One cut on every storey of the shaft, one end
staying `E` at one path, the rest `C`, and no other wall moving."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, driver, geometry, graph, operators

DESIGN = (Path(__file__).resolve().parent.parent
          / "experiments/results/halving-maple-single/winner.dom")
LONG = "rrrl"                  # 28.7 x 1.2 m on all three storeys (§39.187)


@pytest.fixture(autouse=True)
def orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()


def _design():
    return operators._finalise(dom.load(str(DESIGN)))


def _shape(root, skip=None):
    geometry.clear_cache()
    return {(li, lf.id): (lf.type, [geometry.coordinate(lf, i) for i in range(geometry.n_edges(lf))])
            for li, lvl in enumerate(dom.levels(root)) for lf in lvl.leaves()
            if skip is None or not (lf.id or "").startswith(skip)}


@pytest.mark.parametrize("seed", range(6))
def test_one_cut_on_every_storey_and_no_other_wall_moves(seed):
    root = _design()
    before = _shape(root, "rrr")   # the cut widening the shaft narrows `rrrr`
    child, desc = operators.mutate_split_stair(root, np.random.default_rng(seed), [])
    assert desc.startswith(f"split_stair {LONG}") and "(3 storeys)" in desc
    assert _shape(child, "rrr") == before
    lvls = dom.levels(child)
    stair = desc.split()[1]
    other = LONG + ("r" if stair.endswith("l") else "l")
    for lvl in lvls:
        assert lvl.by_id(stair).type == dom.GENERIC_STAIR
        assert lvl.by_id(other).type == "C"
    foot = lvls[0].by_id(stair)
    assert len(graph.stair_shaft(foot)) == 3
    # across the long side: the stair is what the move says, and no narrower
    geometry.clear_cache()
    assert operators._stair_length(foot) == pytest.approx(operators.SPLIT_STAIR_KEEP_M, abs=0.5)
    assert operators._stair_length(lvls[0].by_id(other)) > 15


@pytest.mark.parametrize("seed", range(4))
def test_the_two_parts_have_a_door_and_no_storey_is_lost(seed):
    child, desc = operators.mutate_split_stair(_design(), np.random.default_rng(seed), [])
    geometry.clear_cache()
    for lvl in dom.levels(child):
        G = geometry.leaf_graph(lvl, graph.DOOR_WIDTH)
        assert G.has_edge(lvl.by_id(LONG + "l"), lvl.by_id(LONG + "r"))


def test_without_the_widening_there_is_no_door(monkeypatch):
    """Negative control: the check above fires on the shaft as it stands (1.196 m)."""
    monkeypatch.setattr(operators, "_widen_for_door", lambda *a: True)
    child, _ = operators.mutate_split_stair(_design(), np.random.default_rng(0), [])
    geometry.clear_cache()
    lvl = dom.levels(child)[0]
    G = geometry.leaf_graph(lvl, graph.DOOR_WIDTH)
    assert not G.has_edge(lvl.by_id(LONG + "l"), lvl.by_id(LONG + "r"))


def test_both_ends_are_drawn():
    root = _design()
    got = {operators.mutate_split_stair(root, np.random.default_rng(s), [])[1].split()[1]
           for s in range(20)}
    assert got == {LONG + "l", LONG + "r"}


def test_a_split_stair_is_not_split_again():
    child, _ = operators.mutate_split_stair(_design(), np.random.default_rng(0), [])
    _, desc = operators.mutate_split_stair(child, np.random.default_rng(1), [])
    assert "noop" in desc


def test_a_short_stair_declines():
    root = _design()
    for lvl in dom.levels(root):
        lvl.by_id(LONG).type = "C"
    _, desc = operators.mutate_split_stair(root, np.random.default_rng(0), [])
    assert "noop" in desc


def test_a_shaft_under_a_divided_cell_declines():
    """That cell would read its cut from the new one, and its wall would move."""
    root = _design()
    top = dom.levels(root)[2].by_id(LONG)
    top.type, top.division, top.rotation = None, [0.5, 0.5], 0
    top.left, top.right = dom.Node(type="C"), dom.Node(type="C")
    root = operators._finalise(root)
    assert len(graph.stair_shaft(dom.levels(root)[0].by_id(LONG))) == 2
    _, desc = operators.mutate_split_stair(root, np.random.default_rng(0), [])
    assert "noop" in desc


def test_off_by_default():
    assert "split_stair" in operators.MUTATIONS
    assert 'os.environ.get("HOMEMAKER_SPLIT_STAIR", "") != "1"' in Path(driver.__file__).read_text()

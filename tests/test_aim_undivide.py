"""`undivide`, aimed at a failing cell (`homemaker-py-iplo`, DESIGN.md §39.123).

The recordings said an undivide that lands beside a failing cell removes a
fail about nine times as often as one that does not. Given its parent's fail
lines the move now lands there on purpose, half the time.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, driver, geometry, operators

REPO = Path(__file__).resolve().parent.parent
PH = REPO / "examples" / "programme-house"
DESIGN = PH / "coldstart-1a24b6a+orth-500000-s0.dom"

pytestmark = pytest.mark.skipif(not DESIGN.exists(), reason="examples absent")


def _design():
    root = dom.load(str(DESIGN))
    dom.link(root)
    geometry.clear_cache()
    return root


def _a_leaf_with_a_leaf_sibling(root):
    for li, lvl in enumerate(dom.levels(root)):
        for li2, n in operators._owned_branches(root):
            if li2 == li and not n.left.divided and not n.right.divided:
                return li, n
    raise AssertionError("no cut between two leaves")


def test_the_cells_are_read_off_the_fail_lines():
    assert operators.failing_cells(
        ["0/lrl width", "1/rll (t2) not adjacent to c", "level 0 not connected",
         "staircase volume", "missing required space: t1"]) == {(0, "lrl"), (1, "rll")}
    assert operators.failing_cells(None) == set()


def test_without_fail_lines_the_move_is_the_move_it_was():
    root = _design()
    for seed in range(12):
        a, da = operators.mutate_undivide(root, np.random.default_rng(seed), ["C", "O"])
        b, db = operators.mutate_undivide(root, np.random.default_rng(seed), ["C", "O"],
                                          fails=())
        c, dc = operators.mutate_undivide(root, np.random.default_rng(seed), ["C", "O"],
                                          fails=["staircase volume"])     # names no cell
        assert da == db == dc and "aimed" not in da
        # ...and it drew nothing more: the stream is where it was
        ra, rb = np.random.default_rng(seed), np.random.default_rng(seed)
        operators.mutate_undivide(root, ra, ["C", "O"])
        operators.mutate_undivide(root, rb, ["C", "O"], fails=["staircase volume"])
        assert ra.random() == rb.random()


def test_aimed_it_removes_the_wall_beside_the_failing_cell(monkeypatch):
    root = _design()
    li, n = _a_leaf_with_a_leaf_sibling(root)
    fails = [f"{li}/{n.left.id} width"]
    monkeypatch.setattr(operators, "AIM_SHARE", 1.0)
    for seed in range(12):
        _child, desc = operators.mutate_undivide(root, np.random.default_rng(seed),
                                                 ["C", "O"], fails=fails)
        assert desc == f"undivide {li}/{n.id or 'root'} aimed", desc
    # the control: unaimed, it lands there no more than now and then
    monkeypatch.setattr(operators, "AIM_SHARE", 0.0)
    there = sum(operators.mutate_undivide(root, np.random.default_rng(s), ["C", "O"],
                                          fails=fails)[1].split()[1] == f"{li}/{n.id or 'root'}"
                for s in range(40))
    assert there < 30


def test_a_merged_failing_cell_is_found_from_inside(monkeypatch):
    """The scorer names a merged cell by its parent's address; the cut to
    remove is then any cut whose cells lie INSIDE it."""
    root = _design()
    li, n = _a_leaf_with_a_leaf_sibling(root)
    if not n.id:
        pytest.skip("the only such cut is the root")
    monkeypatch.setattr(operators, "AIM_SHARE", 1.0)
    _child, desc = operators.mutate_undivide(root, np.random.default_rng(0), ["C", "O"],
                                             fails=[f"{li}/{n.id} size"])
    assert desc.endswith(" aimed")


def test_half_the_draws_are_left_to_chance():
    root = _design()
    li, n = _a_leaf_with_a_leaf_sibling(root)
    fails = [f"{li}/{n.left.id} width"]
    aimed = sum("aimed" in operators.mutate_undivide(
        root, np.random.default_rng(s), ["C", "O"], fails=fails)[1] for s in range(200))
    assert 70 < aimed < 130


def test_the_search_hands_over_the_fail_lines_only_when_asked(monkeypatch):
    seen = []
    real = operators.mutate

    def spy(*a, **k):
        seen.append(k.get("fails"))
        return real(*a, **k)

    monkeypatch.setattr(operators, "mutate", spy)
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    monkeypatch.setattr(driver, "AIM_UNDIVIDE", False)
    driver.search(dom.load(str(PH / "init.dom")), str(PH), budget=900, child_budget=20, seed=2)
    assert seen and all(f is None for f in seen)
    seen.clear()
    monkeypatch.setattr(driver, "AIM_UNDIVIDE", True)
    driver.search(dom.load(str(PH / "init.dom")), str(PH), budget=900, child_budget=20, seed=2)
    assert any(f for f in seen), "no parent ever had a fail line to hand over"
    geometry.clear_cache()

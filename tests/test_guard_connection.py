"""The connection guard (`homemaker-py-2g7.13.1.10`, DESIGN.md §39.167).

In the maple spine race the winner sold all three storeys' connection in one
stage, because three `level N not connected` fails cost less than whatever a
connected circulation cost the rooms around it. With the guard on, a bred
child that leaves a storey `not connected` which its parent had connected is
declined: its evaluations are spent, and it is never ranked, bred from or best.

Since the owner's ruling of §39.179 (`homemaker-py-1d5p`) the default mode is
`connected`: only a parent with EVERY storey connected is guarded. `any` is the
guard as §39.173/§39.178 raced it.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from homemaker_layout import dom, driver, geometry

REPO = Path(__file__).resolve().parent.parent
PH = REPO / "examples" / "programme-house"

pytestmark = pytest.mark.skipif(not (PH / "init.dom").exists(), reason="examples absent")


def test_only_a_new_disconnection_counts():
    assert driver.disconnects(["level 1 not connected"], [])
    assert driver.disconnects(["level 0 not connected", "level 2 not connected"],
                              ["level 0 not connected"])
    # a storey already in pieces may stay so, and joining one is welcome
    assert not driver.disconnects(["level 1 not connected"], ["level 1 not connected"])
    assert not driver.disconnects([], ["level 1 not connected"])
    # the other connectivity fails are not a storey coming apart
    assert not driver.disconnects(["level 1 not connected to level 0",
                                   "3 inaccessible usable space"], [])
    assert not driver.disconnects(["0/lrl width"], [])


def test_connected_mode_guards_only_a_fully_connected_parent():
    child = ["level 1 not connected"]
    assert driver.guard_declines(child, [], "connected")
    assert driver.guard_declines(child, [], "any")
    assert not driver.guard_declines(child, [], "off")
    # a parent already in pieces on storey 0 breeds unguarded by default ...
    partly = ["level 0 not connected"]
    assert not driver.guard_declines(child + partly, partly, "connected")
    # ... where the guard as raced turned the child away
    assert driver.guard_declines(child + partly, partly, "any")
    # and no mode declines a child that disconnects nothing new
    for mode in driver.GUARD_MODES:
        assert not driver.guard_declines(partly, partly, mode)


def test_guard_modes_parse_and_default_to_connected(monkeypatch):
    assert driver.guard_mode("1") == driver.guard_mode("on") == "connected"
    assert driver.guard_mode("0") == "off"
    assert driver.guard_mode("ANY") == "any"
    with pytest.raises(ValueError):
        driver.guard_mode("sometimes")
    from homemaker_layout import evolve
    monkeypatch.delenv("HOMEMAKER_GUARD_CONNECTION", raising=False)
    assert evolve._parse_args(["init.dom"]).guard_connection == "connected"
    assert evolve._parse_args(["init.dom", "--guard-connection"]).guard_connection == "connected"
    assert evolve._parse_args(["init.dom", "--guard-connection=any"]).guard_connection == "any"
    assert evolve._parse_args(["init.dom", "--no-guard-connection"]).guard_connection == "off"


def _search_where_every_child_disconnects(monkeypatch, guard: str):
    """A tiny search whose every BRED child is made to fail a storey its
    parent did not. Seeds (lineage `construct/...`) are left as scored."""
    real = driver._evaluate

    def evaluate(*a, **k):
        ind, used = real(*a, **k)
        if not ind.lineage.startswith(("construct/", "pruned/")):
            ind = dataclasses.replace(ind, fails=ind.fails + ("level 9 not connected",))
        return ind, used

    monkeypatch.setattr(driver, "_evaluate", evaluate)
    monkeypatch.setattr(driver, "GUARD_CONNECTION", guard)
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    try:
        return driver.search(dom.load(str(PH / "init.dom")), str(PH),
                             budget=900, child_budget=20, seed=2)
    finally:
        geometry.clear_cache()


def test_the_guard_declines_every_disconnecting_child(monkeypatch):
    r = _search_where_every_child_disconnects(monkeypatch, guard="any")
    assert r.n_declined > 0
    assert all(p.lineage.startswith("construct/") for p in r.population)
    assert r.best.lineage.startswith("construct/")


def test_without_the_guard_those_children_are_admitted(monkeypatch):
    """The negative control: the same search, guard off, keeps bred children,
    so the test above is not passing because no child was ever admissible."""
    r = _search_where_every_child_disconnects(monkeypatch, guard="off")
    assert r.n_declined == 0
    assert any(not p.lineage.startswith("construct/") for p in r.population)

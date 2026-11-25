"""Programme spaces that are circulation, public spaces, and the street as an
adjacency target (owner's rulings, 2026-11-25, DESIGN.md §39.271).

The health-centre redo's draft C (`experiments/proposals/health-centre-r2a9c`)
is the first programme to use them; every live programme declares none of
them, and the scorer is bit-identical on every committed design with the
code present (§39.271). Each test has its control.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from homemaker_layout import dom, geometry, graph
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parent.parent
LIVE = REPO / "examples" / "health-centre"
DRAFT = REPO / "experiments" / "proposals" / "health-centre-r2a9c"
DESIGN = REPO / "experiments/results/halving-health-swap/winner.dom"


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    dom.set_programme_kinds()
    geometry.clear_cache()


def _load():
    if not DESIGN.is_file() or not DRAFT.is_dir():
        pytest.skip("no design or draft")
    root = dom.load(str(DESIGN))
    dom.link(root)
    geometry.clear_cache()
    return root


def _fit(d):
    return Fitness(*load_config(d))


def test_a_circulation_space_is_circulation():
    root = _load()
    cell = next(lf for lf in dom.levels(root)[0].leaves() if lf.type == "wa1")
    _fit(DRAFT).score_with_fails(_load())
    assert "wa1" in dom.PROGRAMME_CIRCULATION and dom.is_circulation(cell)
    # control: under the live programme the waiting room is a room
    _fit(LIVE).score_with_fails(_load())
    assert not dom.PROGRAMME_CIRCULATION and not dom.is_circulation(cell)


def test_c_is_met_beside_a_circulation_space():
    dom.set_programme_kinds(circulation=["wa1"])
    assert "wa1" in graph._adjacency_target("c")
    dom.set_programme_kinds()
    assert "wa1" not in graph._adjacency_target("c")          # control


def test_the_street_target_is_a_wall_on_the_street():
    root = _load()
    fit = _fit(DRAFT)
    lvl = dom.levels(root)[0]
    on = [lf for lf in lvl.leaves() if fit._public_access(lf, root) is not None]
    off = [lf for lf in lvl.leaves() if fit._public_access(lf, root) is None]
    assert on and off
    G = geometry.leaf_graph(lvl, graph.DOOR_WIDTH)
    street = lambda leaf: fit._public_access(leaf, root) is not None  # noqa: E731
    assert graph.has_adjacency(on[0], "street", G, street=street)
    assert not graph.has_adjacency(off[0], "street", G, street=street)     # control
    assert not graph.has_adjacency(on[0], "street", G)                     # no test given


def test_a_public_space_serves_no_utility_room():
    wa = dom.Node(type="wa1")
    usages = {"wa1": "circulation"}
    dom.set_programme_kinds(circulation=["wa1"], public=["wa1"])
    assert not graph.serves_utility(wa, usages)
    dom.set_programme_kinds(circulation=["wa1"])                          # control
    assert graph.serves_utility(wa, usages)


def test_live_programmes_declare_none_of_it():
    for prog in ("health-centre", "harbor-house", "maple-court", "programme-house"):
        f = _fit(REPO / "examples" / prog)
        assert f._kinds == ([], [])


def test_the_draft_charges_the_ruling_on_an_old_design():
    """An old design has no lobby: draft C charges it missing; the live
    programme does not ask for one."""
    _s, draft = _fit(DRAFT).score_with_fails(_load())
    _s, live = _fit(LIVE).score_with_fails(_load())
    assert any("missing required space: lb1" in f for f in draft)
    assert not any("lb1" in f for f in live)

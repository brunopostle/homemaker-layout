"""`experiments/dnc_frozen.py`: a search of one region leaves everything
outside it exactly as it was (`homemaker-py-2g7.13.1.5`, DESIGN.md §39.166).

Each test has its negative control: the same draws without the freeze do
change the outside, so a check that never fires cannot pass."""

import copy
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, geometry, innerloop, operators, solver

REPO = Path(__file__).resolve().parents[1]
WINNER = REPO / "experiments/results/halving-harbor/winner-total.dom"
WING = REPO / "experiments/results/dnc-wing/wing.dom"
ALL = "-"   # a region no path starts with: everything is outside it

pytestmark = pytest.mark.skipif(not (WINNER.is_file() and WING.is_file()),
                                reason="results absent")


def _tool():
    spec = importlib.util.spec_from_file_location("dnc_frozen", REPO / "experiments/dnc_frozen.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def test_pasting_the_wing_as_built_gives_the_building_back(orth):
    t = _tool()
    winner = dom.load(str(WINNER))
    back = t.paste(winner, dom.load(str(WING)), "l")
    assert t.outside(back, ALL) == t.outside(winner, ALL)
    # control: a different wing pasted in does change the building
    other = REPO / "experiments/results/dnc-wing/cold-50000-s1.dom"
    if other.is_file():
        assert t.outside(t.paste(winner, dom.load(str(other)), "l"), ALL) != t.outside(winner, ALL)


def test_frozen_mutations_leave_the_outside_alone(orth, monkeypatch):
    t = _tool()
    root = dom.load(str(WINNER))
    types = sorted({lf.type for lvl in dom.levels(root) for lf in lvl.leaves()})
    ref = t.outside(root, "l")

    def draws(n=60):
        rng = np.random.default_rng(1)
        return [operators.mutate(copy.deepcopy(root), rng, types)[0] for _ in range(n)]

    # control first: unfrozen, some child changes the outside
    assert any(t.outside(c, "l") != ref for c in draws())
    for name in ("mutate", "crossover"):
        monkeypatch.setattr(operators, name, getattr(operators, name))
    monkeypatch.setattr(solver, "free_branches", solver.free_branches)
    monkeypatch.setattr(innerloop, "free_with_keys", innerloop.free_with_keys)
    t.install("l")
    kids = draws()
    assert all(t.outside(c, "l") == ref for c in kids)
    assert any(t.outside(c, ALL) != t.outside(root, ALL) for c in kids)   # and they did move
    # the inner loop sees only the region's cuts
    assert innerloop.free_with_keys(root)
    assert all(k[1].startswith("l") for k, _ in innerloop.free_with_keys(root))
    assert all(b.id.startswith("l") for b in solver.free_branches(root))

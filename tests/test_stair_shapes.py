"""Owner's rulings on the stair fit model, 2026-11-08 (DESIGN.md §39.216,
`homemaker-py-5fje.12`):

* the turn count a stair's doors imply is a MAXIMUM: it may turn fewer times,
  and the best fit wins;
* every turned shape (L, U, three turns) has two flights across its base, and
  a flight narrows to fit its cell down to the 0.9 m domestic minimum, its
  landings with it.

Urb's model put two 1.25 m landings across every base, so a base under 2.5 m
counted a negative number of treads, and a 1.17 m cell read as a good U-stair.
Each case carries its control: the old rule, or the arm the owner turned down
(flights always 1.25 m), which made the owner's own programme-house stair a
missing one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from homemaker_layout import dom, geometry
from homemaker_layout.fitness import Fitness

REPO = Path(__file__).resolve().parent.parent
P1 = REPO / "experiments" / "results" / "phase1"
pytestmark = pytest.mark.skipif(not P1.is_dir(), reason="no phase1 twins")


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


@pytest.fixture(scope="module")
def diag():
    sys.path.insert(0, str(REPO / "experiments"))
    import diag_5fje12_stair_shapes as d
    return d


def _fitness(diag, programme):
    return Fitness(*diag.load_config(REPO / "examples" / programme))


def test_a_narrow_cell_is_not_a_u_stair(diag):
    # the A0 twin's stair is 1.17 m x 4.4 m: too narrow for two flights, so a
    # straight flight, too short for its storey height
    fit = _fitness(diag, "maple-court")
    path = P1 / "split-stair-race--final-double-1--A0.dom"
    _, _, now = diag.score(fit, path, Fitness._stair_fits)
    narrow = [f for _, short, _, f in now if short < 1.2]
    assert narrow and all(f < 0.85 for f in narrow)
    # control: Urb's rule counted -5 treads across and read it as a good fit
    _, _, urb = diag.score(fit, path, diag.urb_stair_fits)
    assert all(f > 1.1 for _, short, _, f in urb if short < 1.2)


def test_the_owners_hand_stair_is_a_stair(diag):
    # the hand design's 2.29 m U-stair: two 1.15 m flights, a good fit
    fit = _fitness(diag, "programme-house")
    path = P1 / "programme-house--hand-3storey--A0.dom"
    _, fails, now = diag.score(fit, path, Fitness._stair_fits)
    assert not any(f.startswith("too few stairs") for f in fails)
    assert now and all(0.95 < f < 1.15 for *_, f in now)
    # control: with every flight 1.25 m wide it is only a straight flight, too
    # short, and the building has no stair at all
    _, fails, _ = diag.score(fit, path, diag.fixed_width_stair_fits)
    assert any(f.startswith("too few stairs (0, min 1)") for f in fails)


def test_turns_are_a_maximum(diag):
    # a stair with one door corner may take any shape a four-corner stair can
    fit = _fitness(diag, "programme-house")
    root = dom.load(str(P1 / "programme-house--hand-3storey--A0.dom"))
    dom.link(root)
    leaf = next(lf for lf in dom.levels(root)[0].leaves() if lf.type == "E")
    one_door, four_doors = fit._stair_fits(leaf, [0]), fit._stair_fits(leaf, [0, 1, 2, 3])
    assert set(four_doors) < set(one_door)
    # control: Urb's rule gave each door count its own shape, so neither
    # contains the other
    assert not set(diag.urb_stair_fits(fit, leaf, [0, 1, 2, 3])) <= set(
        diag.urb_stair_fits(fit, leaf, [0]))

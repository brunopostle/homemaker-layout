"""A sliver room is a fail in a finished design (owner's ruling, §39.222).

"a sliver room is a fail in a finished design, I can see that it might be ok in
an intermediate step." Rooms have no width target (§39.37), so before this a
room 0.05 m wide was scored on size and proportion alone and often failed
neither. Now a room cell whose usable rectangle is narrower than
``sliver_width`` (0.8 m, the owner's "no use for anything", §39.204) fails
``width``, graded by how near it is to passing so a search can climb out.

Circulation and outside cells already fail their own width gaussians far above
0.8 m, so they are untouched. A room that is not a sliver is not asked the
question at all, which keeps every other score bit-identical.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from homemaker_layout import dom as dom_mod, geometry
from homemaker_layout.fitness import CONF_DEFAULTS, FAIL_THRESHOLD, Fitness, load_config

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"
# A0-tiers harbor-house s2 carries two room cells 0.59-0.67 m wide, its rooms
# otherwise ordinary (§39.221, §39.222)
DESIGN = REPO / "experiments/results/phase3-q2/A0-tiers--harbor-house--2.dom"
pytestmark = pytest.mark.skipif(not DESIGN.exists(), reason="artefact absent")


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _rooms(root):
    return [l for lvl in dom_mod.levels(root) for l in lvl.leaves()
            if l.type not in dom_mod.GENERIC_OUTSIDE
            and l.type not in dom_mod.GENERIC_INDOOR_CIRCULATION]


def _fit(**overrides):
    conf, cost = load_config(EXAMPLES / "harbor-house", overrides=overrides or None)
    return Fitness(conf, cost)


def test_the_default_is_the_owners_figure():
    assert CONF_DEFAULTS["sliver_width"] == 0.8


def test_a_sliver_room_fails_width_and_no_other_room_is_asked():
    fit = _fit()
    root = dom_mod.load(str(DESIGN))
    slivers = 0
    for leaf in _rooms(root):
        w = geometry.usable_width(leaf)
        if w < 0.8:
            slivers += 1
            assert fit.factor_is_asked("width", leaf)
            f = fit.quality_width(leaf)
            assert f < FAIL_THRESHOLD
            assert f == pytest.approx(FAIL_THRESHOLD * w / 0.8)
        else:
            assert not fit.factor_is_asked("width", leaf)
            assert fit.quality_width(leaf) == 1.0
    assert slivers == 2


def test_the_fails_appear_and_the_negative_control_removes_only_them():
    root = dom_mod.load(str(DESIGN))
    _, on = _fit().score_with_fails(copy.deepcopy(root))
    _, off = _fit(sliver_width=0).score_with_fails(copy.deepcopy(root))
    assert set(off) <= set(on)
    gained = sorted(set(on) - set(off))
    assert gained == ["1/rrlrllll width", "1/rrlrllrl width"], gained


def test_a_missing_room_is_not_billed_for_it():
    """§38.12: the cascade bills a missing room only for checks every present
    room faces. A sliver is a property of a built cell."""
    fit = _fit()
    probe = dom_mod.Node(type="__room_probe__")
    assert not fit.factor_is_asked("width", probe)

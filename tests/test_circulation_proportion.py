"""Corridors have no aspect requirement (homemaker-py-hxi, DESIGN.md §39.22).

Owner's ruling: "there should be no cap on the proportion of a corridor,
especially for big buildings, the crinkliness rule is there to prevent these
becoming unpleasant spaces."

The tests below pin both halves of that — the cap is gone, AND crinkliness
still does the job the cap was wrongly doing, so removing it did not leave
long buried corridors unpunished.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path

import pytest

from homemaker_layout import dom as dom_mod
from homemaker_layout.fitness import (
    CONF_DEFAULTS, FAIL_THRESHOLD, Fitness, gaussian, load_config,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
pytestmark = pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(),
                                reason="examples absent")


def _fit(**ov):
    conf, cost = load_config(EXAMPLES / "harbor-house", overrides=ov)
    return Fitness(conf, cost)


def test_there_is_no_corridor_aspect_requirement():
    assert CONF_DEFAULTS["proportion_circulation"] is None
    fit = _fit()
    assert dom_mod.is_circulation(dom_mod.Node(type="C"))
    # any aspect at all scores 1.0 -- checked through the real code path
    for aspect in (1.0, 3.0, 12.0, 40.0):
        fit_leaf = dom_mod.Node(
            type="C", node=[[0.0, 0.0], [aspect, 0.0], [aspect, 1.0], [0.0, 1.0]])
        assert fit.quality_proportion(fit_leaf) == 1.0, aspect


def test_a_room_still_has_one():
    """The ruling is about corridors. A habitable room's aspect target stands."""
    fit = _fit()
    room = dom_mod.Node(type="r", node=[[0.0, 0.0], [12.0, 0.0], [12.0, 1.0], [0.0, 1.0]])
    assert fit.quality_proportion(room) < FAIL_THRESHOLD


def test_crinkliness_is_what_punishes_an_unpleasant_corridor():
    """The ruling's own justification, as arithmetic.

    A long BURIED corridor is exactly the unpleasant space the aspect cap was
    being used to prevent; crinkliness sends it to zero. A long corridor along
    a facade is a perfectly good corridor, and crinkliness likes it.
    """
    target, sigma = CONF_DEFAULTS["uncrinkliness_circulation"]
    h, width, length = 3.0, 2.4, 30.0
    area = width * length

    buried = 0.0                       # no illuminated wall at all
    assert buried == 0.0

    lit_one_side = (length * h) / area  # the long wall is a facade
    q = gaussian(1.0 / lit_one_side, 1.0, target, sigma)
    assert q > 0.85, "a daylit corridor along a facade should score well"


def test_removing_the_cap_only_ever_removes_proportion_fails():
    """It cannot introduce a failure, and it touches nothing but corridors."""
    old = {"proportion_circulation": [1.5, 0.5]}
    seen = 0
    for name in ("harbor-house", "maple-court", "health-centre", "programme-house"):
        d = EXAMPLES / name
        for p in sorted(d.glob("coldstart-500000-s*.dom")):
            root = dom_mod.load(str(p))
            c_old, cost = load_config(d, overrides=old)
            c_new, _ = load_config(d)
            _, f_old = Fitness(c_old, cost).score_with_fails(copy.deepcopy(root))
            _, f_new = Fitness(c_new, cost).score_with_fails(copy.deepcopy(root))
            assert not (set(f_new) - set(f_old)), "must not add a failure"
            assert all(f.endswith(" proportion") for f in set(f_old) - set(f_new))
            seen += 1
    assert seen >= 4


def test_the_shape_curve_dp_accepts_an_unbounded_aspect():
    """`leaf_constraints` feeds rmax into the DP; None must become inf, not crash
    and not silently fall back to a finite cap."""
    from homemaker_layout import shapecurve
    fit = _fit()
    leaf = dom_mod.Node(type="C", node=[[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0]])
    assert math.isinf(shapecurve.leaf_constraints(fit, leaf).rmax)


# --------------------------------------------------------------------------- #
# No size requirement either (homemaker-py-hxi, DESIGN.md §39.23)
# --------------------------------------------------------------------------- #

def test_there_is_no_corridor_size_requirement():
    assert CONF_DEFAULTS["size_circulation"] is None
    fit = _fit()
    for area in (5.0, 14.0, 30.0, 60.0, 200.0):
        leaf = dom_mod.Node(
            type="C", node=[[0.0, 0.0], [area, 0.0], [area, 1.0], [0.0, 1.0]])
        assert fit.quality_size(leaf) == 1.0, area


def test_a_corridor_does_not_inherit_a_rooms_size_target():
    """`get_space_params` falls through to a habitable default when a generic
    family key is missing. A key that is present but null must not fall
    through -- or a corridor silently acquires a 16 m2 target."""
    fit = _fit()
    assert fit.get_space_params("C", "size") is None
    assert fit.get_space_params("C", "proportion") is None
    assert fit.get_space_params("C", "width") == CONF_DEFAULTS["width_circulation"]


def test_twice_the_corridor_is_exactly_twice_as_bad():
    """The owner's argument, as arithmetic.

    "double the amount of corridor is simply twice as bad, so it should score
    the same as two half size corridors". Under a gaussian on area that was
    false -- splitting a corridor in two raised its total value, which is a
    pure artefact of how the tree happens to be cut. Value must be linear in
    corridor area, so that one 2A leaf and two A leaves contribute the same.
    """
    fit = _fit()
    rate = fit.conf("value_circulation")

    def value(area):
        leaf = dom_mod.Node(
            type="C", node=[[0.0, 0.0], [area, 0.0], [area, 1.0], [0.0, 1.0]])
        return fit.quality_size(leaf) * rate * area

    assert value(20.0) == pytest.approx(2 * value(10.0))
    assert value(60.0) == pytest.approx(6 * value(10.0))

    # and under the old gaussian it was not -- this is what changed.
    # One 20 m2 corridor scored gaussian(20) = 0.360, two 10 m2 halves
    # gaussian(10) = 0.775 each, so merely cutting the same corridor in two
    # multiplied its value by 2.15x.
    old_whole = gaussian(20.0, 1.0, 0.0, 14.0) * rate * 20.0
    old_halves = 2 * (gaussian(10.0, 1.0, 0.0, 14.0) * rate * 10.0)
    assert old_halves / old_whole == pytest.approx(2.15, abs=0.02), (
        "the old gaussian rewarded splitting a corridor; if that is no longer "
        "so, §39.23's justification needs revisiting")


def test_the_amount_of_circulation_is_priced_exactly_once():
    """Removing the per-leaf cap must not make corridors free -- but the charge
    that remains must also be the ONLY one (§39.24).

    The linear ramp is `value_circulation` against the build cost: every square
    metre of corridor is worth less than it costs, and because the score is
    `value / cost` that pressure is already proportional to how much of the
    building is corridor. `ratio_circulation` said the same thing a second time
    and is disabled; if it comes back, either it has a justification this test
    does not know about or the double count has returned.
    """
    fit = _fit()
    assert fit.conf("value_circulation") < fit.cost("inside"), (
        "a corridor must cost more to build than it is worth, or there is no "
        "linear ramp pushing the search to use less of it")
    assert fit.conf("ratio_circulation") is None, (
        "ratio_circulation duplicates the per-m2 economics (§39.24)")
    assert fit.conf("size_circulation") is None, "§39.23"
    assert fit.conf("proportion_circulation") is None, "§39.22"

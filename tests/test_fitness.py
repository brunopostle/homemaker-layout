"""Unit tests for fitness.py quality terms and helpers (oracle-free)."""

import pytest

from homemaker import dom, geometry
from homemaker.dom import Node
from homemaker.fitness import CONF_DEFAULTS, COST_DEFAULTS, Fitness, gaussian


def _leaf(type_: str, size: float = 4.0) -> Node:
    """Undivided level-root leaf with a square plot of side `size`."""
    geometry.clear_cache()
    return Node(
        node=[[0.0, 0.0], [size, 0.0], [size, size], [0.0, size]],
        type=type_,
    )


# --------------------------------------------------------------------------- #
# gaussian
# --------------------------------------------------------------------------- #


def test_gaussian_peak_returns_a():
    assert gaussian(5.0, 1.0, 5.0, 1.0) == pytest.approx(1.0)


def test_gaussian_peak_scales_by_a():
    assert gaussian(3.0, 2.5, 3.0, 1.0) == pytest.approx(2.5)


def test_gaussian_one_sigma_uses_truncated_e():
    # Urb uses e=2.718281828, not math.e; at one sigma the factor is e^-0.5
    e = 2.718281828
    expected = e ** -0.5
    assert gaussian(6.0, 1.0, 5.0, 1.0) == pytest.approx(expected, rel=1e-9)


def test_gaussian_symmetry():
    assert gaussian(4.0, 1.0, 5.0, 1.0) == pytest.approx(gaussian(6.0, 1.0, 5.0, 1.0))


# --------------------------------------------------------------------------- #
# Fitness.conf / cost
# --------------------------------------------------------------------------- #


def test_conf_falls_back_to_defaults():
    assert Fitness().conf("value_inside") == CONF_DEFAULTS["value_inside"]


def test_conf_override_wins():
    assert Fitness(conf={"value_inside": 999.0}).conf("value_inside") == 999.0


def test_conf_unknown_key_returns_none():
    assert Fitness().conf("no_such_key") is None


def test_cost_falls_back_to_defaults():
    assert Fitness().cost("inside") == COST_DEFAULTS["inside"]


def test_cost_override_wins():
    assert Fitness(cost={"inside": 42.0}).cost("inside") == 42.0


def test_cost_unknown_key_returns_zero():
    assert Fitness().cost("no_such_key") == 0.0


# --------------------------------------------------------------------------- #
# get_space_params lookup chain
# --------------------------------------------------------------------------- #


def test_get_space_params_circulation_size():
    assert Fitness().get_space_params("C", "size") == CONF_DEFAULTS["size_circulation"]


def test_get_space_params_outside_width():
    assert Fitness().get_space_params("O", "width") == CONF_DEFAULTS["width_outside"]


def test_get_space_params_sahn_proportion():
    assert Fitness().get_space_params("S", "proportion") == CONF_DEFAULTS["proportion_outside"]


def test_get_space_params_inside_falls_back_to_inside_defaults():
    assert Fitness().get_space_params("k1", "proportion") == CONF_DEFAULTS["proportion_inside"]
    assert Fitness().get_space_params("k1", "size") == CONF_DEFAULTS["size_inside"]


def test_get_space_params_named_space_overrides_default():
    f = Fitness(conf={"spaces": {"k1": {"size": [20.0, 4.0]}}})
    assert f.get_space_params("k1", "size") == [20.0, 4.0]


# --------------------------------------------------------------------------- #
# quality_proportion
# --------------------------------------------------------------------------- #


def test_quality_proportion_square_inside_returns_one():
    # aspect=1.0 < proportion_inside[0]=1.5 → 1.0
    assert Fitness().quality_proportion(_leaf("k1")) == pytest.approx(1.0)


def test_quality_proportion_square_outside_returns_one():
    # aspect=1.0 < proportion_outside[0]=1.5 → 1.0
    assert Fitness().quality_proportion(_leaf("O")) == pytest.approx(1.0)


def test_quality_proportion_square_circulation_returns_one():
    assert Fitness().quality_proportion(_leaf("C")) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# quality_size
# --------------------------------------------------------------------------- #


def test_quality_size_outside_always_one():
    assert Fitness().quality_size(_leaf("O")) == 1.0


def test_quality_size_sahn_always_one():
    assert Fitness().quality_size(_leaf("S")) == 1.0


def test_quality_size_inside_at_peak():
    # size_inside=[16.0,3.5]; leaf is 4×4=16 m² → gaussian at peak → 1.0
    leaf = _leaf("k1", size=4.0)
    assert geometry.area(leaf) == pytest.approx(16.0)
    assert Fitness().quality_size(leaf) == pytest.approx(1.0)


def test_quality_size_circulation_at_peak():
    # size_circulation=[0.0,14.0]; peak at 0, gaussian(area,1,0,14) → always <1 for area>0
    # Just verify it returns a value in [0,1]
    f = Fitness().quality_size(_leaf("C", size=4.0))
    assert 0.0 < f <= 1.0


# --------------------------------------------------------------------------- #
# quality_width
# --------------------------------------------------------------------------- #


def test_quality_width_wide_inside_returns_one():
    # width_inside=[4.0,1.0]; 10m side > 4.0 → 1.0
    assert Fitness().quality_width(_leaf("k1", size=10.0)) == pytest.approx(1.0)


def test_quality_width_wide_circulation_returns_one():
    # width_circulation=[2.4,0.2]; 10m > 2.4 → 1.0
    assert Fitness().quality_width(_leaf("C", size=10.0)) == pytest.approx(1.0)


def test_quality_width_wide_outside_ground_uses_gaussian():
    # outside at level 0 falls through to gaussian; 10m > width_outside[0]=3.0 → 1.0
    assert Fitness().quality_width(_leaf("O", size=10.0)) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# quality_perpendicular
# --------------------------------------------------------------------------- #


def test_quality_perpendicular_rectangle_near_one():
    # All four corners of the square are pi/2; perpendicular formula gives ≈1
    leaf = _leaf("k1", size=4.0)
    result = Fitness().quality_perpendicular(leaf)
    assert result == pytest.approx(1.0, abs=1e-6)


# --------------------------------------------------------------------------- #
# value_rate
# --------------------------------------------------------------------------- #


def test_value_rate_outside_ground():
    leaf = _leaf("O")
    assert dom.level_of(leaf) == 0
    assert Fitness().value_rate(leaf) == pytest.approx(CONF_DEFAULTS["value_outside"])


def test_value_rate_circulation():
    assert Fitness().value_rate(_leaf("C")) == pytest.approx(CONF_DEFAULTS["value_circulation"])


def test_value_rate_inside():
    assert Fitness().value_rate(_leaf("k1")) == pytest.approx(CONF_DEFAULTS["value_inside"])


# --------------------------------------------------------------------------- #
# leaf_cost
# --------------------------------------------------------------------------- #


def test_leaf_cost_outside_bare():
    # not covered, not supported → outside rate × area
    leaf = _leaf("O", size=4.0)  # area = 16.0
    assert Fitness().leaf_cost(leaf) == pytest.approx(COST_DEFAULTS["outside"] * 16.0)


def test_leaf_cost_inside():
    leaf = _leaf("k1", size=4.0)
    assert Fitness().leaf_cost(leaf) == pytest.approx(COST_DEFAULTS["inside"] * 16.0)


# --------------------------------------------------------------------------- #
# Stair helpers
# --------------------------------------------------------------------------- #


def test_risers_number_exact_division():
    # 2.0 / 0.25 = 8.0 exactly → returns 8
    assert Fitness._risers_number(2.0, 0.25) == 8


def test_risers_number_rounds_up():
    # 3.0 / 0.19 ≈ 15.789 → rounds up to 16
    assert Fitness._risers_number(3.0, 0.19) == 16


def test_ideal_going_clamps_to_minimum():
    # riser=0.25 → going=0.125 < 0.22 → clamp
    assert Fitness._ideal_going(0.25) == 0.22


def test_ideal_going_above_minimum():
    # riser=0.15 → going=0.325 > 0.22; result should be in valid range
    result = Fitness._ideal_going(0.15)
    assert result >= 0.22
    assert result <= 0.625

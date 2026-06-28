"""Unit tests for fitness.py quality terms and helpers (oracle-free)."""

import pytest

from homemaker_layout import dom, geometry
from homemaker_layout.dom import Node
from homemaker_layout.fitness import (
    CONF_DEFAULTS,
    COST_DEFAULTS,
    FAIL_THRESHOLD,
    Fitness,
    _leaf_grade,
    gaussian,
)


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
# Share-aware edge-too-long cap (hph §13.7)
# --------------------------------------------------------------------------- #


def _shared_leaf(type_: str = "k1", k: int = 3) -> Node:
    leaf = _leaf(type_)
    leaf.share = k
    leaf.share_type = type_
    return leaf


def test_edge_cap_flat_by_default():
    # no leaf_sharing → flat 8 m regardless of any share stamp
    fit = Fitness()
    assert fit._edge_cap(_shared_leaf(k=3)) == pytest.approx(8.0)


def test_edge_cap_flat_when_lever_off_even_with_sharing():
    # leaf_sharing on but the hph lever explicitly off → still flat (control arm).
    # Post-§13.8 the lever defaults ON under sharing, so the control must pin it.
    fit = Fitness(conf={"leaf_sharing": True, "share_edge_cap": False})
    assert fit._edge_cap(_shared_leaf(k=3)) == pytest.approx(8.0)


def test_edge_cap_scales_by_share_when_lever_on():
    fit = Fitness(conf={"leaf_sharing": True, "share_edge_cap": True})
    assert fit._edge_cap(_shared_leaf(k=3)) == pytest.approx(24.0)


def test_edge_cap_defaults_on_under_leaf_sharing():
    # §13.8 default flip: leaf_sharing on, lever unset → cap scales by share
    fit = Fitness(conf={"leaf_sharing": True})
    assert fit._edge_cap(_shared_leaf(k=3)) == pytest.approx(24.0)


def test_edge_cap_unshared_leaf_keeps_flat_cap():
    # a non-shared leaf (the narrow-sliver pathology) is never relaxed
    fit = Fitness(conf={"leaf_sharing": True, "share_edge_cap": True})
    assert fit._edge_cap(_leaf("k1")) == pytest.approx(8.0)


def test_edge_cap_stale_share_type_ignored():
    # retyped leaf whose stamp no longer matches type → share invalid → flat
    fit = Fitness(conf={"leaf_sharing": True, "share_edge_cap": True})
    leaf = _shared_leaf("k1", k=3)
    leaf.type = "b1"  # retyped; share_type still "k1"
    assert fit._edge_cap(leaf) == pytest.approx(8.0)


def test_edge_cap_uses_largest_share_among_adjoining_leaves():
    # an interior wall takes the max share of the two leaves it separates
    fit = Fitness(conf={"leaf_sharing": True, "share_edge_cap": True})
    cap = fit._edge_cap(_leaf("k1"), _shared_leaf("b1", k=2))
    assert cap == pytest.approx(16.0)


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


# --------------------------------------------------------------------------- #
# Graded high-fail objective (§11.4)
# --------------------------------------------------------------------------- #


def test_leaf_grade_no_failing_factors_is_zero():
    # All factors above FAIL_THRESHOLD → no proximity credit.
    assert _leaf_grade({"size": 0.9, "width": 1.0, "access": 1.0}) == 0.0


def test_leaf_grade_credits_only_failing_factors():
    # Only size fails (0.05 < 0.1); credit = 0.05 / 0.1 = 0.5.
    g = _leaf_grade({"size": 0.05, "width": 0.5, "proportion": 1.0})
    assert g == pytest.approx(0.05 / FAIL_THRESHOLD)


def test_leaf_grade_monotone_in_proximity():
    # A failing factor closer to the threshold scores higher (better).
    deep = _leaf_grade({"size": 0.01})
    shallow = _leaf_grade({"size": 0.09})
    assert shallow > deep


def test_leaf_grade_sums_over_failing_factors():
    g = _leaf_grade({"size": 0.04, "width": 0.06, "access": 1.0})
    assert g == pytest.approx((0.04 + 0.06) / FAIL_THRESHOLD)


def test_leaf_grade_ignores_non_graded_keys():
    # daylight is pinned and never a graded factor even if below threshold.
    assert _leaf_grade({"daylight": 0.0}) == 0.0


# --------------------------------------------------------------------------- #
# load_config overrides (homemaker-py-x3b)
# --------------------------------------------------------------------------- #


def test_load_config_overrides_merge_last(tmp_path):
    # The CLI/driver injects run-level knobs (leaf_sharing) without editing any
    # on-disk patterns.config, so §13.3 example programmes stay reproducible.
    import yaml

    from homemaker_layout.fitness import load_config

    (tmp_path / "patterns.config").write_text(
        yaml.safe_dump({"spaces": {"b": {"size": [12.0, 1.0]}}}))

    conf, _ = load_config(tmp_path)
    assert "leaf_sharing" not in conf  # absent on disk

    conf2, _ = load_config(tmp_path, overrides={"leaf_sharing": True})
    assert conf2["leaf_sharing"] is True
    assert conf2["spaces"]["b"] == {"size": [12.0, 1.0]}  # disk content preserved

    # None / empty overrides are a no-op (default-OFF parity).
    assert "leaf_sharing" not in load_config(tmp_path, overrides=None)[0]
    assert "leaf_sharing" not in load_config(tmp_path, overrides={})[0]


def test_programme_parses_per_code_share(tmp_path):
    # homemaker-py-x3b: SpaceReq carries the optional per-code 'share' grain and a
    # has_share flag distinguishing an explicit share:1 (opt out) from the default.
    import yaml

    from homemaker_layout.programme import load_programme

    p = tmp_path / "patterns.config"
    p.write_text(yaml.safe_dump({"spaces": {
        "b": {"size": [12.0, 1.0], "share": 3},
        "k": {"size": [20.0, 1.0]},            # no share key
    }}))
    reqs = load_programme(str(p))
    assert reqs["b"].share == 3 and reqs["b"].has_share is True
    assert reqs["k"].share == 1 and reqs["k"].has_share is False

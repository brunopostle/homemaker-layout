"""The `crinkliness_tail="ramp"` rescale (homemaker-py-9gj, DESIGN.md §39.13).

The whole design rests on one invariant: the ramp rewrites the failing compact
tail and NOTHING else, so no leaf crosses FAIL_THRESHOLD and the fail set is
byte-identical to stock. That is what makes it legal to score both arms of the
A/B under the stock objective (the §38.9 trap's one exemption). It is asserted
here on every committed corpus artefact rather than assumed.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from homemaker_layout import dom as dom_mod
from homemaker_layout.fitness import (
    FAIL_THRESHOLD, Fitness, _crink_at_fail_threshold, gaussian, load_config,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
PROGRAMMES = ["harbor-house", "maple-court", "health-centre", "programme-house"]


def _artefacts():
    for name in PROGRAMMES:
        d = EXAMPLES / name
        if not d.is_dir():
            continue
        for p in sorted(d.glob("coldstart-500000-s*.dom")) + \
                sorted(d.glob("evolved-3M*.dom")) + [d / "init.dom"]:
            if p.exists():
                yield d, p


def test_crossing_is_continuous_at_the_fail_threshold():
    """The ramp meets the gaussian exactly at FAIL_THRESHOLD, so the factor is
    continuous there and the ordering across the boundary is preserved."""
    for distance, sigma in ((5.0 / 6, 1.1 / 3), (1.2, 0.25), (0.5, 0.5)):
        c0 = _crink_at_fail_threshold(distance, sigma)
        assert gaussian(1 / c0, 1.0, distance, sigma) == pytest.approx(
            FAIL_THRESHOLD, rel=1e-12)
        # and it is the COMPACT-side root: less exposure than c0, not more
        assert 1 / c0 > distance


def test_ramp_is_strictly_monotone_where_the_gaussian_has_underflowed():
    """The point of the change. Stock assigns the same double -- 0.0 -- to
    every leaf below crink ~= 1/15; the ramp separates them."""
    distance, sigma = 5.0 / 6, 1.1 / 3
    c0 = _crink_at_fail_threshold(distance, sigma)
    crinks = [0.0, 0.001, 0.01, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, c0 * 0.999]

    stock = [gaussian(1 / c, 1.0, distance, sigma) if c else 0.0 for c in crinks]
    ramp = [FAIL_THRESHOLD * c / c0 for c in crinks]

    assert len(set(stock)) < len(set(ramp)), "stock should collapse values the ramp keeps"
    assert stock.count(0.0) > 1, "the flat-zero region is what this fixes"
    assert all(b > a for a, b in zip(ramp, ramp[1:])), "ramp must be strictly increasing"
    assert ramp[0] == 0.0, "a fully buried leaf is still worth nothing"
    assert all(q < FAIL_THRESHOLD for q in ramp), "the ramp must never lift a leaf out of failing"


@pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(),
                    reason="examples absent")
def test_fail_set_is_byte_identical_across_the_corpus():
    seen = 0
    for d, p in _artefacts():
        root = dom_mod.load(str(p))
        c_stock, cost = load_config(d)
        c_ramp, _ = load_config(d, overrides={"crinkliness_tail": "ramp"})
        _, f_stock = Fitness(c_stock, cost).score_with_fails(copy.deepcopy(root))
        _, f_ramp = Fitness(c_ramp, cost).score_with_fails(copy.deepcopy(root))
        assert f_stock == f_ramp, f"{p} changed its fail set under the ramp"
        seen += 1
    assert seen >= 4, "expected to have checked several corpus artefacts"


@pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(),
                    reason="examples absent")
def test_ramp_never_lowers_the_score():
    """Every affected factor rises (0 or ~0 -> a representable fraction of
    FAIL_THRESHOLD), and quality is a product with value accumulating
    positively, so the scalar can only go up or stay put."""
    for d, p in _artefacts():
        root = dom_mod.load(str(p))
        c_stock, cost = load_config(d)
        c_ramp, _ = load_config(d, overrides={"crinkliness_tail": "ramp"})
        s_stock, _ = Fitness(c_stock, cost).score_with_fails(copy.deepcopy(root))
        s_ramp, _ = Fitness(c_ramp, cost).score_with_fails(copy.deepcopy(root))
        assert s_ramp >= s_stock, f"{p} scored lower under the ramp"


def test_ramp_refuses_to_compose_with_the_superseded_modes():
    """§38.1's modes rewrite the same tail; stacking them would give a shape
    neither was measured under."""
    d = EXAMPLES / "harbor-house"
    if not d.is_dir():
        pytest.skip("examples absent")
    conf, cost = load_config(d, overrides={"crinkliness_tail": "ramp",
                                           "crinkliness_mode": "floor"})
    with pytest.raises(ValueError, match="incompatible"):
        Fitness(conf, cost)


def test_unknown_tail_is_rejected():
    d = EXAMPLES / "harbor-house"
    if not d.is_dir():
        pytest.skip("examples absent")
    conf, cost = load_config(d, overrides={"crinkliness_tail": "linear"})
    with pytest.raises(ValueError, match="unknown crinkliness_tail"):
        Fitness(conf, cost)


# --------------------------------------------------------------------------- #
# crinkliness_shape="daylight" (homemaker-py-9gj, DESIGN.md §39.14)
# --------------------------------------------------------------------------- #

def _q(distance, sigma, crink, **conf):
    """quality_uncrinkliness for a synthetic leaf at a given crinkliness.

    A bare `Node` with no type: `is_outside`/`is_covered` must both be False so
    the factor is actually evaluated rather than short-circuited to 1.0 for an
    uncovered outside leaf.
    """
    d = EXAMPLES / "harbor-house"
    c, cost = load_config(d, overrides=conf)
    fit = Fitness(c, cost)
    fit.crinkliness_params = lambda leaf: (distance, sigma)
    fit.crinkliness = lambda leaf, G, groups: crink
    leaf = dom_mod.Node(type="x1")
    assert not dom_mod.is_outside(leaf)
    return Fitness.quality_uncrinkliness(fit, leaf, None, None)


@pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(), reason="examples absent")
def test_daylight_shape_stops_penalising_surplus_daylight():
    """`1/crink` is depth-in-storey-heights; below `distance` the room is
    shallower than the stock peak, i.e. better lit than asked for. Stock
    decays from there; "daylight" does not."""
    b, s = 5.0 / 6, 1.1 / 3
    for crink in (1 / b, 1.5, 2.0, 4.0, 20.0):        # 1/crink <= b
        assert _q(b, s, crink, crinkliness_shape="daylight") == 1.0
        if crink > 1 / b:
            assert _q(b, s, crink) < 1.0, "stock should penalise surplus daylight"


@pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(), reason="examples absent")
def test_daylight_shape_leaves_the_under_lit_side_alone():
    """Only the surplus side is clipped. The graded approach to the daylight
    limit is the part that still does useful work, so it must not move."""
    b, s = 5.0 / 6, 1.1 / 3
    for crink in (0.62, 0.7, 0.9, 1.0, 1.19):          # 1/crink > b, passing
        assert _q(b, s, crink, crinkliness_shape="daylight") == _q(b, s, crink)


@pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(), reason="examples absent")
def test_daylight_shape_is_continuous_at_the_clip():
    """Clipping at the gaussian's peak rather than at FAIL_THRESHOLD is what
    keeps this continuous. Clipping at the threshold would put a 10x cliff on
    the exact boundary the 0.5**n fail multiplier already steps on."""
    b, s = 5.0 / 6, 1.1 / 3
    just_under = _q(b, s, 1 / b - 1e-9, crinkliness_shape="daylight")
    assert just_under == pytest.approx(1.0, abs=1e-6)


@pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(), reason="examples absent")
def test_every_combination_keeps_the_fail_set_byte_identical():
    """The invariant that makes stock scoring a valid yardstick for all arms.

    The over-exposed branch of the stock gaussian only fires above crinkliness
    21.5, and the corpus maximum is 3.95, so clipping that side removes no
    failure that any corpus artefact actually incurs.
    """
    combos = [{"crinkliness_tail": "ramp"},
              {"crinkliness_shape": "daylight"},
              {"crinkliness_shape": "daylight", "crinkliness_tail": "ramp"}]
    seen = 0
    for d, p in _artefacts():
        root = dom_mod.load(str(p))
        c_stock, cost = load_config(d)
        _, f_stock = Fitness(c_stock, cost).score_with_fails(copy.deepcopy(root))
        for ov in combos:
            c, _ = load_config(d, overrides=ov)
            _, f = Fitness(c, cost).score_with_fails(copy.deepcopy(root))
            assert f == f_stock, f"{p} changed its fail set under {ov}"
        seen += 1
    assert seen >= 4


def test_unknown_shape_is_rejected():
    d = EXAMPLES / "harbor-house"
    if not d.is_dir():
        pytest.skip("examples absent")
    conf, cost = load_config(d, overrides={"crinkliness_shape": "onesided"})
    with pytest.raises(ValueError, match="unknown crinkliness_shape"):
        Fitness(conf, cost)


def test_daylight_shape_refuses_to_compose_with_the_superseded_modes():
    d = EXAMPLES / "harbor-house"
    if not d.is_dir():
        pytest.skip("examples absent")
    conf, cost = load_config(d, overrides={"crinkliness_shape": "daylight",
                                           "crinkliness_mode": "compact_ok"})
    with pytest.raises(ValueError, match="incompatible"):
        Fitness(conf, cost)

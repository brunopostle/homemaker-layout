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

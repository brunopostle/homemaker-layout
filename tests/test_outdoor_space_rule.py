"""Outdoor space is a per-level requirement, not a fraction (DESIGN.md §39.25).

Owner: "Alexander simply says that all levels should have accessible outside
space, he doesn't say how much."

The codebase had both rules and had them the wrong way round: the qualitative
one Alexander states (`force_roof_garden`, which fails a level with no outdoor
space at all) was switched OFF in every corpus config, while the quantitative
one he does not state (`ratio_outside`, a gaussian on the outdoor fraction) was
switched on with four mutually contradictory targets.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from homemaker_layout import dom as dom_mod
from homemaker_layout.fitness import Fitness, load_config

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CORPUS = ["harbor-house", "maple-court", "health-centre", "programme-house"]
pytestmark = pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(),
                                reason="examples absent")


@pytest.mark.parametrize("name", CORPUS)
def test_the_qualitative_rule_is_on_and_the_quantitative_one_is_off(name):
    conf, _ = load_config(EXAMPLES / name)
    assert conf["force_roof_garden"], (
        "Alexander's requirement -- every level has accessible outside space --"
        " must actually be enforced")
    assert conf["ratio_outside"] is None, (
        "the outdoor FRACTION is not a rule Alexander states (§39.25)")


def test_a_level_with_no_outdoor_space_fails():
    """The rule has to bite, or turning it on achieved nothing. programme-house
    puts no outdoor space on its ground floor in every baseline seed."""
    d = EXAMPLES / "programme-house"
    seen = 0
    for p in sorted(d.glob("coldstart-500000-s*.dom")):
        conf, cost = load_config(d)
        _, fails = Fitness(conf, cost).score_with_fails(dom_mod.load(str(p)))
        assert any("no outside space" in f for f in fails), p.name
        seen += 1
    assert seen == 3


def test_that_failure_is_hard():
    """It is a structural provision no ratio-solve can supply, so it must tier
    HARD -- a soft fail would let the search buy it off with shape quality."""
    from homemaker_layout.fitness import classify_fail_tier
    assert classify_fail_tier("level 1 no outside space") == "hard"


def test_disabling_the_fraction_removes_no_failure():
    """`ratio_outside` was a value multiplier, never a fail source, so the only
    fail-set movement in §39.25 comes from switching the per-level rule ON."""
    for name in CORPUS:
        d = EXAMPLES / name
        for p in sorted(d.glob("coldstart-500000-s*.dom")):
            root = dom_mod.load(str(p))
            conf, cost = load_config(d)
            with_frac, _ = load_config(
                d, overrides={"ratio_outside": [0.15, 0.1]})
            _, f_off = Fitness(conf, cost).score_with_fails(copy.deepcopy(root))
            _, f_on = Fitness(with_frac, cost).score_with_fails(copy.deepcopy(root))
            assert f_off == f_on, f"{p.name}: ratio_outside moved a failure"

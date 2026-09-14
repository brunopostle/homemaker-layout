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


def _strip_outdoor_space(root, level_id):
    """Retype every usable outside leaf on one level to a code already in use
    on that level. Returns False if the level has no outdoor space to remove,
    or nothing safe to retype it to.
    """
    levels = dom_mod.levels(root)
    if level_id >= len(levels):
        return False
    leaves = levels[level_id].leaves()
    outside = [l for l in leaves
               if dom_mod.is_outside(l) and dom_mod.is_usable(l)]
    stand_in = next((l.type for l in leaves
                     if dom_mod.is_usable(l) and not dom_mod.is_outside(l)
                     and not dom_mod.is_generic(l.type)), None)
    if not outside or stand_in is None:
        return False
    for leaf in outside:
        leaf.type = stand_in
        leaf.share, leaf.share_type, leaf.co_type = 1, None, None
    return True


@pytest.mark.parametrize("name", CORPUS)
def test_the_rule_bites_when_a_level_has_no_outdoor_space(name):
    """The rule has to fire when the condition holds, and stay quiet when it
    does not -- or switching it on in §39.25 achieved nothing.

    This CONSTRUCTS the condition rather than looking for a corpus artefact
    that happens to exhibit it. The first version of this test asserted that
    every `programme-house/coldstart-*-500000-s*.dom` carried a
    `no outside space` fail, which was true of the §39.12 baseline layouts and
    stopped being true the moment `bk9` produced a programme-house ground floor
    with a terrace on it (§39.31). A test pinned to a defect in a checked-in
    search result fails precisely when the search stops making that mistake,
    which is backwards. §39.12 clause 3 already said it: a number quoted in a
    test carries the commit it was measured at. Construct the case instead.
    """
    d = EXAMPLES / name
    conf, cost = load_config(d)
    checked = 0
    for path in sorted(d.glob("coldstart-*-500000-s*.dom")):
        root = dom_mod.load(str(path))
        for level_id in range(len(dom_mod.levels(root))):
            stripped = copy.deepcopy(root)
            if not _strip_outdoor_space(stripped, level_id):
                continue  # nothing to remove on this level
            marker = f"level {level_id} no outside space"

            _, before = Fitness(conf, cost).score_with_fails(copy.deepcopy(root))
            assert marker not in before, (
                f"{path.name} level {level_id} has outdoor space, so the rule "
                f"must not fire")

            _, after = Fitness(conf, cost).score_with_fails(stripped)
            assert marker in after, (
                f"{path.name} level {level_id}: outdoor space removed and the "
                f"rule did not fire")
            checked += 1
    assert checked, f"{name}: no level with removable outdoor space to test"


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
        for p in sorted(d.glob("coldstart-*-500000-s*.dom")):
            root = dom_mod.load(str(p))
            conf, cost = load_config(d)
            with_frac, _ = load_config(
                d, overrides={"ratio_outside": [0.15, 0.1]})
            _, f_off = Fitness(conf, cost).score_with_fails(copy.deepcopy(root))
            _, f_on = Fitness(with_frac, cost).score_with_fails(copy.deepcopy(root))
            assert f_off == f_on, f"{p.name}: ratio_outside moved a failure"

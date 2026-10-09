"""A terrace must not be worth more per square metre than a real internal room.

Owner's ruling, DESIGN.md §39.19. It is an invariant of the objective rather
than a property of any one layout, and it needs BOTH halves of §39.18/§39.19 to
hold — the rate alone leaves a terrace 1.46x a room, the aggregation alone
2.23x. This asserts it end to end on the corpus, so that flipping either back
fails loudly here rather than quietly in a six-hour run.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest

from homemaker_layout import dom as dom_mod, geometry
from homemaker_layout.fitness import Fitness, load_config

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CORPUS = ["harbor-house", "maple-court", "health-centre", "programme-house"]
pytestmark = pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(),
                                reason="examples absent")


def _value_per_m2(overrides=None):
    """(room, terrace) mean value per m2 over the committed baseline layouts."""
    acc = defaultdict(lambda: [0.0, 0.0])
    for name in CORPUS:
        d = EXAMPLES / name
        for p in sorted(d.glob("coldstart-*-500000-s*.dom")):
            conf, cost = load_config(d, overrides=overrides)
            fit = Fitness(conf, cost)
            orig = Fitness.evaluate_leaf

            def ev(self, leaf, G, level_id, groups, fail, _o=orig):
                q, f = _o(self, leaf, G, level_id, groups, fail)
                if dom_mod.is_outside(leaf):
                    kind = "terrace" if dom_mod.level_of(leaf) else None
                elif dom_mod.is_circulation(leaf):
                    kind = None
                else:
                    kind = "room"
                if kind:
                    a = geometry.area(leaf)
                    acc[kind][0] += a
                    acc[kind][1] += q * self.value_rate(leaf) * a
                return q, f

            Fitness.evaluate_leaf = ev
            try:
                fit.score_with_fails(dom_mod.load(str(p)))
            finally:
                Fitness.evaluate_leaf = orig
    return tuple(acc[k][1] / acc[k][0] for k in ("room", "terrace"))


def test_a_terrace_is_worth_less_per_m2_than_a_room():
    room, terrace = _value_per_m2()
    assert terrace < room, (
        f"terrace {terrace:.1f}/m2 >= room {room:.1f}/m2 — §39.19 ruling broken")


def test_the_rate_alone_would_not_be_enough():
    """Documents why the aggregation default moved with the rate: revert the
    aggregation and the ruling breaks again, so neither half is optional."""
    room, terrace = _value_per_m2({"quality_aggregate": "product"})
    assert terrace > room, (
        "the product aggregation no longer violates the ruling — if that is a "
        "real improvement, §39.19's reasoning needs revisiting")


def test_usable_space_is_worth_more_than_it_costs_and_a_terrace_more_than_a_garden():
    """Owner's rulings of 2026-10-07 (DESIGN.md §39.115/§39.116), as rates per
    square metre: a room, a garden and a terrace are each worth more than they
    cost to build; a terrace is worth more than a garden and less than a room.

    This replaces `value_supported == value_outside`, which §39.19 chose and
    which left a terrace worth 100 against a cost of 110."""
    from homemaker_layout.fitness import COST_DEFAULTS

    for name in CORPUS:
        conf, cost = load_config(EXAMPLES / name)
        price = {**COST_DEFAULTS, **(cost or {})}
        assert conf["value_inside"] > price["inside"], name
        assert conf["value_outside"] > price["outside"], name
        assert conf["value_supported"] > price["outside_supported"], name
        assert conf["value_outside"] < conf["value_supported"] < conf["value_inside"], name


def test_circulation_is_deliberately_not_worth_what_it_costs():
    """The exception, and it is a ruling too: "any usable space" did not mean
    circulation, "as a building without any circulation has an efficient
    plan". If this ever fails, someone has made corridor profitable."""
    from homemaker_layout.fitness import COST_DEFAULTS

    for name in CORPUS:
        conf, cost = load_config(EXAMPLES / name)
        assert conf["value_circulation"] < {**COST_DEFAULTS, **(cost or {})}["inside"], name

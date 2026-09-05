"""`quality_aggregate="geometric_mean"` (homemaker-py-ecx, DESIGN.md §39.18).

Quality is a product over the factors, and leaf kinds face different numbers of
them: a room is judged on size, crinkliness and access, an outside leaf is
exempt from all three. Exemption alone therefore buys a higher quality, and
quality multiplies the value rate. The geometric mean divides that out.

Two invariants matter and both are asserted here:

* the fail set cannot move, because `evaluate_leaf` emits each fail from the
  factor itself before anything is combined;
* `factor_is_asked` must agree with the `quality_*` methods -- whenever it says
  a factor is exempt, that factor really is exactly 1.0. It is a separate
  statement of the same conditions, so it can drift; this pins it.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path

import pytest

from homemaker_layout import dom as dom_mod
from homemaker_layout.fitness import Fitness, load_config

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
PROGRAMMES = ["harbor-house", "maple-court", "health-centre", "programme-house"]
pytestmark = pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(),
                                reason="examples absent")


def _artefacts():
    for name in PROGRAMMES:
        d = EXAMPLES / name
        if not d.is_dir():
            continue
        for p in sorted(d.glob("coldstart-500000-s*.dom")) + [d / "init.dom"]:
            if p.exists():
                yield d, p


def test_exempt_factors_really_are_one():
    """The invariant `factor_is_asked` rests on, checked against every leaf in
    the corpus rather than assumed from reading the code."""
    checked = 0
    for d, p in _artefacts():
        conf, cost = load_config(d, overrides={"quality_aggregate": "product"})
        fit = Fitness(conf, cost)
        seen = []
        orig = Fitness.evaluate_leaf

        def ev(self, leaf, G, level_id, groups, fail, _o=orig, _s=seen):
            q, f = _o(self, leaf, G, level_id, groups, fail)
            _s.append((leaf, dict(f)))
            return q, f

        Fitness.evaluate_leaf = ev
        try:
            fit.score_with_fails(dom_mod.load(str(p)))
        finally:
            Fitness.evaluate_leaf = orig

        for leaf, factors in seen:
            for name, value in factors.items():
                if not fit.factor_is_asked(name, leaf):
                    assert value == 1.0, (
                        f"{p.name}: {name} is marked exempt for leaf "
                        f"{leaf.id!r} ({leaf.type!r}) but scored {value}")
                    checked += 1
    assert checked > 100, "expected plenty of exempt factors to check"


def test_fail_set_is_byte_identical():
    for d, p in _artefacts():
        root = dom_mod.load(str(p))
        c_prod, cost = load_config(d, overrides={"quality_aggregate": "product"})
        c_geo, _ = load_config(d, overrides={"quality_aggregate": "geometric_mean"})
        _, f_prod = Fitness(c_prod, cost).score_with_fails(copy.deepcopy(root))
        _, f_geo = Fitness(c_geo, cost).score_with_fails(copy.deepcopy(root))
        assert f_prod == f_geo, f"{p} changed its fail set under the geometric mean"


def test_geometric_mean_is_the_product_when_every_factor_is_asked():
    """No free lunch: a leaf asked all six should agree with `prod ** (1/6)`."""
    fit = Fitness(*load_config(EXAMPLES / "harbor-house"))
    leaf = dom_mod.Node(type="r")
    factors = {"perpendicular": 0.9, "proportion": 0.8, "size": 0.5,
               "width": 0.95, "crinkliness": 0.4, "access": 1.0, "daylight": 1.0}
    asked = [v for k, v in factors.items() if fit.factor_is_asked(k, leaf)]
    expected = math.prod(asked) ** (1.0 / len(asked))
    assert fit._aggregate_geometric(leaf, factors) == pytest.approx(expected)


def test_a_zero_factor_still_makes_the_leaf_worthless():
    """A fully buried leaf is worth nothing under either aggregation -- the
    geometric mean must not launder a zero into 0.4-ish."""
    fit = Fitness(*load_config(EXAMPLES / "harbor-house"))
    leaf = dom_mod.Node(type="r")
    factors = {"perpendicular": 1.0, "proportion": 1.0, "size": 1.0,
               "width": 1.0, "crinkliness": 0.0, "access": 1.0, "daylight": 1.0}
    assert fit._aggregate_geometric(leaf, factors) == 0.0


def test_it_does_not_underflow_where_the_product_would():
    """The point of computing in log space: six small factors multiply to a
    denormal, but their geometric mean is an ordinary number."""
    fit = Fitness(*load_config(EXAMPLES / "harbor-house"))
    leaf = dom_mod.Node(type="r")
    tiny = 1e-60
    factors = {k: tiny for k in ("perpendicular", "proportion", "size",
                                 "width", "crinkliness", "access")}
    factors["daylight"] = 1.0
    assert math.prod(factors[k] for k in factors) == 0.0      # product underflows
    assert fit._aggregate_geometric(leaf, factors) == pytest.approx(tiny, rel=1e-6)


def test_unknown_aggregate_is_rejected():
    conf, cost = load_config(EXAMPLES / "harbor-house",
                             overrides={"quality_aggregate": "mean"})
    with pytest.raises(ValueError, match="unknown quality_aggregate"):
        Fitness(conf, cost)

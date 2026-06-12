"""Inner-loop search tests against a fake evaluator (no perl, no oracle)."""

import numpy as np
import pytest

from homemaker import innerloop
from homemaker.oracle import Score


class FakeEvaluator:
    """Duck-typed OracleEvaluator over an analytic objective."""

    def __init__(self, fn):
        self.fn = fn
        self.n_evals = 0
        self.n_oracle_calls = 0

    def evaluate(self, xs):
        self.n_evals += len(xs)
        self.n_oracle_calls += 1
        return [Score(fitness=self.fn(np.asarray(x)), fails="") for x in xs]


def concave(x):
    # maximum 1.0 at 0.3 in every coordinate
    return float(1.0 - np.sum((x - 0.3) ** 2))


@pytest.mark.parametrize("search", [innerloop.compass_search, innerloop.cma_search])
def test_search_converges_on_concave(search):
    # the production configs trade final-digit polish for basin coverage
    # (multi-start sigma ladder), so assert basin convergence, not precision
    ev = FakeEvaluator(concave)
    r = search(ev, np.full(4, 0.7), budget=400)
    assert r.fitness > 0.99
    assert np.allclose(r.x, 0.3, atol=0.1)
    assert r.x0_fitness == pytest.approx(concave(np.full(4, 0.7)))


@pytest.mark.parametrize("search", [innerloop.compass_search, innerloop.cma_search])
def test_search_respects_budget_and_bounds(search):
    seen = []

    def spy(x):
        seen.append(x.copy())
        return concave(x)

    ev = FakeEvaluator(spy)
    r = search(ev, np.full(3, 0.5), budget=60)
    # one batch may run slightly over, but never a whole extra cycle
    assert r.n_evals == ev.n_evals <= 60 + 3 * 10
    assert all((x >= innerloop._EPS - 1e-12).all() and (x <= 1 - innerloop._EPS + 1e-12).all()
               for x in seen)


def test_compass_never_returns_worse_than_start():
    # a hostile objective: best at the start, everything else worse
    x0 = np.full(3, 0.5)

    def hostile(x):
        return -float(np.sum(np.abs(x - x0)))

    ev = FakeEvaluator(hostile)
    r = innerloop.compass_search(ev, x0, budget=100)
    assert r.fitness == pytest.approx(0.0)
    assert np.allclose(r.x, x0)

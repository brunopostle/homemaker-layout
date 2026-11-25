"""The building's travel factor (`homemaker-py-5fje.29`, DESIGN.md §39.270).

The owner: stairs placed so "a person trying to move from any pair of random
rooms has a minimum path to reverse". The score carries it as a graded
factor on the mean inter-storey detour over the plot's half-diagonal
(`detour_cap`, bar 0.75); WHERE to move a stair is a search move's. Each
test here has its control.
"""

from __future__ import annotations

import copy
import importlib.util
import math
import statistics
import sys
from pathlib import Path

import pytest

from homemaker_layout import dom, geometry, graph
from homemaker_layout.fitness import Fitness, classify_fail_tier, gaussian, load_config

REPO = Path(__file__).resolve().parent.parent
MAPLE = REPO / "experiments/results/split-stair-race/final-best-3.dom"     # three storeys, two shafts
HEALTH2 = REPO / "experiments/results/halving-health-swap/winner.dom"       # two storeys
HEALTH1 = REPO / "examples/health-centre/coldstart-4428262+orth-500000-s0.dom"


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _fit(prog, **conf):
    f = Fitness(*load_config(REPO / "examples" / prog))
    f._conf.update(conf)
    return f


def _load(path):
    if not path.is_file():
        pytest.skip("no design")
    root = dom.load(str(path))
    dom.link(root)
    geometry.clear_cache()
    return root


def _graphs(fit, root):
    m = copy.deepcopy(root)
    dom.merge_divided(m)
    dom.link(m)
    geometry.clear_cache()
    _, gc, _ = graph.storey_graphs(m, fit.conf("door_width") or 1.2, fit.usages())
    return m, gc


def _travel_tool():
    sys.path.insert(0, str(REPO / "experiments"))
    spec = importlib.util.spec_from_file_location(
        "travel", REPO / "experiments" / "diag_5fje29_stair_travel.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("path, prog", [(MAPLE, "maple-court"), (HEALTH2, "health-centre")])
def test_the_port_is_the_measured_tool(path, prog):
    """`graph.mean_detour` is the experiment's detour (itself held to the
    brute force, journeys that change stairs included)."""
    fit = _fit(prog)
    root = _load(path)
    T = _travel_tool()
    ex, _ra, _un = T.Walk(fit, copy.deepcopy(root)).detour()
    _m, gc = _graphs(fit, root)
    W, rooms, stairs = graph.travel_graph(gc)
    got, n = graph.mean_detour(W, rooms, stairs)
    assert n == len(ex) and got == pytest.approx(statistics.fmean(ex), abs=1e-9)


def test_over_the_bar_the_factor_is_the_gaussian():
    fit = _fit("maple-court")
    root = _load(MAPLE)
    m, gc = _graphs(fit, root)
    W, rooms, stairs = graph.travel_graph(gc)
    mean, _n = graph.mean_detour(W, rooms, stairs)
    x = mean / graph.plot_half_diagonal(m)
    bar, sigma = fit.conf("detour_cap")
    assert x > bar                                    # this design is over it
    lines = []
    f = fit.detour_factor(m, gc, lines.append)
    assert f == pytest.approx(gaussian(x, 1.0, bar, sigma)) and f < 1.0
    assert (f < 0.1) == bool(lines)


def test_control_off_is_off():
    on, off = _fit("maple-court"), _fit("maple-court", detour_cap=False)
    s_on = on.score_with_fails(_load(MAPLE))
    s_off = off.score_with_fails(_load(MAPLE))
    assert s_on[0] < s_off[0]
    m, gc = _graphs(off, _load(MAPLE))
    assert off.detour_factor(m, gc, lambda _l: None) == 1.0


def test_control_no_flight_no_journey():
    """With every stair relabelled a corridor nothing joins two storeys, so
    nothing is measured -- `level N not connected` charges that, not this."""
    fit = _fit("maple-court")
    root = _load(MAPLE)
    for lvl in dom.levels(root):
        for leaf in lvl.leaves():
            if leaf.type == dom.GENERIC_STAIR:
                leaf.type = "C"
    m, gc = _graphs(fit, root)
    W, rooms, stairs = graph.travel_graph(gc)
    assert graph.mean_detour(W, rooms, stairs)[1] == 0
    assert fit.detour_factor(m, gc, lambda _l: None) == 1.0


def test_one_storey_is_untouched():
    fit = _fit("health-centre")
    root = _load(HEALTH1)
    if len(dom.levels(root)) != 1:
        pytest.skip("not a one-storey design")
    m, gc = _graphs(fit, root)
    assert fit.detour_factor(m, gc, lambda _l: None) == 1.0


def test_stair_detour_is_soft():
    assert classify_fail_tier("stair detour") == "soft"


def test_half_diagonal_ignores_turning_the_plot():
    """A box in world coordinates grows when the plot is turned; the first
    version used one, and the scorer-invariance test caught it."""
    root = _load(MAPLE)
    a = graph.plot_half_diagonal(root)
    lvl = dom.levels(root)[0]
    pts = [geometry.coordinate(lvl, i) for i in range(geometry.n_edges(lvl))]
    assert a == pytest.approx(max(math.dist(p, q) for p in pts for q in pts) / 2)


# --- the move that acts on it ---------------------------------------------

DOUBLE = REPO / "experiments/results/join-clean9/final-double-1.dom"    # the move fires here


def _labels(root):
    from collections import Counter
    return Counter(lf.type for lv in dom.levels(root) for lf in lv.leaves())


def test_move_stair_swaps_a_column_and_shortens_the_journeys():
    import numpy as np
    from homemaker_layout import operators
    fit = _fit("maple-court")
    root = _load(DOUBLE)
    before = operators._building_detour(root, fit)
    child, msg = operators.mutate_move_stair(copy.deepcopy(root), np.random.default_rng(0), [], fit=fit)
    assert msg.startswith("move_stair ") and "noop" not in msg
    dom.link(child)
    assert _labels(child) == _labels(root)          # a swap: no room lost or gained
    assert dom.dumps(child).count("division") == dom.dumps(root).count("division")
    after = operators._building_detour(child, fit)
    assert after[1] >= before[1] and after[0] < before[0]
    gain = float(msg.rsplit("(", 1)[1].rstrip("%)")) / 100
    assert (before[0] - after[0]) / before[0] == pytest.approx(gain, abs=0.006)


def test_control_move_stair_without_fit_is_noop():
    import numpy as np
    from homemaker_layout import operators
    _, msg = operators.mutate_move_stair(_load(DOUBLE), np.random.default_rng(0), [])
    assert msg == "move_stair noop"


@pytest.mark.parametrize("env, drawn", [("", False), ("1", True)])
def test_default_search_never_draws_move_stair(monkeypatch, env, drawn):
    from homemaker_layout import driver, operators
    calls = []
    real = operators.mutate_move_stair
    monkeypatch.setitem(operators.MUTATIONS, "move_stair",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setenv("HOMEMAKER_MOVE_STAIR", env)
    monkeypatch.setitem(driver._MUTATION_WEIGHTS, "move_stair", 1000.0)
    corpus = REPO / "examples" / "programme-house"
    driver.search(dom.load(str(corpus / "init.dom")), corpus, budget=600, pop_size=4,
                  child_budget=20, seed_budget=60, seed=3)
    assert bool(calls) is drawn

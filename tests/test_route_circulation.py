"""`route_circulation`: a corridor routed to an unserved room, or between two
pieces of a storey's circulation, by cutting strips off the rooms it crosses
(`homemaker-py-8b2u.17.1`, DESIGN.md §39.272). Each test has its control."""

from __future__ import annotations

import copy
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, geometry, graph, operators
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parent.parent
SPLIT = REPO / "experiments/results/halving-maple-single/winner.dom"   # a storey in two pieces


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _load():
    if not SPLIT.is_file():
        pytest.skip("no design")
    root = dom.load(str(SPLIT))
    dom.link(root)
    geometry.clear_cache()
    return root


def _rooms(root, reqs):
    return Counter(lf.type for lv in dom.levels(root) for lf in lv.leaves() if lf.type in reqs)


def test_it_joins_the_pieces_and_keeps_every_room():
    fit = Fitness(*load_config(REPO / "examples" / "maple-court"))
    root = _load()
    child, msg = operators.mutate_route_circulation(copy.deepcopy(root), np.random.default_rng(3),
                                                    [], fit=fit)
    assert msg.startswith("route_circulation 2/two pieces"), msg
    dom.link(child)
    assert _rooms(child, fit._programme) == _rooms(root, fit._programme)   # strips, not retypes
    lvl_p, lvl_c = dom.levels(root)[2], dom.levels(child)[2]

    def pieces(lvl):
        G = geometry.leaf_graph(lvl, graph.DOOR_WIDTH)
        ind = G.subgraph([x for x in G if not dom.is_outside(x)])
        import networkx as nx
        return nx.number_connected_components(ind.subgraph([x for x in ind if dom.is_circulation(x)]))
    geometry.clear_cache()
    before = pieces(lvl_p)
    geometry.clear_cache()
    assert pieces(lvl_c) < before


def test_control_without_fit_is_noop():
    _, msg = operators.mutate_route_circulation(_load(), np.random.default_rng(0), [])
    assert msg == "route_circulation noop"


@pytest.mark.parametrize("env, drawn", [("", False), ("1", True)])
def test_default_search_never_draws_it(monkeypatch, env, drawn):
    from homemaker_layout import driver
    calls = []
    real = operators.mutate_route_circulation
    monkeypatch.setitem(operators.MUTATIONS, "route_circulation",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setenv("HOMEMAKER_ROUTE_CIRCULATION", env)
    monkeypatch.setitem(driver._MUTATION_WEIGHTS, "route_circulation", 1000.0)
    corpus = REPO / "examples" / "programme-house"
    driver.search(dom.load(str(corpus / "init.dom")), corpus, budget=600, pop_size=4,
                  child_budget=20, seed_budget=60, seed=3)
    assert bool(calls) is drawn

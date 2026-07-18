"""Tests for the graded circulation-connectivity signal (homemaker-py-qi6, §18).

Covers:
  - graph.circulation_connectivity: largest-circ-component fraction, non-circ
    cells ignored, empty → 0.0, monotone under (dis)connection.
  - Fitness conn_grade wiring: repurposes the graded proximity scalar, leaves the
    scalar fitness and fail count byte-identical (secondary comparator key only).
"""

import copy
from pathlib import Path

import networkx as nx
import pytest

from homemaker_layout import dom as dom_mod
from homemaker_layout.dom import Node
from homemaker_layout.graph import circulation_connectivity
from homemaker_layout.fitness import Fitness, load_config

HARBOR = Path(__file__).parent.parent / "examples" / "harbor-house"


# --------------------------------------------------------------------------- #
# circulation_connectivity — pure graph contract
# --------------------------------------------------------------------------- #

def _circ(*ids):
    # bare, unlinked nodes: level_of == 0 → is_usable → is_circulation for c/s
    return [Node(type=t) for t in ids]


def test_fully_connected_is_one():
    a, b, c = _circ("C", "C", "S")
    G = nx.Graph([(a, b), (b, c)])
    assert circulation_connectivity(G) == 1.0


def test_two_components_is_half():
    a, b, c, d = _circ("C", "C", "C", "C")
    G = nx.Graph([(a, b), (c, d)])  # two disjoint pairs of 4 circ cells
    assert circulation_connectivity(G) == 0.5


def test_non_circulation_cells_ignored():
    # largest circ component is {a,b} of 3 circ cells → 2/3; the room cells r/s
    # bridging them do NOT count as circulation, so the split stands.
    a, b, lone = _circ("C", "C", "C")
    r1, r2 = Node(type="b1"), Node(type="k1")
    G = nx.Graph([(a, b), (a, r1), (r1, r2), (r2, lone)])
    assert circulation_connectivity(G) == pytest.approx(2 / 3)


def test_no_circulation_is_zero():
    r1, r2 = Node(type="b1"), Node(type="k1")
    G = nx.Graph([(r1, r2)])
    assert circulation_connectivity(G) == 0.0
    assert circulation_connectivity(nx.Graph()) == 0.0


def test_connecting_a_component_raises_the_grade():
    a, b, c, d = _circ("C", "C", "C", "C")
    split = nx.Graph([(a, b), (c, d)])          # 0.5
    joined = nx.Graph([(a, b), (b, c), (c, d)])  # 1.0
    assert circulation_connectivity(joined) > circulation_connectivity(split)


# --------------------------------------------------------------------------- #
# Fitness conn_grade wiring — must not perturb score or fail count
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house example absent")
@pytest.mark.parametrize("name", ["evolved-3M-nols-3.dom", "evolved-3M.dom"])
def test_conn_grade_leaves_score_and_fails_untouched(name):
    conf, cost = load_config(HARBOR)
    conf_cg, _ = load_config(HARBOR, overrides={"conn_grade": True})
    fit, fit_cg = Fitness(conf, cost), Fitness(conf_cg, cost)

    root = dom_mod.load(str(HARBOR / name))
    s_base, f_base = fit.score_with_fails(copy.deepcopy(root))
    s_cg, f_cg, grade = fit_cg.score_with_grade(copy.deepcopy(root))

    assert s_cg == pytest.approx(s_base)
    assert f_cg == f_base
    # grade is the sum of per-level fractions ∈ [0, n_levels]; harbor layouts are
    # partially disconnected, so it is strictly positive and below the level count.
    n_levels = len(dom_mod.levels(dom_mod.load(str(HARBOR / name))))
    assert 0.0 < grade <= n_levels


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house example absent")
def test_more_connected_layout_scores_higher_grade():
    conf_cg, cost = load_config(HARBOR, overrides={"conn_grade": True})
    fit = Fitness(conf_cg, cost)

    def grade_of(name):
        _, _, g = fit.score_with_grade(dom_mod.load(str(HARBOR / name)))
        return g

    # evolved-3M has one fully-connected storey; nols-3 is fragmented on both.
    assert grade_of("evolved-3M.dom") > grade_of("evolved-3M-nols-3.dom")


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house example absent")
def test_conn_grade_off_uses_leaf_grade_not_connectivity():
    # With the flag off, the grade is the §11.4 leaf quality-proximity, which is a
    # different (smaller, here) scalar — the two channels must not collide.
    conf, cost = load_config(HARBOR)
    conf_cg, _ = load_config(HARBOR, overrides={"conn_grade": True})
    root = dom_mod.load(str(HARBOR / "evolved-3M-nols-3.dom"))
    _, _, g_leaf = Fitness(conf, cost).score_with_grade(copy.deepcopy(root))
    _, _, g_conn = Fitness(conf_cg, cost).score_with_grade(copy.deepcopy(root))
    assert g_leaf != g_conn

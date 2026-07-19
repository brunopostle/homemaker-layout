"""Tests for the IN-SEARCH global collapse (homemaker-py-qpk, DESIGN.md §17
follow-on): running Fitness.collapse_global inside every fitness eval instead
of once at finish time.

Covers:
  - default-OFF guarantee + conf-driven knobs (adjacency, iters)
  - _evaluate_full wiring: collapse_global is invoked (with the right kwargs)
    when the flag is on, never when it is off
  - end-to-end effect on a real evolved layout, cross-checked against the
    documented 94g finish-time result (DESIGN.md §17: 15 -> 12 fails on
    evolved-3M-nols-3.dom)
"""

import copy
from pathlib import Path
from unittest.mock import patch

import pytest

from homemaker_layout import dom as dom_mod
from homemaker_layout.dom import Node, _link_subtree
from homemaker_layout.fitness import Fitness, load_config

HARBOR = Path(__file__).parent.parent / "examples" / "harbor-house"


def _two_leaf_root(t_left: str, t_right: str, side: float = 6.0, div: float = 0.4):
    from homemaker_layout import geometry
    geometry.clear_cache()
    root = Node(
        node=[[0, 0], [side, 0], [side, side], [0, side]],
        rotation=0, division=[div, div],
        left=Node(type=t_left), right=Node(type=t_right),
    )
    _link_subtree(root, None, "")
    return root


# --------------------------------------------------------------------------- #
# Defaults + conf-driven knobs
# --------------------------------------------------------------------------- #

def test_collapse_insearch_default_off():
    fit = Fitness()
    assert fit._collapse_insearch is False
    assert fit._collapse_insearch_adjacency is True
    assert fit._collapse_insearch_iters == 3


def test_collapse_insearch_flag_on():
    fit = Fitness(conf={"collapse_insearch": True})
    assert fit._collapse_insearch is True


def test_collapse_insearch_adjacency_knob_off():
    fit = Fitness(conf={"collapse_insearch": True,
                        "collapse_insearch_adjacency": False})
    assert fit._collapse_insearch_adjacency is False


def test_collapse_insearch_iters_knob():
    fit = Fitness(conf={"collapse_insearch": True, "collapse_insearch_iters": 5})
    assert fit._collapse_insearch_iters == 5


# --------------------------------------------------------------------------- #
# _evaluate_full wiring
# --------------------------------------------------------------------------- #

def test_evaluate_full_calls_collapse_global_when_on():
    fit = Fitness(conf={"collapse_insearch": True, "collapse_insearch_iters": 2,
                        "spaces": {"b1": {"size": [16.0, 4.0], "count": 2}}})
    root = _two_leaf_root("b1", "b1")
    with patch.object(Fitness, "collapse_global", wraps=fit.collapse_global) as m:
        fit.score_with_fails(root)
    m.assert_called_once()
    _, kw = m.call_args
    assert kw["adjacency"] is True
    assert kw["objective"] == "threshold"
    assert kw["preserve_public_access"] is True
    assert kw["iters"] == 2


def test_evaluate_full_does_not_call_collapse_global_when_off():
    fit = Fitness(conf={"spaces": {"b1": {"size": [16.0, 4.0], "count": 2}}})
    root = _two_leaf_root("b1", "b1")
    with patch.object(Fitness, "collapse_global", wraps=fit.collapse_global) as m:
        fit.score_with_fails(root)
    m.assert_not_called()


# --------------------------------------------------------------------------- #
# End-to-end: matches the documented 94g finish-time result
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house example absent")
def test_collapse_insearch_reproduces_94g_finish_time_result():
    # DESIGN.md §17: the finish-time collapse takes this layout 15 -> 12 fails.
    # collapse_insearch runs the SAME collapse_global earlier in the SAME
    # pipeline (before Phase-1 checks instead of after the whole search), so it
    # must reach the identical fail count on this fixed-geometry layout.
    conf, cost = load_config(HARBOR)
    conf_ci, _ = load_config(HARBOR, overrides={"collapse_insearch": True})
    fit, fit_ci = Fitness(conf, cost), Fitness(conf_ci, cost)
    root = dom_mod.load(str(HARBOR / "evolved-3M-nols-3.dom"))

    _, f_base = fit.score_with_fails(copy.deepcopy(root))
    _, f_ci = fit_ci.score_with_fails(copy.deepcopy(root))

    assert len(f_base) == 15
    assert len(f_ci) == 12


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house example absent")
def test_collapse_insearch_off_reproduces_baseline():
    conf, cost = load_config(HARBOR)
    fit = Fitness(conf, cost)
    root = dom_mod.load(str(HARBOR / "evolved-3M-nols-3.dom"))
    s1, f1 = fit.score_with_fails(copy.deepcopy(root))
    s2, f2 = Fitness(conf, cost).score_with_fails(copy.deepcopy(root))
    assert s1 == pytest.approx(s2)
    assert f1 == f2

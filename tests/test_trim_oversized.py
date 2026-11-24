"""`trim_oversized`: cut a room built over 2x its target down to target, the
rest outside space (`homemaker-py-s36o.1`, DESIGN.md §39.258).

The §39.257 harbor-house winner is the worked case: a 125.6 m2 plant room
`me1` (target 25) on the ground, the same cell a store `st2` (target 18)
above. Trimmed, it goes from 16 fails to 12 -- the fix today's objective
already prefers and the search never reached. Each positive test has its
control: a room at target is not a candidate, a cut owned below or a
divided cell above blocks the move, and without a scorer it does nothing.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, geometry, operators
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parent.parent
WINNER = REPO / "experiments/results/halving-harbor-rooms/final-seed-20.dom"


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


@pytest.fixture(scope="module")
def fit():
    return Fitness(*load_config(REPO / "examples" / "harbor-house"))


def _load():
    if not WINNER.is_file():
        pytest.skip("no design")
    root = dom.load(str(WINNER))
    dom.link(root)
    geometry.clear_cache()
    return root


def test_candidates_are_the_swollen_plant_room_and_store(fit):
    cands = {(li, p) for li, p, _t in operators.trim_candidates(_load(), fit)}
    assert {(0, "rll"), (1, "rll")} <= cands


def test_control_a_room_at_target_is_not_a_candidate(fit):
    root = _load()
    for li, p, t in operators.trim_candidates(root, fit):
        assert geometry.area(dom.levels(root)[li].by_id(p)) > operators.TRIM_OVER * t
    # and every room under the threshold is absent
    cands = {(li, p) for li, p, _t in operators.trim_candidates(root, fit)}
    for li, lv in enumerate(dom.levels(root)):
        for leaf in lv.leaves():
            t = operators.size_target(fit, leaf)
            if t is not None and geometry.area(leaf) <= operators.TRIM_OVER * t:
                assert (li, leaf.id) not in cands


def test_trim_cuts_the_column_to_target_and_wins(fit):
    root = _load()
    before = fit.score_with_fails(root)
    operators.apply_trim(root, 0, "rll", 25.0, rotation=2)
    dom.link(root)
    geometry.clear_cache()
    lv0, lv1 = dom.levels(root)[:2]
    assert lv0.by_id("rll").divided and lv1.by_id("rll").divided   # inherited above
    assert lv0.by_id("rlll").type == "me1" and lv0.by_id("rllr").type == "O"
    assert lv1.by_id("rlll").type == "st2" and lv1.by_id("rllr").type == "O"
    assert geometry.area(lv0.by_id("rlll")) == pytest.approx(25.0, abs=0.01)
    after = fit.score_with_fails(root)
    assert len(after[1]) == 12 < len(before[1]) == 16
    assert after[0] > 20 * before[0]


def test_control_a_divided_cell_above_blocks_the_move(fit):
    root = _load()
    up = dom.levels(root)[1].by_id("rll")
    up.left, up.right = dom.Node(type="st2"), dom.Node(type="O")
    up.division, up.type = [0.5, 0.5], None
    dom.link(root)
    geometry.clear_cache()
    cands = {(li, p) for li, p, _t in operators.trim_candidates(root, fit)}
    assert (0, "rll") not in cands


def test_control_a_cut_owned_below_blocks_the_move(fit):
    root = _load()
    lo = dom.levels(root)[0].by_id("rll")
    lo.left, lo.right = dom.Node(type="me1"), dom.Node(type="O")
    lo.division, lo.type = [0.5, 0.5], None
    dom.link(root)
    geometry.clear_cache()
    cands = {(li, p) for li, p, _t in operators.trim_candidates(root, fit)}
    assert (1, "rll") not in cands      # st2's cell now spans a cut below


def test_the_move_draws_and_reports(fit):
    child, msg = operators.mutate_trim_oversized(_load(), np.random.default_rng(0), [], fit=fit)
    assert msg.startswith("trim_oversized ") and "noop" not in msg


def test_control_without_fit_is_noop():
    _, msg = operators.mutate_trim_oversized(_load(), np.random.default_rng(0), [])
    assert msg == "trim_oversized noop"


@pytest.mark.parametrize("env, drawn", [("", False), ("1", True)])
def test_default_search_never_draws_it(monkeypatch, env, drawn):
    """Off unless HOMEMAKER_TRIM_OVERSIZED=1. A scorer reaches `mutate` by
    default (merge_circulation and remove_token need one), so the driver's
    zero weight is the only thing keeping the move out; the "1" case is the
    control that the spy can see it at all."""
    from homemaker_layout import driver
    calls = []
    real = operators.mutate_trim_oversized
    monkeypatch.setitem(operators.MUTATIONS, "trim_oversized",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    monkeypatch.setenv("HOMEMAKER_TRIM_OVERSIZED", env)
    # weighted to be drawn nearly every time it is allowed, so the off case
    # shows the driver zeroing it, not luck
    monkeypatch.setitem(driver._MUTATION_WEIGHTS, "trim_oversized", 1000.0)
    corpus = REPO / "examples" / "programme-house"
    driver.search(dom.load(str(corpus / "init.dom")), corpus, budget=600, pop_size=4,
                  child_budget=20, seed_budget=60, seed=3)
    assert bool(calls) is drawn

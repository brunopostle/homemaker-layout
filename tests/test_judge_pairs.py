"""The blind judging kit's pair choice (`homemaker-py-5fje.3`, DESIGN.md §39.206).

`judge_pairs.choose` must ask only pairs the candidate scores order
differently -- a pair they agree on can drop none of them -- and the
negative control is the case where they agree everywhere: no pair at all.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def jp():
    sys.path.insert(0, str(REPO / "experiments"))
    spec = importlib.util.spec_from_file_location(
        "judge_pairs", REPO / "experiments" / "judge_pairs.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _scored(a0, p1, prog="p"):
    return {f"{prog}{i}": dict(programme=prog, scores=dict(A0=x, P1=y))
            for i, (x, y) in enumerate(zip(a0, p1))}


def test_agreeing_candidates_give_no_pairs(jp):
    s = _scored([1, 2, 3, 4], [10, 20, 30, 40])
    assert jp.choose(s, ["A0", "P1"], 30, 2) == []


def test_only_disagreements_are_asked_strongest_first(jp):
    # P1 reverses A0 on designs 0 and 3 only
    s = _scored([1, 2, 3, 4], [40, 20, 30, 10])
    chosen = jp.choose(s, ["A0", "P1"], 30, 9)
    pairs = [(a, b) for _, _, a, b, _ in chosen]
    for _, _, a, b, z in chosen:
        assert z["A0"] * z["P1"] < 0
    assert pairs[0] == ("p0", "p3")
    assert ("p1", "p2") not in pairs


def test_per_design_cap_and_exclusion(jp):
    s = _scored([1, 2, 3, 4, 5], [5, 4, 3, 2, 1])      # every pair disagrees
    chosen = jp.choose(s, ["A0", "P1"], 30, 1)
    used = [d for _, _, a, b, _ in chosen for d in (a, b)]
    assert len(used) == len(set(used))
    ex = frozenset({frozenset(("p0", "p4"))})
    assert ("p0", "p4") not in [(a, b) for _, _, a, b, _ in
                                jp.choose(s, ["A0", "P1"], 30, 1, ex)]


def test_sign_test(jp):
    assert jp.binom_two_sided(5, 10) == 1.0
    assert jp.binom_two_sided(0, 5) == pytest.approx(2 / 32)
    assert jp.binom_two_sided(10, 10) == pytest.approx(2 / 1024)


def _twins(a0_scores, p1_scores, arms=("A0", "P1")):
    """Two twins per design; ``a0_scores[i]`` is design i's (A0 twin, P1 twin)
    under candidate A0, ``p1_scores[i]`` the same under candidate P1."""
    scored, twins = {}, {}
    for i, (x, y) in enumerate(zip(a0_scores, p1_scores)):
        for arm, sa, sp in zip(arms, x, y):
            path = f"d{i}--{arm}"
            scored[path] = dict(programme="p", scores=dict(A0=sa, P1=sp))
            twins[path] = (f"d{i}", arm)
    return scored, twins


def test_twins_agreeing_give_no_pairs(jp):
    # both candidates prefer the A0 twin of every design: nothing to ask
    scored, twins = _twins([(2, 1), (3, 1)], [(5, 4), (5, 1)])
    assert jp.choose_twins(scored, twins, ["A0", "P1"], 30, [("A0", "P1")]) == []


def test_twins_one_pair_per_design_and_only_twins(jp):
    # A0 prefers each A0 twin, P1 each P1 twin: every design disagrees
    scored, twins = _twins([(2, 1), (3, 1), (4, 1)], [(1, 2), (1, 3), (1, 4)])
    chosen = jp.choose_twins(scored, twins, ["A0", "P1"], 30, [("A0", "P1")])
    assert len(chosen) == 3
    for _, _, a, b, z in chosen:
        assert twins[a][0] == twins[b][0]
        assert z["A0"] * z["P1"] < 0


def test_twins_arm_pairs_alternate(jp):
    scored, twins = {}, {}
    for i in range(4):
        for arm, sa, sp in (("A0", 2, 1), ("P1", 1, 2), ("P1u", 1, 3)):
            path = f"d{i}--{arm}"
            scored[path] = dict(programme="p", scores=dict(A0=sa, P1=sp))
            twins[path] = (f"d{i}", arm)
    chosen = jp.choose_twins(scored, twins, ["A0", "P1"], 30, [("A0", "P1"), ("A0", "P1u")])
    arms = sorted(twins[b][1] for _, _, a, b, _ in chosen)
    assert arms == ["P1", "P1", "P1u", "P1u"]

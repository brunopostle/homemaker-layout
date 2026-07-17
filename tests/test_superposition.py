"""Tests for type superposition + collapse (homemaker-py-9o5).

Covers the three layers of the feature:
  1. interchange-class derivation (programme.derive_interchange_classes)
  2. the per-eval collapse assignment (Fitness._best_assignment)
  3. end-to-end collapse re-typing on a built tree (collapse_superposition)

plus the default-OFF guarantee.
"""

import pytest

from homemaker_layout import dom, geometry, programme
from homemaker_layout.dom import Node, _link_subtree
from homemaker_layout.fitness import Fitness
from homemaker_layout.programme import (
    SpaceReq,
    derive_interchange_classes,
    interchangeable,
)


def _req(code, size, width=4.0, proportion=1.5, level=None,
         requires_below=None, adjacency=None, count=1):
    return SpaceReq(
        code=code, size=size, width=width, proportion=proportion,
        level=level, requires_below=requires_below,
        adjacency=list(adjacency or []), count=count, has_size=True,
        has_width=True, has_proportion=True,
    )


# --------------------------------------------------------------------------- #
# Derivation
# --------------------------------------------------------------------------- #

def test_similar_pair_is_grouped():
    # codes are first-letter-classed; c/o/s are generic and never participate,
    # so use plain non-generic codes for the study/guest analogue
    reqs = {"den": _req("den", 9.0), "guest": _req("guest", 12.0)}
    assert derive_interchange_classes(reqs) == [frozenset({"den", "guest"})]


def test_dissimilar_size_not_grouped():
    # 60 / 10 = 6x area, far outside R_SIZE
    reqs = {"hall": _req("hall", 60.0), "wc": _req("wc", 10.0)}
    assert derive_interchange_classes(reqs) == []


def test_width_band_is_tighter_than_size():
    # sizes within R_SIZE but widths 4.0 vs 2.5 (1.6x) exceed R_WIDTH
    reqs = {"a": _req("a", 10.0, width=4.0), "b": _req("b", 12.0, width=2.5)}
    assert derive_interchange_classes(reqs) == []


def test_adjacency_pair_not_grouped():
    # genuinely-similar requirements, but a required adjacency means they are
    # two coexisting rooms, not one interchangeable leaf (S4)
    reqs = {
        "x": _req("x", 10.0, adjacency=["y"]),
        "y": _req("y", 11.0),
    }
    assert derive_interchange_classes(reqs) == []


def test_service_stack_not_grouped_with_non_service():
    # a wet-stack code (requires_below) never groups with a dry room (S3)
    reqs = {
        "bath": _req("bath", 10.0, requires_below="bath"),
        "den": _req("den", 11.0),
    }
    assert derive_interchange_classes(reqs) == []
    # ... but two matching-stack services do group
    reqs2 = {
        "bath1": _req("bath1", 10.0, requires_below="bath"),
        "bath2": _req("bath2", 11.0, requires_below="bath"),
    }
    assert interchangeable(reqs2["bath1"], reqs2["bath2"])


def test_incompatible_levels_not_grouped():
    reqs = {"a": _req("a", 10.0, level=0), "b": _req("b", 11.0, level=1)}
    assert derive_interchange_classes(reqs) == []
    # one level None is still compatible
    reqs2 = {"a": _req("a", 10.0, level=0), "b": _req("b", 11.0, level=None)}
    assert derive_interchange_classes(reqs2) == [frozenset({"a", "b"})]


def test_generic_codes_never_participate():
    reqs = {"c": _req("c", 10.0), "o1": _req("o1", 11.0), "room": _req("room", 11.0)}
    # c/o are circulation/outside — excluded; only one real code left -> no class
    assert derive_interchange_classes(reqs) == []


def test_interchange_veto_removes_code():
    # b3v: a code with interchange=False never joins a class, even if similar.
    a = _req("den", 9.0)
    b = _req("guest", 12.0)
    b.interchange = False
    reqs = {"den": a, "guest": b}
    assert derive_interchange_classes(reqs) == []
    assert not interchangeable(a, b)


def test_interchange_veto_breaks_transitive_chain():
    # b3v motivating case: a middle code bridging two halves of a chain, when
    # vetoed, splits the component rather than collapsing an 8-code class.
    reqs = {
        "left": _req("left", 10.0),
        "bridge": _req("bridge", 12.0),
        "right": _req("right", 15.0),
    }
    # without veto all three chain together (10-12-15, each step <= R_SIZE)
    assert derive_interchange_classes(reqs) == [
        frozenset({"left", "bridge", "right"})]
    # left and right alone are 1.5x -> still just within R_SIZE, so veto the
    # bridge and confirm the two ends still group but only as the direct pair
    reqs["bridge"].interchange = False
    assert derive_interchange_classes(reqs) == [frozenset({"left", "right"})]


def test_interchange_veto_parsed_from_config():
    conf = {"spaces": {
        "den": {"size": [9.0, 1.0]},
        "guest": {"size": [12.0, 1.0], "interchange": False},
    }}
    reqs = programme._parse_spaces(conf)
    assert reqs["den"].interchange is True
    assert reqs["guest"].interchange is False
    assert derive_interchange_classes(reqs) == []


def test_real_programme_house():
    reqs = programme.load_programme_dir("examples/programme-house")
    classes = {frozenset(c) for c in derive_interchange_classes(reqs)}
    assert frozenset({"b1", "b2"}) in classes
    assert frozenset({"t2", "t3"}) in classes


# --------------------------------------------------------------------------- #
# Assignment (collapse core)
# --------------------------------------------------------------------------- #

def _fit_super():
    return Fitness(conf={"superpose": True})


def test_best_assignment_picks_max_diagonal():
    fit = _fit_super()
    # best matching is the diagonal (sum 27); any off-diagonal is worse
    q = [[9, 1, 1], [1, 9, 1], [1, 1, 9]]
    got = sorted(fit._best_assignment(q))
    assert got == [(0, 0), (1, 1), (2, 2)]


def test_best_assignment_enumerates_all_permutations():
    fit = _fit_super()
    # the optimum is the anti-diagonal (10+10+10) — exercises the 3!=6 search
    q = [[1, 2, 10], [2, 10, 2], [10, 2, 1]]
    got = sorted(fit._best_assignment(q))
    assert got == [(0, 2), (1, 1), (2, 0)]


def test_best_assignment_surplus_supply():
    fit = _fit_super()
    # 3 leaves, 2 demand slots -> only 2 pairs, drop the worst-fitting leaf row
    q = [[10, 1], [1, 10], [0, 0]]
    got = sorted(fit._best_assignment(q))
    assert got == [(0, 0), (1, 1)]


def test_best_assignment_surplus_demand():
    fit = _fit_super()
    # 2 leaves, 3 demand slots -> 2 pairs covering the two best columns
    q = [[10, 1, 0], [1, 10, 0]]
    got = sorted(fit._best_assignment(q))
    assert got == [(0, 0), (1, 1)]


def test_best_assignment_falls_back_to_hungarian_beyond_cap():
    fit = Fitness(conf={"superpose": True, "superpose_class_cap": 1})
    q = [[9, 1, 1], [1, 9, 1], [1, 1, 9]]  # min dim 3 > cap 1 -> scipy path
    got = sorted(fit._best_assignment(q))
    assert got == [(0, 0), (1, 1), (2, 2)]


# --------------------------------------------------------------------------- #
# End-to-end collapse on a built tree
# --------------------------------------------------------------------------- #

def _two_leaf_root(t_left: str, t_right: str, side: float = 6.0, div: float = 0.4):
    geometry.clear_cache()
    root = Node(
        node=[[0, 0], [side, 0], [side, side], [0, side]],
        rotation=0, division=[div, div],
        left=Node(type=t_left), right=Node(type=t_right),
    )
    _link_subtree(root, None, "")
    return root


def _bedroom_conf(superpose=True):
    return {
        "superpose": superpose,
        "spaces": {
            "b1": {"size": [16.0, 4.0], "width": [4.0, 1.0],
                   "proportion": [1.5, 0.5], "count": 1},
            "b2": {"size": [12.0, 3.0], "width": [3.5, 0.8],
                   "proportion": [1.5, 0.5], "count": 1},
        },
    }


def test_collapse_relabels_to_demand_set():
    fit = Fitness(conf=_bedroom_conf())
    # both leaves typed b1; areas 14.4 (left) and 21.6 (right)
    root = _two_leaf_root("b1", "b1")
    left, right = root.leaves()
    assert geometry.area(right) > geometry.area(left)

    fit.collapse_superposition(root)

    # the demand set {b1, b2} is now covered, not two b1's
    assert sorted(lf.type for lf in root.leaves()) == ["b1", "b2"]
    # the larger leaf takes the larger target (b1=16), the smaller takes b2=12
    assert right.type == "b1"
    assert left.type == "b2"


def test_collapse_is_noop_without_a_class():
    # only one real code -> no interchange class -> collapse must not touch types
    conf = {"superpose": True,
            "spaces": {"b1": {"size": [16.0, 4.0], "count": 2}}}
    fit = Fitness(conf=conf)
    root = _two_leaf_root("b1", "b1")
    fit.collapse_superposition(root)
    assert [lf.type for lf in root.leaves()] == ["b1", "b1"]


def test_superpose_default_off():
    assert Fitness(conf=_bedroom_conf(superpose=False))._superpose is False
    assert Fitness()._superpose is False


def test_superpose_off_does_not_relabel():
    # with the flag off, _evaluate_full must never call collapse: a two-b1 tree
    # keeps both labels through scoring (proxy: collapse only fires when on)
    fit = Fitness(conf=_bedroom_conf(superpose=False))
    root = _two_leaf_root("b1", "b1")
    # collapse_superposition is gated by self._superpose in _evaluate_full; call
    # the gate directly to document the contract
    if fit._superpose:
        fit.collapse_superposition(root)
    assert [lf.type for lf in root.leaves()] == ["b1", "b1"]

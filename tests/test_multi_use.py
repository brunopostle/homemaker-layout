"""Tests for multi-use leaves as a permanent design goal (homemaker-py-1s3,
DESIGN.md §26 path b).

Covers the four layers of the feature:
  1. co-location pair derivation (programme.derive_colocate_pairs)
  2. the graph resolver + checks (graph.leaf_codes and friends)
  3. quality-term combination (fitness.quality_size/width/proportion)
  4. construction-time fusion (operators._colocate_rooms/_leaf_colocate_from_plan)

plus the default-OFF guarantee at each layer.
"""

from pathlib import Path

import numpy as np
import pytest

from _helpers import with_usage
from homemaker_layout import dom, geometry, graph, operators, programme
from homemaker_layout.dom import Node, _link_subtree
from homemaker_layout.fitness import Fitness, gaussian
from homemaker_layout.programme import SpaceReq, derive_colocate_pairs

HARBOR = Path(__file__).parent.parent / "examples" / "harbor-house"


def _req(code, size, width=4.0, proportion=1.5, level=None,
        requires_below=None, adjacency=None, count=1, co_locate=None):
    return SpaceReq(
        code=code, size=size, width=width, proportion=proportion,
        level=level, requires_below=requires_below,
        adjacency=list(adjacency or []), count=count,
        co_locate=list(co_locate or []), has_size=True,
        has_width=True, has_proportion=True,
    )


# --------------------------------------------------------------------------- #
# Node round-trip (dom.py)
# --------------------------------------------------------------------------- #

def test_co_type_round_trips_through_dom_dump_load():
    root = Node(type="x", co_type="y", rotation=0)
    _link_subtree(root, None, "")
    d = dom._emit(root, True)
    assert d["co_type"] == "y"

    reparsed = dom._parse(d)
    assert reparsed.type == "x"
    assert reparsed.co_type == "y"


def test_co_type_absent_when_unset():
    root = Node(type="x", rotation=0)
    d = dom._emit(root, True)
    assert "co_type" not in d


# --------------------------------------------------------------------------- #
# Derivation (programme.py)
# --------------------------------------------------------------------------- #

def test_declared_pair_passing_interchangeable_is_valid():
    reqs = {"den": _req("den", 9.0, co_locate=["guest"]),
            "guest": _req("guest", 12.0)}
    assert derive_colocate_pairs(reqs) == [frozenset({"den", "guest"})]


def test_declaration_is_symmetric():
    # only the "guest" side declares — still valid, either direction suffices
    reqs = {"den": _req("den", 9.0),
            "guest": _req("guest", 12.0, co_locate=["den"])}
    assert derive_colocate_pairs(reqs) == [frozenset({"den", "guest"})]


def test_declared_pair_failing_size_ratio_is_dropped():
    # 60/10 = 6x, far outside interchangeable()'s R_SIZE — declaring it doesn't help
    reqs = {"hall": _req("hall", 60.0, co_locate=["wc"]), "wc": _req("wc", 10.0)}
    assert derive_colocate_pairs(reqs) == []


def test_declared_pair_with_adjacency_edge_is_dropped():
    # S4: a required-adjacency pair are coexisting rooms, not a fusable pair
    reqs = {
        "x": _req("x", 10.0, adjacency=["y"], co_locate=["y"]),
        "y": _req("y", 11.0),
    }
    assert derive_colocate_pairs(reqs) == []


def test_declared_pair_with_incompatible_level_is_dropped():
    reqs = {
        "x": _req("x", 10.0, level=0, co_locate=["y"]),
        "y": _req("y", 11.0, level=1),
    }
    assert derive_colocate_pairs(reqs) == []


def test_no_transitive_closure_unlike_interchange_classes():
    # p1 declares p2, p2 declares p1+p3; p1-p3 is NEVER inferred (pairs only,
    # no b3v transitive-chain failure mode) — codes avoid a c/o/s initial
    # letter, which interchangeable() treats as generic and excludes (S1)
    reqs = {
        "p1": _req("p1", 10.0, co_locate=["p2"]),
        "p2": _req("p2", 12.0, co_locate=["p1", "p3"]),
        "p3": _req("p3", 15.0),
    }
    pairs = derive_colocate_pairs(reqs)
    assert frozenset({"p1", "p2"}) in pairs
    assert frozenset({"p2", "p3"}) in pairs
    assert frozenset({"p1", "p3"}) not in pairs


def test_undeclared_pair_is_never_valid_even_if_interchangeable():
    # study/guest would pass interchangeable() but neither declares co_locate
    reqs = {"den": _req("den", 9.0), "guest": _req("guest", 12.0)}
    assert derive_colocate_pairs(reqs) == []


def test_co_locate_parsed_from_config():
    conf = {"spaces": with_usage({
        "den": {"size": [9.0, 1.0], "co_locate": ["guest"]},
        "guest": {"size": [12.0, 1.0]},
    })}
    reqs = programme._parse_spaces(conf)
    assert reqs["den"].co_locate == ["guest"]
    assert reqs["guest"].co_locate == []
    assert derive_colocate_pairs(reqs) == [frozenset({"den", "guest"})]


# --------------------------------------------------------------------------- #
# Resolver + checks (graph.py)
# --------------------------------------------------------------------------- #

def _leaf_tree(t: str, co: str | None = None) -> Node:
    geometry.clear_cache()
    return Node(node=[[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0]],
                type=t, co_type=co)


def test_leaf_codes_default_off_returns_scalar_type():
    leaf = Node(type="x", co_type="y")
    assert graph.leaf_codes(leaf) == ["x"]
    assert graph.leaf_codes(leaf, [frozenset({"x", "y"})], multi_use=False) == ["x"]


def test_leaf_codes_multi_use_returns_both_when_pair_valid():
    leaf = Node(type="x", co_type="y")
    pairs = [frozenset({"x", "y"})]
    assert sorted(graph.leaf_codes(leaf, pairs, multi_use=True)) == ["x", "y"]


def test_leaf_codes_drops_stale_co_type_after_retype():
    # mirrors leaf_share's type-guard: a retype invalidates a co_type whose pair
    # no longer includes the leaf's current type
    leaf = Node(type="x", co_type="y")
    pairs = [frozenset({"x", "y"})]
    leaf.type = "z"  # generic retype mutation, co_type never reset
    assert graph.leaf_codes(leaf, pairs, multi_use=True) == ["z"]


def test_check_space_counts_colocated_leaf_covers_both_codes():
    reqs = {"x": _req("x", 10.0), "y": _req("y", 9.0)}
    pairs = [frozenset({"x", "y"})]
    root = _leaf_tree("x", co="y")

    fails, missing = graph.check_space_counts(
        root, reqs, multi_use=True, colocate_pairs=pairs)
    assert fails == [] and missing == []


def test_check_space_counts_default_off_leaves_second_code_missing():
    reqs = {"x": _req("x", 10.0), "y": _req("y", 9.0)}
    pairs = [frozenset({"x", "y"})]
    root = _leaf_tree("x", co="y")

    _fails, missing = graph.check_space_counts(root, reqs)  # multi_use default False
    assert missing == ["y"]
    _fails, missing = graph.check_space_counts(
        root, reqs, multi_use=True, colocate_pairs=[])  # pair not declared valid
    assert missing == ["y"]


def test_check_level_constraints_honours_co_type_leaf():
    reqs = {"x": _req("x", 10.0, level=0), "y": _req("y", 9.0, level=0)}
    pairs = [frozenset({"x", "y"})]
    root = _leaf_tree("x", co="y")
    _link_subtree(root, None, "")

    assert graph.check_level_constraints(
        root, reqs, missing=[], multi_use=True, colocate_pairs=pairs) == []


def test_check_vertical_connectivity_honours_co_type_leaf():
    lower = _leaf_tree("below")
    upper = _leaf_tree("x", co="y")
    lower.above = upper
    dom.link(lower)

    reqs = {"x": _req("x", 10.0, requires_below="below"),
            "y": _req("y", 9.0, requires_below="below")}
    pairs = [frozenset({"x", "y"})]

    fails = graph.check_vertical_connectivity(
        lower, reqs, missing=[], multi_use=True, colocate_pairs=pairs)
    assert fails == []


def test_has_adjacency_sees_co_type_leaf_only_under_multi_use():
    geometry.clear_cache()
    left = Node(type="x", co_type="y")
    root = Node(
        node=[[0.0, 0.0], [6.0, 0.0], [6.0, 6.0], [0.0, 6.0]],
        rotation=0, division=[0.4, 0.4],
        left=left, right=Node(type="z"),
    )
    _link_subtree(root, None, "")
    G = graph.build_graphs(root, 1.2)[0]
    right = root.right
    pairs = [frozenset({"x", "y"})]

    assert graph.has_adjacency(right, "y", G, pairs, multi_use=True) is True
    assert graph.has_adjacency(right, "y", G, pairs, multi_use=False) is False
    assert graph.has_adjacency(right, "y", G, [], multi_use=True) is False  # undeclared


# --------------------------------------------------------------------------- #
# Quality-term combination (fitness.py)
# --------------------------------------------------------------------------- #

def _leaf(type_: str, size: float = 4.0, co_type: str | None = None) -> Node:
    geometry.clear_cache()
    return Node(
        node=[[0.0, 0.0], [size, 0.0], [size, size], [0.0, size]],
        type=type_, co_type=co_type,
    )


def _rect_leaf(type_: str, width: float, length: float,
              co_type: str | None = None) -> Node:
    geometry.clear_cache()
    return Node(
        node=[[0.0, 0.0], [length, 0.0], [length, width], [0.0, width]],
        type=type_, co_type=co_type,
    )


def _multi_use_conf(pair=True):
    # x/y stay within interchangeable()'s S2 bounds (R_SIZE=1.5, R_WIDTH=1.3,
    # R_PROP=1.5) so a declared co_locate is actually valid.
    spaces = {
        "x": {"size": [10.0, 2.0], "width": [3.0, 0.5], "proportion": [1.2, 0.5],
              "count": 1},
        "y": {"size": [7.0, 1.0], "width": [3.8, 0.2], "proportion": [1.5, 0.1],
              "count": 1},
    }
    if pair:
        spaces["x"]["co_locate"] = ["y"]
    return {"multi_use": True, "spaces": with_usage(spaces)}


def test_quality_size_combines_both_codes_area_additively():
    fit = Fitness(conf=_multi_use_conf())
    leaf = _leaf("x", size=4.0, co_type="y")  # area 16
    # target 10+7=17, sigma 2+1=3
    assert fit.quality_size(leaf) == pytest.approx(gaussian(16.0, 1.0, 17.0, 3.0))


def test_gaussian_product_is_intermediate_and_narrower():
    from homemaker_layout.fitness import _gaussian_product

    # equal sigmas -> target is the plain average, sigma shrinks by sqrt(2)
    t, s = _gaussian_product(3.0, 0.5, 4.0, 0.5)
    assert t == pytest.approx(3.5)
    assert s == pytest.approx(0.5 / (2 ** 0.5))
    assert s < 0.5

    # unequal sigmas -> target is pulled toward the more confident (smaller
    # sigma) side, and stays strictly between the two targets (never the max)
    t2, s2 = _gaussian_product(3.0, 0.5, 3.8, 0.2)
    assert 3.0 < t2 < 3.8
    assert t2 > 3.4  # pulled toward the tighter-sigma target (3.8)
    assert s2 < min(0.5, 0.2)


def test_clipped_gaussian_flat_past_target_and_decays_short_of_it():
    from homemaker_layout.fitness import _clipped_gaussian

    assert _clipped_gaussian(5.0, 3.0, 0.5, "above") == 1.0
    assert _clipped_gaussian(3.0, 3.0, 0.5, "above") == pytest.approx(
        gaussian(3.0, 1.0, 3.0, 0.5))
    assert _clipped_gaussian(1.0, 3.0, 0.5, "below") == 1.0
    assert _clipped_gaussian(5.0, 3.0, 0.5, "below") == pytest.approx(
        gaussian(5.0, 1.0, 3.0, 0.5))


def test_quality_width_and_proportion_use_precision_weighted_combination():
    from homemaker_layout.fitness import _gaussian_product

    fit = Fitness(conf=_multi_use_conf())
    # elongated rectangle so neither the width nor proportion "already fine"
    # early-return short-circuits before the combination runs
    leaf = _rect_leaf("x", width=2.0, length=10.0, co_type="y")
    wt, ws = _gaussian_product(3.0, 0.5, 3.8, 0.2)
    assert fit.quality_width(leaf) == pytest.approx(
        gaussian(geometry.length_narrowest(leaf), 1.0, wt, ws))
    pt, ps = _gaussian_product(1.2, 0.5, 1.5, 0.1)
    assert fit.quality_proportion(leaf) == pytest.approx(
        gaussian(geometry.aspect(leaf), 1.0, pt, ps))


def test_quality_size_ignores_co_type_when_pair_not_declared():
    fit = Fitness(conf=_multi_use_conf(pair=False))
    leaf = _leaf("x", size=4.0, co_type="y")  # area 16, but pair never declared
    assert fit.quality_size(leaf) == pytest.approx(gaussian(16.0, 1.0, 10.0, 2.0))


def test_multi_use_default_off_ignores_co_type():
    conf = _multi_use_conf()
    conf["multi_use"] = False
    fit = Fitness(conf=conf)
    assert fit._multi_use is False
    leaf = _leaf("x", size=4.0, co_type="y")
    assert fit.quality_size(leaf) == pytest.approx(gaussian(16.0, 1.0, 10.0, 2.0))


def test_leaf_never_combines_share_and_co_type():
    # construction never stamps both; if it somehow happened, share wins (k>1
    # takes precedence over co_type in quality_size)
    conf = _multi_use_conf()
    conf["leaf_sharing"] = True
    fit = Fitness(conf=conf)
    leaf = _leaf("x", size=4.0, co_type="y")
    leaf.share, leaf.share_type = 2, "x"
    # k=2 -> target 20, sigma 4; co_type ignored
    assert fit.quality_size(leaf) == pytest.approx(gaussian(16.0, 1.0, 20.0, 4.0))


def test_load_config_multi_use_override_merges_last(tmp_path):
    import yaml

    from homemaker_layout.fitness import load_config

    (tmp_path / "patterns.config").write_text(
        yaml.safe_dump({"spaces": with_usage({"x": {"size": [10.0, 1.0]}})}))

    conf, _ = load_config(tmp_path)
    assert "multi_use" not in conf

    conf2, _ = load_config(tmp_path, overrides={"multi_use": True})
    assert conf2["multi_use"] is True
    assert conf2["spaces"]["x"] == with_usage({"x": {"size": [10.0, 1.0]}})["x"]


# --------------------------------------------------------------------------- #
# Construction-time fusion (operators.py)
# --------------------------------------------------------------------------- #

def test_colocate_rooms_fuses_available_pair():
    rooms = ["x", "y", "z"]
    pairs = [frozenset({"x", "y"})]
    reduced, plan = operators._colocate_rooms(rooms, pairs, np.random.default_rng(0))

    assert len(plan) == 1
    (primary, secondaries), = plan.items()
    assert secondaries == [({"x", "y"} - {primary}).pop()]
    assert sorted(reduced) == sorted(["z", primary])


def test_colocate_rooms_leaves_unpaired_code_untouched():
    rooms = ["x", "z"]  # no 'y' available to pair with
    pairs = [frozenset({"x", "y"})]
    reduced, plan = operators._colocate_rooms(rooms, pairs, np.random.default_rng(0))
    assert sorted(reduced) == sorted(rooms)
    assert plan == {}


def test_colocate_rooms_fuses_every_available_instance():
    rooms = ["x", "x", "y", "y"]
    pairs = [frozenset({"x", "y"})]
    reduced, plan = operators._colocate_rooms(rooms, pairs, np.random.default_rng(1))
    assert len(reduced) == 2
    assert sum(len(v) for v in plan.values()) == 2


def test_colocate_rooms_no_pairs_is_identity():
    rooms = ["x", "y", "z"]
    reduced, plan = operators._colocate_rooms(rooms, [], np.random.default_rng(0))
    assert sorted(reduced) == sorted(rooms)
    assert plan == {}


def test_leaf_colocate_from_plan_matches_biggest_target_to_biggest_leaf():
    geometry.clear_cache()
    root = Node(
        node=[[0.0, 0.0], [6.0, 0.0], [6.0, 6.0], [0.0, 6.0]],
        rotation=0, division=[0.7, 0.7],
        left=Node(type="x"), right=Node(type="x"),
    )
    _link_subtree(root, None, "")
    reqs = {"big": _req("big", 8.0), "small": _req("small", 2.0)}
    plan = {"x": ["small", "big"]}  # deliberately unsorted

    leaf_co = operators._leaf_colocate_from_plan(root, plan, reqs)

    left, right = root.left, root.right
    assert geometry.area(left) > geometry.area(right)
    assert left.co_type == "big"
    assert right.co_type == "small"
    assert leaf_co[left] == "big" and leaf_co[right] == "small"


def test_constructive_topology_multi_use_fuses_leaves_and_covers_both_codes():
    reqs = {
        "x": _req("x", 10.0, co_locate=["y"]),
        "y": _req("y", 8.0),
        "z": _req("z", 6.0),
        "C": _req("C", 0.0),
        "O": _req("O", 0.0),
    }
    for code in ("C", "O"):
        reqs[code].has_size = False
    types = sorted(reqs)
    seed = Node(node=[[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]],
               rotation=0, wall_outer=0.25, wall_inner=0.08)

    plain = operators.constructive_topology(
        seed, reqs, np.random.default_rng(0), types)
    fused = operators.constructive_topology(
        seed, reqs, np.random.default_rng(0), types, multi_use=True)

    n_plain = sum(len(lvl.leaves()) for lvl in dom.levels(plain))
    n_fused = sum(len(lvl.leaves()) for lvl in dom.levels(fused))
    assert n_fused < n_plain

    pairs = derive_colocate_pairs(reqs)
    _fails, missing = graph.check_space_counts(
        fused, reqs, multi_use=True, colocate_pairs=pairs)
    assert missing == []

    # default-OFF parity: the plain seed never stamps a co_type
    assert all(lf.co_type is None for lvl in dom.levels(plain) for lf in lvl.leaves())


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_multi_use_default_off_reproduces_plain_construction():
    # multi_use defaults False and no programme declares co_locate, so
    # constructive_topology(multi_use left at default) must be untouched.
    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    seed = dom.load(str(HARBOR / "init.dom"))
    a = operators.constructive_topology(seed, reqs, np.random.default_rng(0), types)
    b = operators.constructive_topology(seed, reqs, np.random.default_rng(0), types,
                                        multi_use=False)
    assert dom.dumps(a) == dom.dumps(b)

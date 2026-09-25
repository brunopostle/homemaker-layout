"""The 2026-09-25 rulings on what counts as a usable space (DESIGN.md §39.58).

Four invariants of the objective, not properties of any one layout:

* `homemaker-py-k7c` — `adjacency: [o]` means a TERRACE. A void is a hole, and
  the wall exposure it does provide is credited once, by crinkliness.
* `homemaker-py-v8n` — a void costs nothing and earns nothing. The 10/m2
  unsupported rate prices a ground-floor yard, which is a different thing.
* `homemaker-py-w2k` — every indoor|outdoor wall is an external wall. This one
  already held; it is here because it is exactly what a careless k7c fix would
  break, the two being one `is_outside` test apart.
* `homemaker-py-m3s` — the internal-area rule is a CAP, not a floor.

Each is cheap to flip back by accident and expensive to notice in a six-hour
run, so they are asserted here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from homemaker_layout import dom as dom_mod, geometry, graph as graph_mod
from homemaker_layout.dom import Node
from homemaker_layout.fitness import (
    CONF_DEFAULTS, Fitness, _height, load_config)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CORPUS = ["harbor-house", "maple-court", "health-centre", "programme-house"]
needs_examples = pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(),
                                    reason="examples absent")


def _two_storey(upper_outside_over: str) -> Node:
    """A 2x1 plot: ground is `k1` | `O`, upper is `l1` plus one outside leaf.

    ``upper_outside_over`` places that outside leaf over the indoor half
    ("indoor" -> a supported terrace) or over the outdoor half ("outdoor" -> an
    unsupported void).
    """
    corners = [[0, 0], [8, 0], [8, 4], [0, 4]]
    ground = Node(node=[list(c) for c in corners], height=3.0, elevation=0.0,
                  division=[0.5, 0.5], rotation=0,
                  left=Node(type="k1"), right=Node(type="O"))
    if upper_outside_over == "indoor":
        upper = Node(node=[list(c) for c in corners], height=3.0, elevation=3.0,
                     division=[0.5, 0.5], rotation=0,
                     left=Node(type="O"), right=Node(type="l1"))
    else:
        upper = Node(node=[list(c) for c in corners], height=3.0, elevation=3.0,
                     division=[0.5, 0.5], rotation=0,
                     left=Node(type="l1"), right=Node(type="O"))
    ground.above = upper
    dom_mod.link(ground)
    geometry.clear_cache()
    return ground


def _upper_outside_leaf(root: Node) -> Node:
    upper = dom_mod.levels(root)[1]
    return next(lf for lf in upper.leaves() if dom_mod.is_outside(lf))


def _upper_room(root: Node) -> Node:
    upper = dom_mod.levels(root)[1]
    return next(lf for lf in upper.leaves() if not dom_mod.is_outside(lf))


# --------------------------------------------------------------------------- #
# k7c — a void does not satisfy an outdoor adjacency requirement
# --------------------------------------------------------------------------- #
def test_supported_terrace_satisfies_outdoor_adjacency():
    root = _two_storey("indoor")
    room, terrace = _upper_room(root), _upper_outside_leaf(root)
    assert dom_mod.is_usable(terrace), "fixture: this one should be supported"
    G = graph_mod.build_graphs(root, 1.2)[1]
    assert graph_mod.has_adjacency(room, "o", G) is True


def test_void_does_not_satisfy_outdoor_adjacency():
    """The bug: a hole in the floor was being read as a balcony."""
    root = _two_storey("outdoor")
    room, void = _upper_room(root), _upper_outside_leaf(root)
    assert not dom_mod.is_usable(void), "fixture: this one should be a void"
    G = graph_mod.build_graphs(root, 1.2)[1]
    assert graph_mod.has_adjacency(room, "o", G) is False


def test_indoor_adjacency_is_unaffected_by_the_usability_filter():
    """`is_usable` is True for every indoor leaf, so nothing else moved."""
    root = _two_storey("outdoor")
    void = _upper_outside_leaf(root)
    G = graph_mod.build_graphs(root, 1.2)[1]
    assert graph_mod.has_adjacency(void, "l", G) is True


# --------------------------------------------------------------------------- #
# v8n — a void costs nothing and earns nothing
# --------------------------------------------------------------------------- #
def _fit() -> Fitness:
    return Fitness({}, {})


def test_void_costs_nothing():
    void = _upper_outside_leaf(_two_storey("outdoor"))
    fit = _fit()
    assert fit.leaf_cost(void) == 0.0
    assert fit.outside_edge_cost(void) == 0.0


def test_void_earns_nothing():
    void = _upper_outside_leaf(_two_storey("outdoor"))
    assert _fit().value_rate(void) == 0.0


def test_supported_terrace_still_costs_and_earns():
    """v8n zeroes a hole, not outdoor space in general."""
    terrace = _upper_outside_leaf(_two_storey("indoor"))
    fit = _fit()
    assert fit.leaf_cost(terrace) > 0.0
    assert fit.value_rate(terrace) > 0.0


def test_ground_floor_yard_keeps_the_unsupported_rate():
    """The 10/m2 rate is what it was written for and must survive."""
    # the "outdoor" variant puts an outside leaf over the yard, so the yard is
    # uncovered -- a covered one draws `outside_covered` and tests nothing here
    root = _two_storey("outdoor")
    yard = next(lf for lf in dom_mod.levels(root)[0].leaves()
                if dom_mod.is_outside(lf))
    assert not dom_mod.is_covered(yard), "fixture: the yard must be open to the sky"
    fit = _fit()
    assert dom_mod.level_of(yard) == 0
    assert fit.leaf_cost(yard) == pytest.approx(
        fit.cost("outside") * geometry.area(yard))


# --------------------------------------------------------------------------- #
# w2k — every indoor|outdoor wall is an external wall
# --------------------------------------------------------------------------- #
@needs_examples
def test_indoor_outdoor_wall_is_external_across_the_corpus():
    """Including indoor|void and indoor|sahn.

    k7c stops a void satisfying an adjacency requirement; it must NOT stop the
    wall against that void being charged as external. The two live in separate
    graph builds (`graph_base_pre` for adjacency, `graph_base` for costing)
    precisely so that one cannot reach the other.
    """
    checked = 0
    for name in CORPUS:
        d = EXAMPLES / name
        conf, cost = load_config(d)
        fit = Fitness(conf, cost)
        exterior = fit.cost("exterior_wall")
        interior = fit.cost("interior_wall")
        assert exterior != interior, "fixture: the rates must differ to test this"
        for p in sorted(d.glob("coldstart-*-500000-s*.dom")):
            root = dom_mod.load(str(p))
            geometry.clear_cache()
            for G in graph_mod.build_graphs(root, conf.get("door_width") or 1.2):
                for a, b in G.edges():
                    a_out, b_out = dom_mod.is_outside(a), dom_mod.is_outside(b)
                    if a_out == b_out:
                        continue
                    width = G[a][b]["width"]
                    if width <= 0:
                        continue
                    expected = exterior * width * _height(a)
                    assert expected > 0, "fixture: a zero expectation tests nothing"
                    assert fit.edge_cost(G, a, b) == pytest.approx(expected), (
                        f"{name} {p.name}: {a.type}|{b.type} not at the external rate")
                    checked += 1
    assert checked > 0, "no indoor|outdoor walls found — the test proved nothing"


# --------------------------------------------------------------------------- #
# m3s — the internal-area rule is a cap, not a floor
# --------------------------------------------------------------------------- #
def test_area_cap_default_is_the_owners_twenty_percent():
    assert CONF_DEFAULTS["area_cap"] == 1.2


@needs_examples
def test_undersized_building_is_not_penalised_by_the_area_rule():
    """The floor is gone. A building whose rooms fall short is the per-room
    `quality_size` checks' business, where maldistribution is visible; a sum
    cannot see it (§39.57: 101% of the required area with eight rooms failing).
    """
    d = EXAMPLES / "programme-house"
    conf, cost = load_config(d)
    fit = Fitness(conf, cost)
    room_area = sum(r.size * r.count for r in (fit._programme or {}).values()
                    if not dom_mod.is_generic(r.code) and r.size > 0)
    tracking = {"_failures": [], "stair_fit": []}

    tiny = room_area * 0.1
    orig = Fitness._area_internal
    try:
        Fitness._area_internal = staticmethod(lambda root: tiny)
        root = dom_mod.load(str(sorted(d.glob("coldstart-*-500000-s*.dom"))[0]))
        geometry.clear_cache()
        factor = fit.evaluate_building(root, tracking)
    finally:
        Fitness._area_internal = orig
    assert "excess internal area" not in tracking["_failures"]
    assert factor > 0.0


@needs_examples
def test_oversized_building_is_penalised_and_registers_a_fail():
    """And it registers — the old block had no `fail()` call at all, so a
    building 1.8x over the programme took a silent x0.004.
    """
    d = EXAMPLES / "programme-house"
    conf, cost = load_config(d)
    fit = Fitness(conf, cost)
    room_area = sum(r.size * r.count for r in (fit._programme or {}).values()
                    if not dom_mod.is_generic(r.code) and r.size > 0)
    tracking = {"_failures": [], "stair_fit": []}
    huge = room_area * 2.0          # well past the 1.59x fail threshold
    orig = Fitness._area_internal
    try:
        Fitness._area_internal = staticmethod(lambda root: huge)
        root = dom_mod.load(str(sorted(d.glob("coldstart-*-500000-s*.dom"))[0]))
        geometry.clear_cache()
        fit.evaluate_building(root, tracking)
    finally:
        Fitness._area_internal = orig
    assert "excess internal area" in tracking["_failures"]


def test_excess_internal_area_has_a_fail_tier():
    """`classify_fail_tier` raises on an unrecognised string, so a new fail
    that skips the marker tuples breaks every consumer downstream."""
    from homemaker_layout.fitness import classify_fail_tier
    assert classify_fail_tier("excess internal area") == "soft"

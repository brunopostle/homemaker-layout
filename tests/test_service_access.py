"""A utility room or a workshop need not be on circulation, and one room nobody
can reach is one storey fail, not two (owner's rulings, DESIGN.md §39.138).

    "A utility room can be reached from another non sleeping room or from an
    outside space, as can a workshop. I guess one unreachable room is a single
    fail."                                               -- owner, 2026-10-12

The design scored is a copy of the owner's hand drawing with the brief it was
classified under (tests/data/service-access): its plant room opens off an
office and onto the garden, its utilities closet off a store.
"""

import copy
from pathlib import Path

import networkx as nx
import pytest

from homemaker_layout import dom, geometry, graph, programme
from homemaker_layout.dom import Node
from homemaker_layout.fitness import Fitness, load_config

DATA = Path(__file__).parent / "data" / "service-access"


@pytest.fixture
def orthogonal(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _fails():
    fit = Fitness(*load_config(DATA))
    root = dom.load(str(DATA / "hand2a.dom"))
    dom.link(root)
    geometry.clear_cache()
    return fit.score_with_fails(copy.deepcopy(root))[1]


def test_a_plant_room_off_a_store_or_the_garden_is_reached(orthogonal):
    fails = _fails()
    assert not [f for f in fails if "not adjacent to c" in f]
    assert not [f for f in fails if f.endswith(" access")]
    assert not [f for f in fails if "inaccessible usable space" in f]


def test_without_the_ruling_the_same_rooms_fail_and_the_storey_fails_once(
        orthogonal, monkeypatch):
    """The negative control, and the second ruling: with no usage allowed the
    extra way in, both rooms fail as they did -- and the storey the closet
    cuts off is reported once, where it used to be reported twice."""
    monkeypatch.setattr(programme, "SERVICE_USAGES", ())
    fails = _fails()
    assert "0/llrrrrr (me1) not adjacent to c" in fails
    assert "1/llrrrrr (ut1) not adjacent to c" in fails
    assert "0/llrrrrr access" in fails and "1/llrrrrr access" in fails
    assert fails.count("1 inaccessible usable space") == 1


USAGES = {"st": "utility", "ut": "utility", "ws": "workshop", "bed": "bedroom",
          "lv": "living", "wc": "toilet"}


@pytest.mark.parametrize("code, served", [
    ("C", True), ("E", True), ("lv", True), ("st", True), ("wc", True),
    ("ws", True), ("bed", False), ("", False),
])
def test_what_serves_a_utility_room(code, served):
    assert graph.serves_utility(Node(type=code), USAGES) is served


def test_outdoor_space_serves_only_where_it_can_be_stood_in(monkeypatch):
    yard = Node(type="O")
    monkeypatch.setattr(dom, "is_usable", lambda n: True)
    assert graph.serves_utility(yard, USAGES)
    monkeypatch.setattr(dom, "is_usable", lambda n: False)
    assert not graph.serves_utility(yard, USAGES)


def _chain(*codes):
    nodes = [Node(type=c) for c in codes]
    G = nx.Graph()
    G.add_nodes_from(nodes)
    for a, b in zip(nodes, nodes[1:]):
        G.add_edge(a, b, weight=1.0, width=2.0)
    return G


@pytest.mark.parametrize("codes, connected", [
    (("C", "st", "ut"), True),      # a closet off a store off the corridor
    (("C", "lv", "ws"), True),      # a workshop off a living room
    (("C", "bed", "ut"), False),    # ...but never through a bedroom
    (("C", "bed", "ws"), False),
    (("C", "st", "bed"), False),    # and a bedroom gains nothing by it
])
def test_a_storey_is_connected_through_the_one_door_kept(codes, connected, monkeypatch):
    monkeypatch.setattr(dom, "is_usable", lambda n: True)
    assert graph.has_circulation(_chain(*codes), USAGES) is connected


def test_the_door_kept_is_the_rulings_and_not_an_accident(monkeypatch):
    monkeypatch.setattr(dom, "is_usable", lambda n: True)
    monkeypatch.setattr(programme, "SERVICE_USAGES", ())
    assert graph.has_circulation(_chain("C", "st", "ut"), USAGES) is False

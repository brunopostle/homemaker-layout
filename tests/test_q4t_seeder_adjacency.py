"""The seeders must ask the adjacency question the scorer asks (§39.64, q4t).

`graph.has_adjacency` has required a USABLE outside neighbour since `k7c`
(§39.58): an unsupported void above ground is a hole, not a terrace. Three
seeders decided the same question their own way --

* `cpsat`, through the `context_types` its callers hand it (a set of type
  STRINGS, so an unsupported void arrives as a plain ``"O"`` and is credited as
  a constant-1 satisfaction);
* the greedy room placement in `operators._assign_adjacency_aware`;
* `operators._beam_place_rooms`.

-- and so optimised a relation the scorer does not check. Worse seeds, not
wrong scores, which is why q4t was filed P2.

This is the second time the same drift has hit the same code: the docstring of
`test_assign_cpsat_beats_greedy_on_a_namespace_clean_programme` records
`cpsat._matches` matching by raw prefix after `graph.has_adjacency` had been
tightened. The answer both times is one shared definition
(`graph.code_matches_requirement` then, `graph.satisfies_as_outside` now), so
the tests that matter here are the ones that would fail if someone wrote a
second copy of the rule -- not the ones that check today's arithmetic.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, geometry, graph as graph_mod, operators
from homemaker_layout.dom import Node
from homemaker_layout.programme import SpaceReq

CORNERS = [[0, 0], [16, 0], [16, 8], [0, 8]]


def _level(elevation: float, left: Node, right: Node) -> Node:
    return Node(node=[list(c) for c in CORNERS], height=3.0, elevation=elevation,
                division=[0.5, 0.5], rotation=0, left=left, right=right)


def _two_storey(ground_left: str, upper_left: str) -> Node:
    """Ground ``<ground_left>`` | ``k1``; upper ``<upper_left>`` | ``r1``.

    With ``ground_left="O"`` the upper-left leaf sits over a yard and is
    unsupported; with ``"k1"`` it sits on building and is a real terrace.
    """
    ground = _level(0.0, Node(type=ground_left), Node(type="k1"))
    ground.above = _level(3.0, Node(type=upper_left), Node(type="r1"))
    dom.link(ground)
    geometry.clear_cache()
    return ground


# --------------------------------------------------------------------------- #
# the shared predicate itself
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("ground_left,usable", [("O", False), ("k1", True)])
def test_satisfies_as_outside_tracks_usability_above_ground(ground_left, usable):
    root = _two_storey(ground_left, "O")
    terrace = dom.levels(root)[1].left
    assert dom.is_outside(terrace)
    assert dom.is_usable(terrace) is usable
    assert graph_mod.satisfies_as_outside(terrace) is usable


def test_satisfies_as_outside_never_rejects_an_indoor_neighbour():
    """k7c narrows the OUTSIDE case alone. A seeder that filtered on
    `is_usable` directly would also drop indoor rooms that happen to sit over a
    yard, which is why the shared predicate exists rather than a bare
    usability test. Ground ``O`` | ``k1``, upper ``r1`` | ``O`` puts the room
    over the yard."""
    ground = _level(0.0, Node(type="O"), Node(type="k1"))
    ground.above = _level(3.0, Node(type="r1"), Node(type="O"))
    dom.link(ground)
    geometry.clear_cache()
    room = dom.levels(ground)[1].left
    assert not dom.is_outside(room)
    assert not dom.is_supported(room), "fixture must put the room over the yard"
    assert graph_mod.satisfies_as_outside(room) is True


def test_ground_floor_outside_always_counts():
    root = _two_storey("O", "O")
    yard = dom.levels(root)[0].left
    assert graph_mod.satisfies_as_outside(yard) is True


# --------------------------------------------------------------------------- #
# the seam the bug lived in: what the seeders hand their solver
# --------------------------------------------------------------------------- #
def _context_types_for_upper_room(root: Node) -> set[str]:
    """The `context_types` comprehension `operators`' three cpsat callers use.

    This MIRRORS production rather than calling it -- the callers build the dict
    inline and do not return it -- so on its own it would only prove the rule is
    self-consistent. What ties it to production is
    `test_the_seeders_import_the_shared_predicate` (the filter is present at
    every site) and the end-to-end seeder tests below (the behaviour is right
    whichever solver runs). Stated because a test that quietly re-implements
    what it checks is how §39.20 happened.
    """
    lvl = dom.levels(root)[1]
    room = lvl.right
    G = geometry.leaf_graph(lvl)
    room_set = {room}
    return {nb.type for nb in G.neighbors(room)
            if nb.type and nb not in room_set
            and graph_mod.satisfies_as_outside(nb)}


@pytest.mark.parametrize("ground_left,expected", [("O", set()), ("k1", {"O"})])
def test_context_handed_to_the_solver_matches_what_the_scorer_credits(
        ground_left, expected):
    """The whole bug in one assertion: the void is dropped, the terrace is
    kept, and both agree with `has_adjacency`."""
    root = _two_storey(ground_left, "O")
    lvl = dom.levels(root)[1]
    G = geometry.leaf_graph(lvl)
    assert G.has_edge(lvl.left, lvl.right), "fixture must make the two adjacent"

    scorer_says = graph_mod.has_adjacency(lvl.right, "o", G)
    assert _context_types_for_upper_room(root) == expected
    assert scorer_says is bool(expected)


# --------------------------------------------------------------------------- #
# end to end
# --------------------------------------------------------------------------- #
def _settled_wing() -> Node:
    """Upper storey of four leaves in a row: ``slot | void | terrace | slot``.

    The left half sits over a ground-floor yard, so the ``O`` there is a void;
    the right half sits over building, so its ``O`` is a real terrace. The two
    room slots are the outer leaves, so the left one touches ONLY the void and
    the right one ONLY the terrace -- which is the discrimination the seeders
    have to make.

    Built for `_cpsat_relabel_settled`, not `_assign_adjacency_aware`: the
    latter places its own circulation spine and its own ``O`` leaves, so it
    overwrites any void a fixture pre-places and cannot be shown this case.
    """
    ground = _level(0.0, Node(type="O"), Node(type="k1"))
    ground.above = _level(
        3.0,
        Node(division=[0.5, 0.5], rotation=0,
             left=Node(type="r1"), right=Node(type="O")),
        Node(division=[0.5, 0.5], rotation=0,
             left=Node(type="O"), right=Node(type="r2")))
    dom.link(ground)
    geometry.clear_cache()
    return ground


def test_the_settled_wing_isolates_one_void_and_one_terrace():
    root = _settled_wing()
    lvl = dom.levels(root)[1]
    slot_by_void, void, terrace, slot_by_terrace = (
        lvl.left.left, lvl.left.right, lvl.right.left, lvl.right.right)
    assert (dom.is_outside(void), dom.is_usable(void)) == (True, False)
    assert (dom.is_outside(terrace), dom.is_usable(terrace)) == (True, True)
    G = geometry.leaf_graph(lvl)
    assert set(G.neighbors(slot_by_void)) == {void}
    assert set(G.neighbors(slot_by_terrace)) == {terrace}


def test_relabelling_puts_the_o_requiring_room_where_the_scorer_credits_it():
    """A property test, and honest about it: the fix only REMOVES credit, so
    it turns a strict preference for the void into a tie rather than into a
    strict preference the other way. Both arms pass on this fixture. It guards
    the outcome against future regressions; what proves the fix bites is
    `test_context_handed_to_the_solver_matches_what_the_scorer_credits` above
    and `test_the_narrowing_reaches_a_real_corpus_seed` below.
    """
    root = _settled_wing()
    lvl = dom.levels(root)[1]
    reqs = {"r1": SpaceReq(code="r1", adjacency=["o"]),
            "r2": SpaceReq(code="r2")}
    operators._cpsat_relabel_settled(lvl, reqs)

    G = geometry.leaf_graph(lvl)
    r1 = next((lf for lf in lvl.leaves() if lf.type == "r1"), None)
    assert r1 is not None, "the relabel dropped the o-requiring room entirely"
    assert graph_mod.has_adjacency(r1, "o", G), (
        "the o-requiring room was left beside the void while a terrace slot "
        "was available")


CORPUS = Path(__file__).resolve().parent.parent / "examples" / "maple-court"


@pytest.mark.skipif(not CORPUS.is_dir(), reason="maple-court absent")
def test_the_narrowing_reaches_a_real_corpus_seed():
    """The end-to-end guard, on the default (greedy) seeder.

    maple-court declares six codes with an outside adjacency -- more than any
    other corpus programme -- so it is where the drift is visible. Because
    `graph.satisfies_as_outside` is now the single copy of the rule, stubbing
    it to `lambda nb: True` reproduces the pre-q4t seeder exactly, which makes
    this a matched pair differing in one function.

    Asserted as a DIRECTION, not a margin: this project has twice reported a
    margin its sample could not resolve (§38.19/§38.21). At the time of writing
    four seeds gave 9 `not adjacent to o` fails before and 4 after, and two
    fewer fails overall -- the narrowing removes adjacency fails and trades
    nothing for them.

    ~2 s. `experiments/diag_q4t_seed_adjacency.py` is the same measurement
    across all three relevant programmes and both solvers.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_diag_q4t",
        Path(__file__).resolve().parent.parent
        / "experiments" / "diag_q4t_seed_adjacency.py")
    diag = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(diag)

    seeds = range(4)
    counts = {}
    for narrowed, label in ((False, "before"), (True, "after")):
        rows = diag.arm(CORPUS, seeds, "greedy", narrowed)
        counts[label] = (
            sum(sum(1 for f in fails if "not adjacent to o" in f)
                for _, fails in rows),
            sum(len(fails) for _, fails in rows))

    assert counts["after"][0] < counts["before"][0], (
        f"the narrowing removed no `not adjacent to o` fails from maple-court "
        f"seeds: {counts}. Either it is no longer reaching the greedy seeder, "
        f"or the seeder no longer produces the case.")
    assert counts["after"][1] <= counts["before"][1], (
        f"the narrowing cost more fails than it saved: {counts}")


# --------------------------------------------------------------------------- #
# the guard that matters: one copy of the rule, not four
#
# A literal scan for the generic outside types was tried here and removed: the
# legitimate constant ``("C", "O", "S")`` makes it fire on noise, and a guard
# that cries wolf is deleted in irritation the first time it blocks someone.
# The behavioural tests above and the count below are what is left.
# --------------------------------------------------------------------------- #
REPO = Path(__file__).resolve().parent.parent


def test_the_seeders_import_the_shared_predicate():
    """If this stops being true the filters have been removed or inlined."""
    body = (REPO / "src/homemaker_layout/operators.py").read_text()
    assert body.count("satisfies_as_outside") >= 5, (
        "operators.py had five sites routed through graph.satisfies_as_outside "
        "(three cpsat `context_types` builders, the greedy `_sat`, and the "
        "beam `sat`). Fewer means one has been dropped.")

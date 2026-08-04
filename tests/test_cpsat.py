"""Tests for the exact CP-SAT room-code labelling solver (homemaker-py-2g7.5).

``cpsat.solve_room_labels`` is dom/geometry-independent (same decoupled-
testability convention as ``operators._beam_place_rooms``, exercised in
``test_operators.py::test_beam_place_rooms_is_deterministic_given_inputs``),
so these tests use plain hashable keys except where a direct comparison
against the existing beam/greedy heuristic requires real ``dom.Node``
objects (``_beam_place_rooms`` reads a neighbour's ``.type`` attribute for
already-fixed context).
"""

from homemaker_layout import cpsat, dom, operators


class _Req:
    def __init__(self, adjacency):
        self.adjacency = adjacency


def test_empty_inputs_return_empty_dict():
    assert cpsat.solve_room_labels([], [], {}, {}, {}) == {}
    assert cpsat.solve_room_labels(["s1"], [], {}, {}, {}) == {}
    assert cpsat.solve_room_labels([], ["a"], {}, {}, {}) == {}


def test_determinism():
    slots = ["s1", "s2", "s3"]
    codes = ["a", "b", "c"]
    reqs = {"a": _Req(["b"]), "b": _Req(["a"]), "c": _Req([])}
    neighbors = {"s1": {"s2"}, "s2": {"s1", "s3"}, "s3": {"s2"}}
    r1 = cpsat.solve_room_labels(slots, codes, reqs, neighbors, {})
    r2 = cpsat.solve_room_labels(slots, codes, reqs, neighbors, {})
    assert r1 == r2


def test_fixed_context_credits_adjacency_without_a_decision_neighbour():
    # a single slot with no room-slot neighbours at all, but a fixed
    # (already-typed) circulation neighbour "c" — the requirement must be
    # creditable purely from context_types, no decision variable involved.
    reqs = {"k1": _Req(["c"])}
    result = cpsat.solve_room_labels(
        ["s1"], ["k1"], reqs, {"s1": set()}, {"s1": {"c"}})
    assert result == {"s1": "k1"}


def test_drops_least_constrained_code_when_over_capacity():
    # more codes than slots: the code with a real adjacency requirement is
    # kept over the unconstrained one, same priority the greedy path's
    # hardest-first ordering uses (_n_secondary).
    reqs = {"a": _Req(["b"]), "b": _Req([])}
    result = cpsat.solve_room_labels(["s1"], ["b", "a"], reqs, {"s1": set()}, {})
    assert result == {"s1": "a"}


def test_finds_globally_optimal_labelling_beam_search_misses():
    """Hand-built counter-example (same "adversarial hand-built graph"
    convention as test_collapse_global.py's
    test_two_opt_polish_escapes_jacobi_plateau): a hub H (already typed
    "r") connects to four leaves L1-L4; L1-L2 also has its own direct
    edge. "s" and "t" each need only a "r" neighbour — satisfiable from
    ANY leaf, since every leaf touches the hub. "p" and "q" need EACH
    OTHER as a neighbour — only satisfiable via the one non-hub edge,
    L1-L2.

    All four codes tie at exactly one secondary-adjacency requirement, so
    the beam/greedy heuristic (``operators._beam_place_rooms``,
    beam_width=1 reproduces the plain greedy pass) processes them in
    whatever order the caller's shuffle produced. Given the order
    s, t, p, q, the degree/id tie-break greedily claims the special L1-L2
    edge for s and t (who don't need it — they're satisfiable everywhere),
    stranding p and q on L3/L4 with no edge between them: 2 of their 4
    combined requirements met. CP-SAT reasons globally and finds the
    assignment that satisfies all 4/4, regardless of processing order.
    """
    H = dom.Node(type="r")
    L1, L2, L3, L4 = (dom.Node(type=None) for _ in range(4))
    slots = [L1, L2, L3, L4]
    nbrs = {H: {L1, L2, L3, L4}, L1: {H, L2}, L2: {H, L1}, L3: {H}, L4: {H}}
    deg = {n: len(ns) for n, ns in nbrs.items()}
    idx = {L1: 0, L2: 1, L3: 2, L4: 3}
    dominated = set(slots)
    reqs = {"r": _Req(["s", "t"]), "s": _Req(["r"]), "t": _Req(["r"]),
            "p": _Req(["q"]), "q": _Req(["p"])}
    codes = ["s", "t", "p", "q"]

    placed = operators._beam_place_rooms(
        codes, slots, dominated, deg, idx, lambda s: nbrs[s], reqs,
        beam_width=1)
    for leaf, code in placed.items():
        leaf.type = code
    p_leaf = next(leaf for leaf, code in placed.items() if code == "p")
    q_leaf = next(leaf for leaf, code in placed.items() if code == "q")
    assert q_leaf not in nbrs[p_leaf], (
        "expected the greedy heuristic to strand p/q apart in this setup")

    neighbors_among_slots = {L1: {L2}, L2: {L1}, L3: set(), L4: set()}
    context_types = {s: {"r"} for s in slots}  # every leaf touches the hub
    result = cpsat.solve_room_labels(
        slots, codes, reqs, neighbors_among_slots, context_types)
    p_slot = next(s for s, c in result.items() if c == "p")
    q_slot = next(s for s, c in result.items() if c == "q")
    assert q_slot in neighbors_among_slots[p_slot], (
        "CP-SAT should place p/q on the one edge that satisfies both")

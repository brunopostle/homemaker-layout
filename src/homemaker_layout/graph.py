"""Leaf-adjacency graph build and pre-merge checks for programme-driven fitness.

TWO-PHASE PATTERN (ProgrammeDriven.pm:83-103):
  1. ``build_graphs(root)`` on the UNMERGED tree  → graph_base
  2. Run adjacency / level / vertical checks using graph_base and the unmerged tree.
  3. ``dom.merge_divided(root)`` — mutates the tree in place.
  4. ``build_graphs(root)`` again on the MERGED tree for storey processing.

FIDELITY DECISION — ``has_vertical_connection`` (DESIGN.md §8.1):
  Ported faithfully including the no-spatial-overlap stub from
  ProgrammeDriven.pm:399-423.  Any leaf of the target type on the level below
  counts as "connected", regardless of spatial overlap.  This is a known
  simplification in the Perl; it is preserved here for oracle parity.
  Reshape in Phase 4 if needed.

PERL CLONE QUIRK — ``has_circulation`` (Base.pm:228-241):
  Perl's ``Graph::clone()`` only copies vertices that are part of at least one
  edge.  Isolated vertices (single-leaf levels or unconnected nodes) are lost.
  An empty graph returns ``is_connected = False``.  ``has_circulation`` replicates
  this by removing isolated vertices before the usability/edge-type filtering.
"""

from __future__ import annotations

import itertools

import networkx as nx

from . import dom, geometry
from .dom import Node, is_generic, levels
from . import programme as _pr
from .programme import SpaceReq

DOOR_WIDTH = 1.2  # Urb::Dom::Fitness::Base default_params door_width


# --------------------------------------------------------------------------- #
# Graph build
# --------------------------------------------------------------------------- #

def build_graphs(root: Node, door_width: float = DOOR_WIDTH) -> list[nx.Graph]:
    """Return one ``nx.Graph`` per storey (lowest first); mirrors
    ``setup_storey_graphs`` in ``Urb::Dom::Fitness::Base``.

    This is called twice in the two-phase pattern: once before
    ``dom.merge_divided`` for adjacency/level/vertical checks, and once after
    for storey processing.
    """
    return [geometry.leaf_graph(lvl, door_width) for lvl in levels(root)]


def build_graphs_with_circ(
    root: Node,
    door_width: float,
    fail,
    usages: dict[str, str],
) -> tuple[list[nx.Graph], list[nx.Graph]]:
    """Build ``(graph_base, graph_circ)`` pairs; mirrors ``setup_storey_graphs``
    in ``Base.pm:217-241``.

    ``graph_base[i]`` is the unfiltered adjacency graph for level i.
    ``graph_circ[i]`` is a copy filtered by ``has_circulation``; emits
    "N inaccessible usable space" via ``fail`` if a level is disconnected after
    filtering.

    Perl clone quirk: ``has_circulation`` removes isolated vertices first, so a
    level with no adjacency edges always fires the "inaccessible" failure.
    """
    lvls = levels(root)
    graph_base: list[nx.Graph] = []
    graph_circ: list[nx.Graph] = []
    for i, lvl in enumerate(lvls):
        g = geometry.leaf_graph(lvl, door_width)
        graph_base.append(g)
        gc = g.copy()
        if not has_circulation(gc, usages):
            fail(f"{i} inaccessible usable space")
        graph_circ.append(gc)
    return graph_base, graph_circ


# --------------------------------------------------------------------------- #
# Has_Circulation (Base.pm:487-594)
# --------------------------------------------------------------------------- #

def _avg_path_len_from(G: nx.Graph, node: Node) -> float:
    """Average weighted shortest-path length from node to all reachable other nodes.

    Mirrors Perl's ``$graph->average_path_length($node, undef)`` which uses
    Dijkstra with edge weights (centroid-to-centroid distances, stored as 'weight').
    """
    try:
        lengths = dict(nx.single_source_dijkstra_path_length(G, node, weight="weight"))
        vals = [v for v in lengths.values() if v > 0]
        return sum(vals) / len(vals) if vals else 0.0
    except Exception:
        return 0.0


def _centrality(G: nx.Graph):
    """A sort key for the nodes of ``G`` as it is NOW: average path length to
    everything reachable, then -- for nodes exactly as central as each other --
    area and position, which are properties of the cell and not of where it
    falls in a list."""
    cache: dict = {}

    def key(n: Node):
        if n not in cache:
            c = geometry.centroid(n)
            cache[n] = (_avg_path_len_from(G, n), geometry.area(n),
                        round(c[0], 6), round(c[1], 6))
        return cache[n]

    return key


def has_circulation(G: nx.Graph, usages: dict[str, str]) -> bool:
    """Port of ``Urb::Dom::Has_Circulation`` (modifies G in place).

    ``usages`` maps room code -> access-requirement class (homemaker-py-sel,
    DESIGN.md §39.7); it decides which edges are trimmed. It used to be inferred
    from a leaf type's first character, so `la1` "Laundry Room" was trimmed as a
    living room and `tr1` "Treatment Room" as a toilet. Codes absent from the
    map (the generic ``C``/``O``/``S``) have no usage and are never trimmed.

    Replicates the Perl clone quirk: isolated vertices (degree 0) are removed
    first since Perl's ``Graph::clone`` only copies vertices in edges.  After
    that, removes non-usable nodes, trims bedroom/toilet cross-connections, then
    trims excess circulation and outdoor connections using centrality ordering.
    Returns True iff the remaining graph is connected.
    """
    # Perl clone loses isolated vertices → remove them first
    isolated = [v for v in list(G.nodes()) if G.degree(v) == 0]
    G.remove_nodes_from(isolated)

    # Remove non-usable nodes (outside above outside etc.)
    non_usable = [v for v in list(G.nodes()) if not dom.is_usable(v)]
    G.remove_nodes_from(non_usable)

    def _usage(v: Node) -> str:
        return usages.get(v.type, "")

    # A TERMINAL room (bedroom/utility) is reachable from circulation or outside
    # only — never a route through. Trim its edges to every other room.
    for v in list(G.nodes()):
        if _usage(v) not in _pr.PRIVATE_USAGES:
            continue
        to_remove = [nb for nb in list(G.neighbors(v))
                     if _usage(nb) in _pr.PRIVATE_STRIPS]
        G.remove_edges_from((v, nb) for nb in to_remove)

    # A toilet keeps its edge to a terminal room (the Brand adjacency, §39.6)
    # and loses outside/living/kitchen/toilet.
    for v in list(G.nodes()):
        if _usage(v) != "toilet":
            continue
        to_remove = [nb for nb in list(G.neighbors(v))
                     if nb.type in dom.GENERIC_OUTSIDE
                     or _usage(nb) in _pr.TOILET_STRIPS]
        G.remove_edges_from((v, nb) for nb in to_remove)

    # Any classified room keeps only one circulation neighbour.
    #
    # How central each neighbour is gets measured ONCE, on the graph as it
    # stands before any of this trimming, and ties go to geometry. Urb measured
    # inside the loop: every room's trim changed the path lengths the next room
    # sorted by, so which edges survived depended on the order the rooms were
    # listed in -- the tree's left/right naming. A harbor-house design and its
    # mirror image differed by two hard fails that way, and re-listing the same
    # storey in a shuffled order reproduced it (homemaker-py-rwwv, §39.100).
    central = _centrality(G)
    for v in list(G.nodes()):
        if _usage(v) not in _pr.PRIVATE_USAGES + ("toilet",) + _pr.SOCIABLE_USAGES:
            continue
        circ_nbs = [nb for nb in list(G.neighbors(v)) if dom.is_circulation(nb)]
        if len(circ_nbs) <= 1:
            continue
        circ_nbs.sort(key=central)
        # terminal rooms and toilets keep their LEAST central circulation
        # neighbour (privacy); sociable rooms keep their MOST central one.
        sociable = _usage(v) in _pr.SOCIABLE_USAGES
        while len(circ_nbs) > 1:
            if not sociable:
                G.remove_edge(v, circ_nbs.pop(0))
            else:
                G.remove_edge(v, circ_nbs.pop())

    # Clone the current state and run Connected_Outside to get outdoor components
    outside_graph = G.copy()
    _connected_outside_inplace(outside_graph)
    outside_components = list(nx.connected_components(outside_graph)) if len(outside_graph.nodes()) > 0 else []

    # blkc nodes: keep only one outdoor neighbour per outdoor component
    # (centrality again fixed before the loop, for the same reason as above)
    outdoor_central = _centrality(G)
    for v in list(G.nodes()):
        # terminal rooms, sociable rooms, and generic circulation
        if not (_usage(v) in _pr.PRIVATE_USAGES + _pr.SOCIABLE_USAGES
                or dom.is_circulation(v)):
            continue
        out_nbs = [
            nb for nb in list(G.neighbors(v))
            if dom.is_outside(nb) and dom.is_usable(nb)
        ]
        if len(out_nbs) <= 1:
            continue
        out_nbs.sort(key=outdoor_central)

        for component in outside_components:
            component_nbs = [nb for nb in out_nbs if nb in component]
            if len(component_nbs) <= 1:
                continue
            terminal = _usage(v) in _pr.PRIVATE_USAGES
            while len(component_nbs) > 1:
                if terminal:
                    nb = component_nbs.pop(0)
                else:
                    nb = component_nbs.pop()
                if G.has_edge(v, nb):
                    G.remove_edge(v, nb)

    if len(G.nodes()) == 0:
        return False
    return nx.is_connected(G)


def _connected_outside_inplace(G: nx.Graph) -> None:
    """Remove all non-outside/non-usable vertices; mirrors ``Connected_Outside``."""
    to_remove = [v for v in list(G.nodes()) if not (dom.is_outside(v) and dom.is_usable(v))]
    G.remove_nodes_from(to_remove)


def circulation_connectivity(G: nx.Graph) -> float:
    """Fraction of circulation cells in the largest connected circulation
    component — a continuous [0,1] proximity to a single connected circulation
    spine (1.0 = fully connected, lower = more fragmented, 0.0 = no circulation).

    Companion graded signal for the binary ``level N not connected`` fail
    (``connected_circulation``, homemaker-py-qi6). That fail fires identically
    whether a level's circulation is split into 2 components or 7, so it is FLAT
    across fragmentation and gives the outer search no gradient to climb toward
    connectivity. This proxy restores the gradient: among equally-failing
    layouts, the one whose circulation is closer to a single component scores
    higher. Measured on the same circ subgraph the fail uses (all non-circulation
    vertices removed), so the two agree at the connected endpoint (proxy == 1.0
    iff ``connected_circulation`` is True on a non-empty circ set).
    """
    gc = G.copy()
    gc.remove_nodes_from(
        [v for v in list(gc.nodes()) if not dom.is_circulation(v)]
    )
    n = gc.number_of_nodes()
    if n == 0:
        return 0.0
    largest = max((len(c) for c in nx.connected_components(gc)), default=0)
    return largest / n


def connected_circulation(G: nx.Graph) -> bool:
    """True iff circulation nodes are non-empty and connected; mirrors
    ``Urb::Dom::Connected_Circulation`` (Storey.pm:106).

    Removes all non-circulation vertices from G in place before checking.
    Perl's ``Graph::is_connected`` returns False for an empty graph — replicated
    here so "level N not connected" fires when there are no circulation nodes.
    """
    to_remove = [v for v in list(G.nodes()) if not dom.is_circulation(v)]
    G.remove_nodes_from(to_remove)
    if len(G.nodes()) == 0:
        return False  # Perl Graph::is_connected returns false for empty graph
    return nx.is_connected(G)


# --------------------------------------------------------------------------- #
# Stair-corner detection (Quad.pm:1490-1544, Dom.pm:648-668)
# --------------------------------------------------------------------------- #

def _corner_runs(leaf: Node, G: nx.Graph, neighbors: list[Node],
                 doors: "tuple | list" = ()) -> list[frozenset]:
    """Every SMALLEST run of consecutive corners that contains all of the
    leaf's shared walls -- the corners a stair must leave clear for doors.

    ``Urb::Quad::Corners_In_Use`` (Quad.pm:1490) returned the first such run it
    met, counting from corner 0 and never past corner 3, and the port copied
    both habits. So a wall spanning corners 3 and 0 could not be a pair (Perl
    read ``corners[4]``, which is undef) and came back as three corners, while
    the same wall on a leaf whose corners were numbered one place round came
    back as two. Which corner is "0" is the leaf's ``rotation``, a label that
    moves no wall -- and turning it changed the score of a design in 236 of 576
    trials (DESIGN.md §39.94).

    Owner's ruling, 2026-10-06 (§39.95): "we want to fit stairs to cores
    whichever way is best, so the flight can start at any corner and may run
    clockwise or counter clockwise". So runs wrap, and ALL the smallest ones
    are returned: the caller picks, and nothing here depends on the numbering.

    A DOOR MAY STAND ANYWHERE ALONG ITS WALL (owner, same day, §39.100: "doors
    are typically in the corner of a room, but can be moved to any other
    position along a shared wall if it frees up space to place stair flights").
    That is what the test below already means: a wall is served by any one
    corner it reaches, or by lying on an edge between two corners of the run,
    and the caller is free to choose which. ``doors`` are further walls to
    serve in the same way -- the entrance door's wall, which Urb pinned to
    BOTH corners of its edge.
    """
    walls = [list(w) for w in doors]
    for nb in neighbors:
        if G.has_edge(leaf, nb):
            coords = G[leaf][nb].get("coordinates")
            if coords is not None:
                walls.append(coords)
    corners = [geometry.coordinate(leaf, i) for i in range(4)]
    ib = geometry.is_between_2d

    def holds(run: list[int]) -> bool:
        """Each wall touches a corner of the run or ends on an edge inside it."""
        for w in walls:
            if any(ib(corners[c], w[0], w[1]) for c in run):
                continue
            if any(ib(w[k], corners[a], corners[b])
                   for a, b in zip(run, run[1:]) for k in (0, 1)):
                continue
            return False
        return True

    for size in (1, 2, 3):
        runs = [[(start + k) % 4 for k in range(size)] for start in range(4)]
        found = [frozenset(r) for r in runs if holds(r)]
        if found:
            return found
    # No three corners serve every wall, wherever the doors are put: all four
    # are taken, and the stair is a single straight flight. Urb answered THREE
    # here and never four -- its last test read corners[4] and [5], both undef,
    # and `is_between_2d(point, undef, undef)` is true of anything. Owner's
    # ruling (`homemaker-py-8b2u.7`, §39.100): "a stair core with doors on three
    # or four sides is going to need a single straight flight, unless the doors
    # can be moved" -- and they have been, above.
    return [frozenset(range(4))]


def corners_in_use(leaf: Node, G: nx.Graph, neighbors: list[Node]) -> list[int]:
    """One smallest run of corners containing all shared walls (the lowest
    numbered, for a stable answer). Its LENGTH is what means something; use
    :func:`_corner_runs` where the choice between equal runs matters."""
    return sorted(min(_corner_runs(leaf, G, neighbors), key=sorted))


def _stack_levels_above(leaf: Node) -> list[Node]:
    """Same-path nodes on all levels above leaf; mirrors ``Levels_Above`` on a leaf."""
    result: list[Node] = []
    n = leaf
    while True:
        above = dom._above_node(n)
        if above is None:
            break
        result.append(above)
        n = above
    return result


def stack_corners_in_use(
    leaf: Node,
    graph_circ_list: list[nx.Graph],
    all_levels: list[Node],
    doors: "tuple | list" = (),
) -> list[int]:
    """The fewest corners a stair in this shaft must leave clear; mirrors
    ``Urb::Dom::Stack_Corners_In_Use`` in what it means, not in how it counts.

    Returns [] if the stack does not span all levels above leaf, or if any
    level's node is not circulation type.

    Each storey of the shaft has doors to keep clear, and so one or more
    equally small runs of corners (:func:`_corner_runs`). Urb took the first
    run on each storey and united them, so the total depended on how the
    corners happened to be numbered. Here the runs are chosen TOGETHER, to
    leave the stair as many corners as the doors allow. ``doors`` are extra
    walls on ``leaf``'s own storey that need a door somewhere along them (the
    entrance). Every node of the stack has the same corners -- an upper storey
    inherits them -- so no index is remapped.
    """
    if leaf.type != "C":
        return []

    stack = [leaf] + _stack_levels_above(leaf)

    # The stack must span ALL levels (leaf's level + all above)
    li = _level_index(leaf, all_levels)
    levels_above_count = len(all_levels) - li - 1
    if len(stack) <= levels_above_count:
        return []

    # All stack nodes must be circulation
    if not all(n.type == "C" for n in stack):
        return []

    options: list[list[frozenset]] = []
    for level_offset, node in enumerate(stack):
        level_idx = li + level_offset
        if level_idx >= len(graph_circ_list):
            break
        G = graph_circ_list[level_idx]
        nbs = list(G.neighbors(node)) if G.has_node(node) else []
        options.append(_corner_runs(node, G, nbs,
                                    doors if level_offset == 0 else ()))

    best = None
    for choice in itertools.product(*options):
        union = frozenset().union(*choice)
        key = (len(union), sorted(union))
        if best is None or key < best:
            best = key
    return best[1]


def _level_index(n: Node, lvls: list[Node]) -> int:
    """Index of n's storey in ``lvls`` (0 = ground floor)."""
    lr = n
    while lr.parent is not None:
        lr = lr.parent
    return lvls.index(lr)


# --------------------------------------------------------------------------- #
# Adjacency helpers
# --------------------------------------------------------------------------- #

def _codes_match_prefix(codes: list[str], tc) -> bool:
    """Match a neighbour's codes against an adjacency target.

    ``tc`` is either a lowercase prefix string (ordinary programme requirement,
    Perl's ``^target_code`` semantics — a requirement ``t`` matches ``t1``,
    ``t2``, …) or, for a GENERIC requirement, the exact set of generic types it
    names (see :func:`_adjacency_target`).
    """
    if isinstance(tc, frozenset):
        return any(c in tc for c in codes)
    return any(c.lower().startswith(tc) for c in codes)


def code_matches_requirement(code: str, target_code: str) -> bool:
    """True if one room ``code`` satisfies an ``adjacency:`` requirement.

    The single place that answers "does this leaf count as the thing the
    programme asked to be next to". Shared with :mod:`homemaker_layout.cpsat`
    so the exact solver optimises the same relation the scorer checks.
    """
    return _codes_match_prefix([code], _adjacency_target(target_code))


def _adjacency_target(target_code: str):
    """Resolve one ``adjacency:`` entry to a matcher.

    §39.4: programmes name the generic types in lowercase (``adjacency: [c, o]``
    — every corpus programme does this), and a case-insensitive PREFIX match
    then let any programme code beginning with that letter satisfy the
    requirement: a room next to ``cr1`` "Common Room" counted as being next to
    circulation. A generic requirement now matches only the generic types it
    names; every other requirement keeps Perl's prefix semantics.
    """
    tc = target_code.lower()
    if tc == "c":
        return frozenset(dom.GENERIC_CIRCULATION)
    if tc == "o":
        return frozenset(("O",))
    if tc == "s":
        return frozenset(("S",))
    return tc


def satisfies_as_outside(nb: Node) -> bool:
    """True unless ``nb`` is an outside space that cannot be stood in.

    PUBLIC because it is the single definition of "does this neighbour count",
    and the seeders need it too. ``cpsat``'s model and ``operators``'
    greedy/beam room placement each decide the same question while building a
    seed; when they answered it their own way they optimised a relation the
    scorer does not check (homemaker-py-q4t, §39.64), which is the same defect
    ``code_matches_requirement`` was made public to prevent (§39.4) and the same
    shape as §39.63. One copy, imported.

    homemaker-py-k7c (DESIGN.md §39.56/§39.58). A programme asking for
    ``adjacency: [o]`` wants a terrace or a balcony -- somewhere usable. An
    unsupported void above ground floor is a hole, not a space, and eleven
    rooms across the corpus were being credited with outdoor adjacency they
    did not have.

    The owner's ruling, 2026-09-25: "If a room requires adjacency to an outside
    space, this is intended to be a usable outside space, ie. a terrace or
    balcony, a void isn't useful for this -- the void providing outside wall
    for potential window is already accounted for with the crinkliness
    measure." So the wall exposure a void does provide is still credited, once,
    by `quality_uncrinkliness`; this stops it being credited twice.

    Indoor neighbours are unaffected -- `is_usable` is True for every one of
    them -- so this narrows the outside case alone.

    NOTE the two graph builds in `fitness.evaluate`: adjacency runs on
    `graph_base_pre` and wall costing on a separate `graph_base`. Filtering
    here cannot de-cost a wall; an indoor|void wall is still external, which
    `test_indoor_outdoor_wall_is_external` (homemaker-py-w2k) holds.
    """
    return dom.is_usable(nb) if dom.is_outside(nb) else True


def has_adjacency(leaf: Node, target_code: str, G: nx.Graph,
                  colocate_pairs=(), multi_use: bool = False) -> bool:
    """True if ``leaf`` (or its nearest graphed ancestor) has a neighbour whose
    type matches ``^target_code`` (case-insensitive prefix); mirrors
    ``ProgrammeDriven.pm::has_adjacency``.

    Walking up to the nearest graphed ancestor handles merged nodes that no
    longer appear as individual vertices in a post-merge graph. Under
    ``multi_use`` a neighbour's ``leaf_codes()`` (both type and any live
    co_type) are checked, not just its scalar ``type``.
    """
    node: Node | None = leaf
    while node is not None and not G.has_node(node):
        node = node.parent
    if node is None:
        return False
    tc = _adjacency_target(target_code)
    for nb in G.neighbors(node):
        if (_codes_match_prefix(leaf_codes(nb, colocate_pairs, multi_use), tc)
                and satisfies_as_outside(nb)):
            return True
        # neighbour might be a merged branch — check its leaves
        for nl in (nb.leaves() if nb.divided else []):
            if (_codes_match_prefix(leaf_codes(nl, colocate_pairs, multi_use), tc)
                    and satisfies_as_outside(nl)):
                return True
    return False


def has_vertical_connection(leaf: Node, target_code: str, lvls: list[Node],
                            colocate_pairs=(), multi_use: bool = False) -> bool:
    """True if any leaf on the level directly below has type matching
    ``^target_code`` (case-insensitive); mirrors
    ``ProgrammeDriven.pm::has_vertical_connection``.

    FAITHFUL STUB — no spatial-overlap check (ProgrammeDriven.pm:399-423 bug).
    See module docstring for the fidelity decision.
    """
    li = _level_index(leaf, lvls)
    if li == 0:
        return False
    below_root = lvls[li - 1]
    tc = _adjacency_target(target_code)
    return any(_codes_match_prefix(leaf_codes(bl, colocate_pairs, multi_use), tc)
               for bl in below_root.leaves())


# --------------------------------------------------------------------------- #
# Space-count detection + failure stacking (ProgrammeDriven.pm:154-215)
# --------------------------------------------------------------------------- #

def leaf_share(leaf: Node, max_share: int) -> int:
    """How many same-code rooms a leaf covers under leaf-sharing (erc.3, §13.3).

    Explicit per-leaf multiplicity: construction stamps ``leaf.share = k`` and
    ``leaf.share_type = code``; this is honoured only while ``leaf.type`` still
    equals ``share_type``, so any retype/undivide silently invalidates a stale
    share (a retyped small leaf cannot claim to cover rooms it does not provide).
    Clamped to ``max_share``. Both the count check and ``quality_size`` read this
    one helper so they always agree on ``k``."""
    if leaf.share > 1 and leaf.share_type == leaf.type:
        return min(max_share, leaf.share)
    return 1


def leaf_codes(leaf: Node, colocate_pairs=(), multi_use: bool = False) -> list[str]:
    """Codes ``leaf`` counts as (homemaker-py-1s3, §26 path b).

    Normally just ``[leaf.type]``. Under ``multi_use``, a leaf carrying a
    ``co_type`` counts as BOTH codes simultaneously — but only while
    ``{type, co_type}`` is still a valid declared co-location pair
    (``colocate_pairs``, from ``programme.derive_colocate_pairs``); a generic
    retype mutation that changes ``leaf.type`` out from under a stale
    ``co_type`` silently drops it, mirroring ``leaf_share``'s type-guard.
    """
    if not leaf.type:
        return []
    if multi_use and leaf.co_type and frozenset((leaf.type, leaf.co_type)) in colocate_pairs:
        return [leaf.type, leaf.co_type]
    return [leaf.type]


def check_space_counts(
    root: Node,
    targets: dict[str, SpaceReq],
    leaf_sharing: bool = False,
    max_share: int = 4,
    multi_use: bool = False,
    colocate_pairs=(),
    room_checks: tuple[str, ...] = ("size", "width", "proportion"),
) -> tuple[list[str], list[str]]:
    """Check design has exactly the required spaces; mirrors
    ``check_space_counts`` in ``ProgrammeDriven.pm:156-215``.

    Returns ``(failures, missing_ids)`` where:
    - ``failures`` is the stacked failure list: per missing instance, 2 base
      failures plus one placeholder for each quality check it would have faced
      (homemaker-py-1i8); also "too many" for excess spaces.

      THIS FUNCTION'S share is fixed, but the CASCADE a missing room pays is
      not, and 1i8's "a FIXED 5, independent of how the programme was spelled"
      described only this producer. `check_adjacency` adds a placeholder per
      DECLARED adjacency and `check_level_constraints` one for a declared
      level, so the true cost is
      ``2 + (room checks asked) + (declared adjacencies) + (1 if a level)``
      -- 5 to 8 lines across the four programmes, i.e. 1/32 to 1/256 (DESIGN.md
      §39.80). §39.37 also moved the floor: retiring room width dropped the
      room-check placeholders from three to two.

      THE OWNER HAS RULED THAT SPREAD CORRECT (2026-09-29): a room declaring
      three neighbours and a fixed storey is more entangled with the rest of the
      design, so omitting it really does do more damage than omitting a room
      with one neighbour and no storey. It is a property of the brief, not an
      artefact of how it was typed. Do not "fix" it into a flat penalty. The
      separate question of whether the BASE magnitude is right is open
      (homemaker-py-3i3) and waits on a corpus at the live objective.
    - ``missing_ids`` is the list of virtual space ids used to suppress false
      adjacency/level/vertical failures for absent spaces.

    With ``leaf_sharing`` (erc.3, DESIGN.md §13.3) presence is counted by
    *coverage* not leaf count: one sufficiently large leaf of a code covers
    ``round(area/target)`` required instances (capped at ``max_share``), so a
    single shared leaf can satisfy several same-code rooms without a missing
    fail. Default OFF reproduces the strict per-leaf count exactly.
    """
    # Count spaces by type (case-sensitive, as in Perl exact-match for unique)
    count: dict[str, list[Node]] = {}
    for lvl in levels(root):
        for leaf in lvl.leaves():
            for code in leaf_codes(leaf, colocate_pairs, multi_use):
                count.setdefault(code, []).append(leaf)

    failures: list[str] = []
    missing: list[str] = []

    for code, req in targets.items():
        # §39.4: skip only Urb's GENERIC structural types. This used to test
        # code[0].lower(), which silently dropped any programme code beginning
        # with c/o/s from the required set -- 14% of harbor-house. Generic types
        # are never declared in ``spaces`` anyway, so this is now a no-op guard
        # kept for intent rather than a filter that discards real requirements.
        if is_generic(code):
            continue

        leaves_of = count.get(code, [])
        if leaf_sharing and req.size > 0:
            # Coverage: sum each leaf's explicit (type-guarded) share multiplicity.
            actual = sum(leaf_share(lf, max_share) for lf in leaves_of)
        else:
            actual = len(leaves_of)
        expected = req.count

        if actual < expected:
            n_missing = expected - actual
            for i in range(1, n_missing + 1):
                mid = code if expected == 1 else f"{code}#{i}"
                # 2 base failures
                failures.append(f"missing required space: {mid}")
                failures.append(f"missing required space: {mid} (critical)")
                missing.append(mid)
                # One placeholder per quality check the missing room WOULD have
                # faced -- always all three (homemaker-py-1i8, DESIGN.md §38.12).
                #
                # These used to be gated on req.has_size/has_width/has_proportion,
                # which record only whether the author TYPED the key in
                # patterns.config, not whether the requirement exists. It always
                # exists: `get_space_params` fills width and proportion from
                # defaults (or derives width from size), so a PRESENT room is
                # checked on all three however its config was spelled --
                # programme-house's `t2` declares `size:` alone and still gets a
                # real width target of 1.633 that it can fail on.
                #
                # So the missing path must mirror the present path. Gating it
                # made one missing room cost 3 fails and another 5, and under
                # `value *= 0.5 ** len(failures)` that is a 4x difference in
                # penalty between two single rooms decided by YAML verbosity --
                # inherited by the tiered comparator, whose primary key n_hard
                # is dominated by these cascades.
                # homemaker-py-s34: the caller supplies which checks a PRESENT
                # room actually faces. §38.12's point is that missing and
                # present rooms must be billed on the same terms; once §39.37
                # stopped asking rooms for a width, billing a missing room for
                # one re-opened exactly that asymmetry.
                for check in room_checks:
                    failures.append(f"missing {mid}: would need {check} check")

        elif actual > expected:
            failures.append(
                f"too many spaces: {code} (found {actual}, expected {expected})"
            )

    return failures, missing


# --------------------------------------------------------------------------- #
# Pre-merge checks
# --------------------------------------------------------------------------- #

def check_adjacency(
    root: Node,
    targets: dict[str, SpaceReq],
    graph_base: list[nx.Graph],
    missing: list[str],
    multi_use: bool = False,
    colocate_pairs=(),
) -> list[str]:
    """Adjacency check failures; mirrors
    ``check_adjacency_requirements`` in ``ProgrammeDriven.pm:218-278``.

    Run on the UNMERGED tree with the pre-merge ``graph_base``.
    """
    lvls = levels(root)
    missing_set = set(missing)
    failures: list[str] = []
    seen: set[tuple] = set()   # dedup per (leaf.id, code, adj_code) like Perl

    for code, req in targets.items():
        if not req.adjacency:
            continue
        any_missing = any(m == code or m.startswith(f"{code}#") for m in missing_set)
        # The placeholder charges for the MISSING instance; the PRESENT ones are
        # still checked. This used to `continue` here, so omitting one instance
        # of a code exempted every other instance from the check: maple-court
        # s1 at 07b2058+orth hid six `not adjacent to c` fails by omitting one
        # of twelve `r`, a 6-line price for 6 lines hidden -- and for a code
        # with a large count, omission could pay outright (DESIGN.md §39.84).
        if any_missing:
            for adj_code in req.adjacency:
                failures.append(f"missing {code}: would need adjacency to {adj_code}")

        for lvl in lvls:
            li = lvls.index(lvl)
            for leaf in lvl.leaves():
                if code not in leaf_codes(leaf, colocate_pairs, multi_use):
                    continue
                G = graph_base[li]
                for adj_code in req.adjacency:
                    key = (leaf.id, *sorted((code, adj_code)))
                    if key in seen:
                        continue
                    seen.add(key)
                    if not has_adjacency(leaf, adj_code, G, colocate_pairs, multi_use):
                        failures.append(
                            f"{li}/{leaf.id} ({code}) not adjacent to {adj_code}"
                        )
    return failures


def check_level_constraints(
    root: Node,
    targets: dict[str, SpaceReq],
    missing: list[str],
    multi_use: bool = False,
    colocate_pairs=(),
) -> list[str]:
    """Level constraint failures; mirrors
    ``check_level_constraints`` in ``ProgrammeDriven.pm:319-358``.
    """
    lvls = levels(root)
    missing_set = set(missing)
    failures: list[str] = []

    for code, req in targets.items():
        if req.level is None:
            continue
        any_missing = any(m == code or m.startswith(f"{code}#") for m in missing_set)
        if any_missing:   # placeholder for the missing one; present ones checked (§39.84)
            failures.append(f"missing {code}: would need to be on level {req.level}")

        for lvl in lvls:
            li = lvls.index(lvl)
            for leaf in lvl.leaves():
                if code not in leaf_codes(leaf, colocate_pairs, multi_use):
                    continue
                if li != req.level:
                    failures.append(
                        f"{code} on wrong level (level {li}, expected {req.level})"
                    )
    return failures


def check_vertical_connectivity(
    root: Node,
    targets: dict[str, SpaceReq],
    missing: list[str],
    multi_use: bool = False,
    colocate_pairs=(),
) -> list[str]:
    """Vertical connectivity failures; mirrors
    ``check_vertical_connectivity_requirements`` in ``ProgrammeDriven.pm:360-397``.

    Uses the faithful no-overlap stub; see ``has_vertical_connection``.
    """
    lvls = levels(root)
    missing_set = set(missing)
    failures: list[str] = []

    for code, req in targets.items():
        if req.requires_below is None:
            continue
        any_missing = any(m == code or m.startswith(f"{code}#") for m in missing_set)
        if any_missing:
            failures.append(
                f"missing {code}: would need connection to {req.requires_below} below"
            )   # and the present instances are still checked (§39.84)

        for lvl in lvls:
            for leaf in lvl.leaves():
                if code not in leaf_codes(leaf, colocate_pairs, multi_use):
                    continue
                if not has_vertical_connection(leaf, req.requires_below, lvls,
                                               colocate_pairs, multi_use):
                    failures.append(
                        f"{code} not connected to {req.requires_below} below"
                    )
    return failures


# --------------------------------------------------------------------------- #
# Substrate readiness (DESIGN.md §11.3 Stage 1 objective)
# --------------------------------------------------------------------------- #

STAIR_MIN_AREA = 6.0  # a C leaf must be at least this big to count as a core


def substrate_readiness(
    base_root: Node,
    reqs: dict[str, SpaceReq],
    n_storeys: int,
) -> float:
    """Score in [0,1] of how well a single-storey base can HOST upper floors.

    Stage 1 must optimise the base as a *substrate*, not merely as a ground floor
    (the §4.2 partial-objective / bungalow trap). Two structural proxies from the
    bead:

    - **Reserved core**: a vertically-alignable circulation core must already
      exist, so Stage 2 keeps it rather than carving one from scratch. Full credit
      when at least one base ``C`` leaf is at least ``STAIR_MIN_AREA``; otherwise a
      small floor (0.25) so the term still rewards adding/enlarging a core.
    - **Capacity**: enough divisible base footprint to carve the upper-floor room
      set above. ``min(1, usable_base_area / required_upper_area)`` where the
      reserved core area is excluded from the usable footprint.

    Returns ``core_factor * capacity`` (both in [0,1]).
    """
    # Parallel staged runs (n_workers>1) score children in pool workers, so this
    # parent-process read is never preceded by the score_with_fails clear that
    # normally keeps geometry._cache cold; without this, evicted trees' freed
    # addresses can alias into freshly unpickled ones (homemaker-py-cvw).
    geometry.clear_cache()
    base_lvl = levels(base_root)[0]
    base_leaves = base_lvl.leaves()
    total_base_area = sum(geometry.area(lf) for lf in base_leaves)

    core_leaves = [
        lf for lf in base_leaves
        if lf.type == "C" and geometry.area(lf) >= STAIR_MIN_AREA
    ]
    core_factor = 1.0 if core_leaves else 0.25
    core_area = max((geometry.area(lf) for lf in core_leaves), default=0.0)

    # Required floor area on storeys >= 1: level-constrained upper rooms plus the
    # expected share of level-free rooms distributed to upper storeys.
    upper_levels = sum(
        req.size * req.count
        for req in reqs.values()
        if req.level is not None and req.level >= 1
    )
    free_area = sum(
        req.size * req.count
        for code, req in reqs.items()
        if not is_generic(code) and req.level is None
    )
    upper_free = free_area * (n_storeys - 1) / n_storeys if n_storeys > 0 else 0.0
    required_upper_area = upper_levels + upper_free

    usable = max(0.0, total_base_area - core_area)
    capacity = 1.0 if required_upper_area <= 0 else min(1.0, usable / required_upper_area)
    return core_factor * capacity

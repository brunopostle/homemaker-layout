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

import networkx as nx

from . import dom, geometry
from .dom import Node, levels
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
        if not has_circulation(gc):
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


def has_circulation(G: nx.Graph) -> bool:
    """Port of ``Urb::Dom::Has_Circulation`` (modifies G in place).

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

    # Remove b → [lkbt] edges  (bedrooms only connect to circulation/outside)
    for v in list(G.nodes()):
        if not (v.type and v.type[0].lower() == "b"):
            continue
        to_remove = [
            nb for nb in list(G.neighbors(v))
            if nb.type and nb.type[0].lower() in ("l", "k", "b", "t")
        ]
        G.remove_edges_from((v, nb) for nb in to_remove)

    # Remove t → [olkt] edges  (toilets only connect to bedrooms/circulation)
    for v in list(G.nodes()):
        if not (v.type and v.type[0].lower() == "t"):
            continue
        to_remove = [
            nb for nb in list(G.neighbors(v))
            if nb.type and nb.type[0].lower() in ("o", "l", "k", "t")
        ]
        G.remove_edges_from((v, nb) for nb in to_remove)

    # btlk nodes: keep only one circulation neighbour
    for v in list(G.nodes()):
        if not (v.type and v.type[0].lower() in ("b", "t", "l", "k")):
            continue
        circ_nbs = [nb for nb in list(G.neighbors(v)) if dom.is_circulation(nb)]
        if len(circ_nbs) <= 1:
            continue
        circ_nbs.sort(key=lambda nb: _avg_path_len_from(G, nb))
        # b/t: keep least popular (last), remove most popular (first)
        # l/k: keep most popular (first), remove least popular (last)
        t0 = v.type[0].lower()
        while len(circ_nbs) > 1:
            if t0 in ("b", "t"):
                G.remove_edge(v, circ_nbs.pop(0))
            else:
                G.remove_edge(v, circ_nbs.pop())

    # Clone the current state and run Connected_Outside to get outdoor components
    outside_graph = G.copy()
    _connected_outside_inplace(outside_graph)
    outside_components = list(nx.connected_components(outside_graph)) if len(outside_graph.nodes()) > 0 else []

    # blkc nodes: keep only one outdoor neighbour per outdoor component
    for v in list(G.nodes()):
        if not (v.type and v.type[0].lower() in ("b", "l", "k", "c")):
            continue
        out_nbs = [
            nb for nb in list(G.neighbors(v))
            if dom.is_outside(nb) and dom.is_usable(nb)
        ]
        if len(out_nbs) <= 1:
            continue
        out_nbs.sort(key=lambda nb: _avg_path_len_from(G, nb))

        for component in outside_components:
            component_nbs = [nb for nb in out_nbs if nb in component]
            if len(component_nbs) <= 1:
                continue
            t0 = v.type[0].lower()
            while len(component_nbs) > 1:
                if t0 == "b":
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

def _corners_of(leaf: Node) -> list[list[float] | None]:
    """4 corner coordinates of leaf (index 0-3), with None at index 4 to
    replicate Perl's undef-array-element behaviour in ``Corners_In_Use``."""
    return [geometry.coordinate(leaf, i) for i in range(4)] + [None]


def corners_in_use(
    leaf: Node, G: nx.Graph, neighbors: list[Node]
) -> list[int]:
    """Return the minimum set of consecutive corner indices needed to contain
    all shared walls; mirrors ``Urb::Quad::Corners_In_Use`` (Quad.pm:1490).

    Returns raw consecutive indices — may include values > 3 (e.g. [3,4] or
    [3,4,5]); the caller (``stack_corners_in_use``) normalises with % 4 after
    rotation remapping.

    Perl's ``corners[4]`` is undef.  ``is_between_2d(point, undef, undef)``
    always returns True in Perl (distance_2d(undef,x)=0 so abs(0-0-0)<1e-6).
    This means the triple check at idx=3 always succeeds in Perl, so [3,4,5]
    is always returned when no shorter span works — equivalent to [0,1,3] after
    rotation-normalisation.  ``_ib`` replicates that: both-None → True,
    one-None → False.
    """
    walls: list[list] = []
    for nb in neighbors:
        if G.has_edge(leaf, nb):
            coords = G[leaf][nb].get("coordinates")
            if coords is not None:
                walls.append(coords)

    corners = _corners_of(leaf)  # len==5, corners[4]=None

    ib = geometry.is_between_2d  # (point, pa, pb) — handles point=None

    def _ib(point, pa, pb):
        if pa is None and pb is None:
            return True  # Perl: is_between_2d(point,undef,undef) always True
        if pa is None or pb is None:
            return False
        return ib(point, pa, pb)

    # Try single corner
    for idx in range(4):
        c = corners[idx]
        if all(ib(c, w[0], w[1]) for w in walls):
            return [idx]

    # Try pair (idx, idx+1); corners[4]=None → _ib returns False
    for idx in range(4):
        c0, c1 = corners[idx], corners[idx + 1]
        ok = True
        for w in walls:
            if ib(c0, w[0], w[1]):
                continue
            if ib(c1, w[0], w[1]):
                continue
            if _ib(w[0], c0, c1):
                continue
            if _ib(w[1], c0, c1):
                continue
            ok = False
            break
        if ok:
            return [idx, idx + 1]  # raw; may be [3,4]

    # Try triple (idx, idx+1, idx+2); corners[4] and corners[5]=None → _ib False
    for idx in range(4):
        c0 = corners[idx]
        c1 = corners[idx + 1]
        c2 = corners[idx + 2] if idx + 2 < len(corners) else None
        ok = True
        for w in walls:
            if ib(c0, w[0], w[1]):
                continue
            if ib(c1, w[0], w[1]):
                continue
            if ib(c2, w[0], w[1]):
                continue
            if _ib(w[0], c0, c1):
                continue
            if _ib(w[1], c0, c1):
                continue
            if _ib(w[0], c1, c2):
                continue
            if _ib(w[1], c1, c2):
                continue
            ok = False
            break
        if ok:
            return [idx, idx + 1, idx + 2]  # raw; may be [3,4,5]

    return [0, 1, 2, 3]


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


def _ground_rotation(node: Node) -> int:
    """Rotation of the lowest below node; mirrors Perl's ``Rotation()`` method.

    Perl's ``Rotation`` returns ``$self->Below->Rotation`` when Below is
    defined, so upper-storey nodes always report the ground-floor rotation.
    Using the raw ``node.rotation`` (stored per-level) would give wrong
    rotation corrections in ``stack_corners_in_use``.
    """
    while node.below is not None:
        node = node.below
    return node.rotation


def stack_corners_in_use(
    leaf: Node,
    graph_circ_list: list[nx.Graph],
    all_levels: list[Node],
) -> list[int]:
    """Minimum set of corners in use for the vertical stair stack; mirrors
    ``Urb::Dom::Stack_Corners_In_Use``.

    Returns [] if the stack does not span all levels above leaf, or if any
    level's node is not circulation type.
    """
    if not (leaf.type and leaf.type[0].lower() == "c"):
        return []

    stack = [leaf] + _stack_levels_above(leaf)

    # The stack must span ALL levels (leaf's level + all above)
    li = _level_index(leaf, all_levels)
    levels_above_count = len(all_levels) - li - 1
    if len(stack) <= levels_above_count:
        return []

    # All stack nodes must be circulation
    if not all(n.type and n.type[0].lower() == "c" for n in stack):
        return []

    leaf_rot = _ground_rotation(leaf)
    all_corners: set[int] = set()
    for level_offset, node in enumerate(stack):
        level_idx = li + level_offset
        if level_idx >= len(graph_circ_list):
            break
        G = graph_circ_list[level_idx]
        nbs = list(G.neighbors(node)) if G.has_node(node) else []
        in_use = corners_in_use(node, G, nbs)
        # Map to ground-floor rotation frame using ground rotation (Perl
        # Rotation() follows Below chain, so upper nodes use ground rotation)
        node_rot = _ground_rotation(node)
        for c in in_use:
            all_corners.add((c - node_rot + leaf_rot) % 4)

    return sorted(all_corners)


def _level_index(n: Node, lvls: list[Node]) -> int:
    """Index of n's storey in ``lvls`` (0 = ground floor)."""
    lr = n
    while lr.parent is not None:
        lr = lr.parent
    return lvls.index(lr)


# --------------------------------------------------------------------------- #
# Adjacency helpers
# --------------------------------------------------------------------------- #

def _codes_match_prefix(codes: list[str], tc: str) -> bool:
    return any(c.lower().startswith(tc) for c in codes)


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
    tc = target_code.lower()
    for nb in G.neighbors(node):
        if _codes_match_prefix(leaf_codes(nb, colocate_pairs, multi_use), tc):
            return True
        # neighbour might be a merged branch — check its leaves
        for nl in (nb.leaves() if nb.divided else []):
            if _codes_match_prefix(leaf_codes(nl, colocate_pairs, multi_use), tc):
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
    tc = target_code.lower()
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
) -> tuple[list[str], list[str]]:
    """Check design has exactly the required spaces; mirrors
    ``check_space_counts`` in ``ProgrammeDriven.pm:156-215``.

    Returns ``(failures, missing_ids)`` where:
    - ``failures`` is the stacked failure list (2 base + per-quality per missing
      space, up to ~7 per missing space; also "too many" for excess spaces).
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
        if code[0].lower() in ("c", "o", "s"):
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
                # Per-quality failures (1 each for explicitly configured params)
                if req.has_size:
                    failures.append(f"missing {mid}: would need size check")
                if req.has_width:
                    failures.append(f"missing {mid}: would need width check")
                if req.has_proportion:
                    failures.append(f"missing {mid}: would need proportion check")

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
        if any_missing:
            for adj_code in req.adjacency:
                failures.append(f"missing {code}: would need adjacency to {adj_code}")
            continue

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
        if any_missing:
            failures.append(f"missing {code}: would need to be on level {req.level}")
            continue

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
            )
            continue

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
    base_lvl = levels(base_root)[0]
    base_leaves = base_lvl.leaves()
    total_base_area = sum(geometry.area(lf) for lf in base_leaves)

    core_leaves = [
        lf for lf in base_leaves
        if lf.type and lf.type[0].lower() == "c" and geometry.area(lf) >= STAIR_MIN_AREA
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
        if code[0].lower() not in ("c", "o", "s") and req.level is None
    )
    upper_free = free_area * (n_storeys - 1) / n_storeys if n_storeys > 0 else 0.0
    required_upper_area = upper_levels + upper_free

    usable = max(0.0, total_base_area - core_area)
    capacity = 1.0 if required_upper_area <= 0 else min(1.0, usable / required_upper_area)
    return core_factor * capacity

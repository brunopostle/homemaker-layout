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
    for storey processing.  ``Has_Circulation`` filtering (which produces the
    "inaccessible usable space" failure) is implemented in homemaker-py-hgg.
    """
    return [geometry.leaf_graph(lvl, door_width) for lvl in levels(root)]


# --------------------------------------------------------------------------- #
# Adjacency helpers
# --------------------------------------------------------------------------- #

def has_adjacency(leaf: Node, target_code: str, G: nx.Graph) -> bool:
    """True if ``leaf`` (or its nearest graphed ancestor) has a neighbour whose
    type matches ``^target_code`` (case-insensitive prefix); mirrors
    ``ProgrammeDriven.pm::has_adjacency``.

    Walking up to the nearest graphed ancestor handles merged nodes that no
    longer appear as individual vertices in a post-merge graph.
    """
    node: Node | None = leaf
    while node is not None and not G.has_node(node):
        node = node.parent
    if node is None:
        return False
    tc = target_code.lower()
    for nb in G.neighbors(node):
        if nb.type and nb.type.lower().startswith(tc):
            return True
        # neighbour might be a merged branch — check its leaves
        for nl in (nb.leaves() if nb.divided else []):
            if nl.type and nl.type.lower().startswith(tc):
                return True
    return False


def has_vertical_connection(leaf: Node, target_code: str, lvls: list[Node]) -> bool:
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
    return any(bl.type and bl.type.lower().startswith(tc) for bl in below_root.leaves())


def _level_index(n: Node, lvls: list[Node]) -> int:
    """Index of n's storey in ``lvls`` (0 = ground floor)."""
    lr = n
    while lr.parent is not None:
        lr = lr.parent
    return lvls.index(lr)


# --------------------------------------------------------------------------- #
# Space-count detection (missing space list only; stacking is in homemaker-py-hgg)
# --------------------------------------------------------------------------- #

def find_missing_spaces(root: Node, targets: dict[str, SpaceReq]) -> list[str]:
    """Return ids of missing required spaces; mirrors the count-detection
    part of ``check_space_counts`` in ``ProgrammeDriven.pm:156-215``.

    Only returns the missing-code list used by other checks to suppress false
    adjacency/level/vertical failures.  The 2-base + per-quality failure
    stacking (up to ~7 failures per missing space) is implemented in
    homemaker-py-hgg.
    """
    count: dict[str, int] = {}
    for lvl in levels(root):
        for leaf in lvl.leaves():
            if leaf.type:
                key = leaf.type.lower()
                count[key] = count.get(key, 0) + 1

    missing: list[str] = []
    for code, req in targets.items():
        if code[0].lower() in ("c", "o", "s"):
            continue
        actual = count.get(code.lower(), 0)
        if actual < req.count:
            for i in range(req.count - actual):
                missing.append(code if req.count == 1 else f"{code}#{i + 1}")
    return missing


# --------------------------------------------------------------------------- #
# Pre-merge checks
# --------------------------------------------------------------------------- #

def check_adjacency(
    root: Node,
    targets: dict[str, SpaceReq],
    graph_base: list[nx.Graph],
    missing: list[str],
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
                if leaf.type != code:
                    continue
                G = graph_base[li]
                for adj_code in req.adjacency:
                    key = (leaf.id, *sorted((code, adj_code)))
                    if key in seen:
                        continue
                    seen.add(key)
                    if not has_adjacency(leaf, adj_code, G):
                        failures.append(
                            f"{li}/{leaf.id} ({code}) not adjacent to {adj_code}"
                        )
    return failures


def check_level_constraints(
    root: Node,
    targets: dict[str, SpaceReq],
    missing: list[str],
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
                if leaf.type != code:
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
                if leaf.type != code:
                    continue
                if not has_vertical_connection(leaf, req.requires_below, lvls):
                    failures.append(
                        f"{code} not connected to {req.requires_below} below"
                    )
    return failures

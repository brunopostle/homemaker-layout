"""High-locality topology operators: mutation + subtree crossover.

Operators edit a *decoded* Node tree (the canonical phenotype) and re-link it;
``genome.encode`` then re-derives the genome, which makes every operator
total: dangling per-storey deltas after an undivide below, or storey
misalignment after crossover, are absorbed by encode's parallel walk (cuts
that stop existing below simply become owned above). Geometry moves (Urb's
``slide``, floor heights) are deliberately absent — the inner loop owns all
continuous DOF (DESIGN.md §5), and the warm-vs-cold result (homemaker-py-8cs)
makes Lamarckian re-optimisation after every topology move mandatory anyway.

Each ``mutate_*`` helper applies one random instance to a deep copy and
returns ``(child_root, descriptor)``; ``crossover`` returns two children.
Candidate selection respects ownership: cuts are swappable/rotatable only
where they are live (below is None / below undivided — the free-branch
criterion), so operators never edit dead fields.
"""

from __future__ import annotations

import copy

import numpy as np

from . import dom


def _finalise(root: dom.Node) -> dom.Node:
    from . import geometry

    dom.link(root)
    geometry.clear_cache()
    return root


def _level_nodes(lvl: dom.Node) -> list[dom.Node]:
    out = [lvl]
    if lvl.divided:
        out += _level_nodes(lvl.left) + _level_nodes(lvl.right)
    return out


def _pick(rng: np.random.Generator, items: list):
    return items[int(rng.integers(len(items)))]


def _pick_weighted_by_storey(rng: np.random.Generator, items: list, base_p: float):
    """Pick one ``(level_index, node)`` tuple, downweighting the base storey.

    Base-storey leaves/branches (``li == 0``) are sampled with relative weight
    ``base_p``; everything else with weight 1.0. ``base_p == 1.0`` (default)
    reproduces a uniform pick exactly (DESIGN.md §11.3 Stage 2 keeps the base
    mutable at low probability rather than freezing it).
    """
    if base_p >= 1.0 or not items:
        return _pick(rng, items)
    w = np.array([base_p if li == 0 else 1.0 for li, _ in items], dtype=float)
    if w.sum() == 0:
        w[:] = 1.0
    return items[int(rng.choice(len(items), p=w / w.sum()))]


def _owned_branches(root: dom.Node) -> list[tuple[int, dom.Node]]:
    """(level_index, node) for every divided node whose cut is live here."""
    out = []
    for li, lvl in enumerate(dom.levels(root)):
        for n in _level_nodes(lvl):
            if n.divided and (n.below is None or not n.below.divided):
                out.append((li, n))
    return out


def _leaves(root: dom.Node) -> list[tuple[int, dom.Node]]:
    return [(li, leaf) for li, lvl in enumerate(dom.levels(root)) for leaf in lvl.leaves()]


# --------------------------------------------------------------------------- #
# Mutations
# --------------------------------------------------------------------------- #
def mutate_divide(root: dom.Node, rng: np.random.Generator,
                  types: list[str], base_p: float = 1.0) -> tuple[dom.Node, str]:
    child = copy.deepcopy(root)
    li, leaf = _pick_weighted_by_storey(rng, _leaves(child), base_p)
    leaf.division = [0.5, 0.5]
    leaf.rotation = int(rng.integers(4))
    leaf.left = dom.Node(type=leaf.type)
    leaf.right = dom.Node(type=str(_pick(rng, types)))
    leaf.type = None
    return _finalise(child), f"divide {li}/{leaf.id or 'root'}"


def mutate_undivide(root: dom.Node, rng: np.random.Generator,
                    types: list[str], base_p: float = 1.0) -> tuple[dom.Node, str]:
    child = copy.deepcopy(root)
    cands = [(li, n) for li, n in _owned_branches(child)
             if not n.left.divided and not n.right.divided]
    if not cands:
        return _finalise(child), "undivide noop"
    li, n = _pick_weighted_by_storey(rng, cands, base_p)
    # prefer a PROGRAMME room type over a generic (circulation/outside/sahn)
    # one when collapsing two children into one leaf (§39.4)
    keep = [t for t in (n.left.type, n.right.type) if t and not dom.is_generic(t)]
    n.type = keep[0] if keep else (n.left.type or str(_pick(rng, types)))
    n.division = None
    n.left = n.right = None
    return _finalise(child), f"undivide {li}/{n.id or 'root'}"


def mutate_retype(root: dom.Node, rng: np.random.Generator,
                  types: list[str], base_p: float = 1.0) -> tuple[dom.Node, str]:
    child = copy.deepcopy(root)
    li, leaf = _pick_weighted_by_storey(rng, _leaves(child), base_p)
    leaf.type = str(_pick(rng, [t for t in types if t != leaf.type] or types))
    return _finalise(child), f"retype {li}/{leaf.id or 'root'}->{leaf.type}"


def mutate_swap(root: dom.Node, rng: np.random.Generator,
                types: list[str], base_p: float = 1.0) -> tuple[dom.Node, str]:
    child = copy.deepcopy(root)
    cands = _owned_branches(child)
    if not cands:  # undivided topology (e.g. a bare plot seed)
        return _finalise(child), "swap noop"
    li, n = _pick_weighted_by_storey(rng, cands, base_p)
    n.left, n.right = n.right, n.left
    return _finalise(child), f"swap {li}/{n.id or 'root'}"


def mutate_rotate(root: dom.Node, rng: np.random.Generator,
                  types: list[str], base_p: float = 1.0) -> tuple[dom.Node, str]:
    # re-orient a live cut; live rotation = node without a below link (base
    # storey or inside an upper-storey divide delta)
    child = copy.deepcopy(root)
    cands = [(li, n) for li, n in _owned_branches(child) if n.below is None]
    if not cands:
        return _finalise(child), "rotate noop"
    li, n = _pick_weighted_by_storey(rng, cands, base_p)
    n.rotation = (n.rotation + int(rng.integers(1, 4))) % 4
    return _finalise(child), f"rotate {li}/{n.id or 'root'}"


def mutate_level_fix(root: dom.Node, rng: np.random.Generator,
                     types: list[str], reqs=None) -> tuple[dom.Node, str]:
    """Atomically move a level-constrained room to its required floor.

    Finds a room type with a ``level: N`` constraint that currently sits on the
    wrong storey.  Retypes the LARGEST leaf on the required floor to that room,
    and retypes the vacated wrong-floor leaf to a generic (C or O).  Does not
    undivide anything, so the size may still be suboptimal — the inner NM loop
    fixes geometry, and subsequent core_divide / retype mutations fill in any
    displaced rooms.

    Requires ``reqs`` (dict[str, SpaceReq] from programme.load_programme_dir).
    """
    if not reqs:
        return _finalise(copy.deepcopy(root)), "level_fix noop"

    from . import geometry as _geo

    level_types = {code: req.level for code, req in reqs.items()
                   if getattr(req, "level", None) is not None}
    if not level_types:
        return _finalise(copy.deepcopy(root)), "level_fix noop"

    child = copy.deepcopy(root)
    lvls = dom.levels(child)

    violations = [
        (li, lf, code, req_level)
        for code, req_level in level_types.items()
        for li, lvl in enumerate(lvls)
        for lf in lvl.leaves()
        if lf.type == code and li != req_level
    ]
    if not violations:
        return _finalise(child), "level_fix noop"

    li_wrong, wrong_leaf, code, req_level = _pick(rng, violations)
    if req_level >= len(lvls):
        return _finalise(child), "level_fix noop"

    correct_leaves = lvls[req_level].leaves()
    if not correct_leaves:
        return _finalise(child), "level_fix noop"

    # Pick the largest leaf on the correct floor as the best landing spot
    target = max(correct_leaves, key=lambda lf: _geo.area(lf))
    target.type = code

    generics = [t for t in types if t.upper() in ("C", "O")]
    wrong_leaf.type = str(rng.choice(generics)) if generics else "C"

    return _finalise(child), (
        f"level_fix {code}: lvl{li_wrong}/{wrong_leaf.id or 'root'}"
        f" → lvl{req_level}/{target.id or 'root'}"
    )


def mutate_level_compound_fix(root: dom.Node, rng: np.random.Generator,
                              types: list[str], reqs=None) -> tuple[dom.Node, str]:
    """Compound level fix: move level-constrained room + re-insert displaced room.

    Extends level_fix: after landing the constrained room (e.g. l1) on its
    required floor, the displaced room (e.g. t3) is re-inserted by splitting
    the SIBLING of the largest C leaf on that floor.  The C sibling is always
    geometrically adjacent to C (they share the same parent split), so the
    displaced room inherits that adjacency.  Division is applied to the target
    floor only (not core-divide style), since the displaced room only needs to
    appear on its required floor.

    This avoids the 5-fail "missing t3" penalty that level_fix alone causes
    when the landing spot displaces a required room.
    """
    if not reqs:
        return _finalise(copy.deepcopy(root)), "level_compound_fix noop"

    from . import geometry as _geo

    level_types = {code: req.level for code, req in reqs.items()
                   if getattr(req, "level", None) is not None}
    if not level_types:
        return _finalise(copy.deepcopy(root)), "level_compound_fix noop"

    child = copy.deepcopy(root)
    lvls = dom.levels(child)

    violations = [
        (li, lf, code, req_level)
        for code, req_level in level_types.items()
        for li, lvl in enumerate(lvls)
        for lf in lvl.leaves()
        if lf.type == code and li != req_level
    ]
    if not violations:
        return _finalise(child), "level_compound_fix noop"

    li_wrong, wrong_leaf, code, req_level = _pick(rng, violations)
    if req_level >= len(lvls):
        return _finalise(child), "level_compound_fix noop"

    correct_leaves = lvls[req_level].leaves()
    if not correct_leaves:
        return _finalise(child), "level_compound_fix noop"

    target = max(correct_leaves, key=lambda lf: _geo.area(lf))
    displaced_type = target.type

    # Apply level_fix part
    target.type = code
    generics = [t for t in types if t.upper() in ("C", "O")]
    wrong_leaf.type = str(rng.choice(generics)) if generics else "C"

    desc = (f"level_compound_fix {code}: lvl{li_wrong} → lvl{req_level}/{target.id or 'root'}")

    # Re-insert displaced room if it was a named room
    if displaced_type and displaced_type.upper() not in ("C", "O", "S"):
        displaced_req = reqs.get(displaced_type)
        displaced_level = getattr(displaced_req, "level", None) if displaced_req else None
        insert_level = displaced_level if displaced_level is not None else req_level

        lvls = dom.levels(child)
        # Find C-sibling pairs: (parent, sibling_of_C) on insert_level.
        # The sibling of a C leaf shares a parent split → guaranteed adjacent to C.
        # Pick the largest such sibling as the host for the displaced room.
        sibling_cands: list[dom.Node] = []
        for li2, n in _owned_branches(child):
            if li2 != insert_level:
                continue
            l_is_c = n.left.type and n.left.type.upper() == "C" and not n.left.divided
            r_is_c = n.right.type and n.right.type.upper() == "C" and not n.right.divided
            if l_is_c and not n.right.divided and n.right.id:
                sibling_cands.append(n.right)
            if r_is_c and not n.left.divided and n.left.id:
                sibling_cands.append(n.left)

        if sibling_cands:
            host = max(sibling_cands, key=lambda lf: _geo.area(lf))
            host_path = host.id

            node = lvls[insert_level].by_id(host_path)
            if node is not None and not node.divided:
                host_orig_type = node.type
                # rotation=0 (vertical left-right split): left child neighbours C;
                # displaced room goes left (small), host type preserved right (large).
                # Inner NM tunes the exact split ratio.
                node.division = [0.25, 0.25]
                node.rotation = 0
                node.left = dom.Node(type=displaced_type)  # small, adjacent to C
                node.right = dom.Node(type=host_orig_type)  # large, preserves host
                node.type = None

            desc += f" + insert {displaced_type} into {host_path}/lvl{insert_level}"

    return _finalise(child), desc


def _programme_codes(reqs) -> dict:
    """Required programme spaces only (drop generic circulation/outside/sahn)."""
    return {c: r for c, r in reqs.items() if not dom.is_generic(c)}


def mutate_place_missing(root: dom.Node, rng: np.random.Generator,
                         types: list[str], reqs=None) -> tuple[dom.Node, str]:
    """Repair operator: insert a required-but-absent space (DESIGN.md §11.2).

    Detects a missing required room via ``graph.check_space_counts`` and inserts
    one instance by dividing a host leaf into ``[new room | remainder]``.  Lex-
    safety (cf. the §4.10 deceptive-valley lesson): the host is chosen to *not*
    create more new fails than the missing-stack it removes — generic ``O``
    leaves are preferred (unbounded, no "too many", nothing displaced), then
    other non-required leaves; a required room is never displaced.  The new room
    is forced onto its required storey when the programme constrains its level.
    """
    if not reqs:
        return _finalise(copy.deepcopy(root)), "place_missing noop"

    from . import geometry as _geo, graph as _graph

    child = copy.deepcopy(root)
    _failures, missing = _graph.check_space_counts(child, reqs)
    if not missing:
        return _finalise(child), "place_missing noop"

    mid = _pick(rng, missing)
    code = mid.split("#")[0]
    req = reqs.get(code)
    target_level = getattr(req, "level", None)
    lvls = dom.levels(child)
    if target_level is not None and target_level < len(lvls):
        host_levels = [target_level]
    else:
        host_levels = list(range(len(lvls)))

    # Rank candidate hosts: 0 = generic outside (safest — nothing displaced),
    # 1 = other non-required leaf, 2 = circulation/stair (carve only as last
    # resort — disrupts the core). Required rooms are never candidates.
    cands: list[tuple[int, float, dom.Node]] = []
    for li in host_levels:
        for leaf in lvls[li].leaves():
            if not leaf.type:
                continue
            if leaf.type == "O":
                pref = 0
            elif leaf.type in ("C", "S"):
                pref = 2
            elif leaf.type in reqs:
                continue
            else:
                pref = 1
            cands.append((pref, _geo.area(leaf), leaf))

    if cands:
        best_pref = min(p for p, _, _ in cands)
        pool = [(a, lf) for p, a, lf in cands if p == best_pref]
        _, host = max(pool, key=lambda x: x[0])
        keep = host.type if host.type not in dom.GENERIC_OUTSIDE else "O"
    else:
        # No safe host on the required storey — split its largest leaf and
        # preserve that leaf's type on the large side.
        all_leaves = [lf for li in host_levels for lf in lvls[li].leaves()]
        if not all_leaves:
            return _finalise(child), "place_missing noop"
        host = max(all_leaves, key=_geo.area)
        keep = host.type or "O"

    host_id = host.id or "root"
    # New room small (left, adjacent to remainder); inner NM tunes the ratio.
    host.division = [0.3, 0.3]
    host.rotation = int(rng.integers(4))
    host.left = dom.Node(type=code)
    host.right = dom.Node(type=keep)
    host.type = None
    return _finalise(child), f"place_missing {code} -> {host_id}"


def mutate_bridge_circulation(root: dom.Node, rng: np.random.Generator,
                              types: list[str], reqs=None) -> tuple[dom.Node, str]:
    """Repair operator (homemaker-py-8sh): retype the leaves on the cheapest
    path between two circulation components to circulation, directly clearing
    a ``level N not connected`` fail (``graph.connected_circulation``).

    Follow-on to homemaker-py-qi6 mechanism (a). Mechanism (b)/(c) — a graded
    circulation-connectivity comparator key (DESIGN.md §18) — measured
    NEGATIVE: it never fired on harbor-house and never cleared a genuine
    not-connected fail on programme-house, because the outer search rarely
    hits the fail-count tie the grade needs to break. This operator does not
    depend on a tie: for each storey it finds the two circulation components
    (``graph.build_graphs``' per-leaf adjacency, restricted to
    ``dom.is_circulation`` leaves) joined by the shortest, least-disruptive
    path and retypes the intermediate leaves to ``C``. Path cost prefers
    generic outside (``O``) leaves (free — nothing displaced, same rationale
    as ``mutate_place_missing``'s host ranking), then other non-required
    leaves, and only crosses a required programme room (from ``reqs``) if no
    other route exists. A displaced required room becomes a missing-space
    fail for ``mutate_place_missing`` to re-insert elsewhere on a later step,
    the same division of labour ``mutate_deslim`` uses.
    """
    import networkx as nx

    from . import geometry as _geo, graph as _graph

    child = copy.deepcopy(root)
    lvls = dom.levels(child)

    def _cost(n: dom.Node) -> int:
        if dom.is_circulation(n):
            return 0
        if not n.type:
            return 1
        if n.type in dom.GENERIC_OUTSIDE:
            return 0
        if reqs and n.type in reqs:
            return 5
        return 1

    per_level: list[tuple[int, list[dom.Node]]] = []
    for li, lvl in enumerate(lvls):
        G = _geo.leaf_graph(lvl, _graph.DOOR_WIDTH)
        circ = [n for n in G.nodes() if dom.is_circulation(n)]
        if not circ:
            continue
        comps = list(nx.connected_components(G.subgraph(circ)))
        if len(comps) <= 1:
            continue
        # Node cost split across its edges (average of endpoint costs) so a
        # weighted shortest path sums to (approximately) total intermediate-
        # leaf conversion cost — a plain hop-count shortest path would pick an
        # arbitrary same-length route and could cross a required room even
        # when an equal-length free ('O') route exists.
        weighted = G.copy()
        for u, v, data in weighted.edges(data=True):
            data["bridge_weight"] = (_cost(u) + _cost(v)) / 2.0
        best_path: list[dom.Node] | None = None
        best_weight = None
        for i in range(len(comps)):
            for j in range(i + 1, len(comps)):
                tmp = weighted.copy()
                tmp.add_node("SRC")
                tmp.add_node("DST")
                tmp.add_edges_from(("SRC", n, {"bridge_weight": 0.0}) for n in comps[i])
                tmp.add_edges_from(("DST", n, {"bridge_weight": 0.0}) for n in comps[j])
                try:
                    weight, path = nx.single_source_dijkstra(
                        tmp, "SRC", "DST", weight="bridge_weight")
                except nx.NetworkXNoPath:
                    continue
                if best_weight is None or weight < best_weight:
                    between = [n for n in path[1:-1]
                               if n not in comps[i] and n not in comps[j]]
                    best_weight, best_path = weight, between
        if best_path:
            per_level.append((li, best_path))

    if not per_level:
        return _finalise(child), "bridge_circulation noop"

    li, path = _pick(rng, per_level)
    for leaf in path:
        leaf.type = "C"
    names = ",".join(leaf.id or "root" for leaf in path)
    return _finalise(child), f"bridge_circulation lvl{li}: {names} -> C"


def repair_circulation_settled(lvl: dom.Node, reqs, max_bridges: int = 8) -> int:
    """Reconnect a storey's circulation AFTER the geometry has settled.

    homemaker-py-yql (DESIGN.md §39.9). ``_assign_adjacency_aware`` picks
    circulation as a CONNECTED dominating set, but it does so against the
    pre-resize geometry; ``_size_divisions_from_targets`` then moves every wall
    to hit the programme's area targets and the shared boundaries the dominating
    set relied on shrink below ``door_width`` or vanish outright. Measured on
    health-centre: 41 of 49 circulation-to-circulation edges destroyed by the
    resize, surviving shared walls squeezed to 0.54-1.11 m against a 1.2 m
    threshold — so only 5% of constructed seeds started connected, against 100%
    with the resize disabled.

    This is the same alternating-minimisation fix §37.7 applied to room
    assignment (``_cpsat_relabel_settled``): re-run the step against the
    geometry that actually resulted. Retypes the cheapest bridging leaves to
    ``C``, preferring generic outside, then unassigned, and crossing a required
    room last — the cost model ``mutate_bridge_circulation`` already uses.

    Returns the number of leaves retyped. Idempotent once connected.
    """
    import networkx as nx

    from . import geometry as _geo, graph as _graph

    def _cost(node: dom.Node) -> int:
        if dom.is_circulation(node):
            return 0
        if not node.type:
            return 1
        if node.type in dom.GENERIC_OUTSIDE:
            return 0
        if reqs and node.type in reqs:
            return 5
        return 1

    retyped = 0
    for _ in range(max_bridges):
        _geo.clear_cache()
        G = _geo.leaf_graph(lvl, _graph.DOOR_WIDTH)
        circ = [x for x in G.nodes() if dom.is_circulation(x)]
        if not circ:
            return retyped
        comps = list(nx.connected_components(G.subgraph(circ)))
        if len(comps) <= 1:
            return retyped
        weighted = G.copy()
        for u, v, data in weighted.edges(data=True):
            data["bridge_weight"] = (_cost(u) + _cost(v)) / 2.0
        best_path = None
        best_weight = None
        for i in range(len(comps)):
            for j in range(i + 1, len(comps)):
                for a in comps[i]:
                    for b in comps[j]:
                        try:
                            path = nx.shortest_path(weighted, a, b,
                                                    weight="bridge_weight")
                        except nx.NetworkXNoPath:
                            continue
                        w = sum(_cost(x) for x in path[1:-1])
                        if best_weight is None or w < best_weight:
                            best_weight, best_path = w, path
        if not best_path:
            return retyped
        middle = [x for x in best_path[1:-1] if not dom.is_circulation(x)]
        if not middle:
            return retyped          # components already touch; nothing to retype
        for leaf in middle:
            leaf.type = "C"
            retyped += 1
    return retyped


def _shape_failing(leaf: dom.Node, fit) -> bool:
    """A named-room leaf whose width or proportion factor actually fails
    (``< fitness.FAIL_THRESHOLD``) under ``fit``, the same Gaussian quality
    functions the scorer uses (``Fitness.quality_width``/``quality_proportion``)
    — not a geometric proxy, which over-flags leaves the gaussian tail still
    passes. Generic circulation/outside/sahn leaves are never candidates —
    they absorb slack by design (solver.py ``min_width_generic``), not a
    repair target."""
    if dom.is_generic(leaf.type) or not leaf.type:
        return False
    from . import fitness as _fit_mod

    return (fit.quality_width(leaf) < _fit_mod.FAIL_THRESHOLD
            or fit.quality_proportion(leaf) < _fit_mod.FAIL_THRESHOLD)


def mutate_shape_rotate(root: dom.Node, rng: np.random.Generator,
                        types: list[str], fit=None) -> tuple[dom.Node, str]:
    """Repair operator (homemaker-py-7fm): re-orient the cut that produced a
    shape-failing (long-thin) leaf.

    Diagnosis (bd memory, 7fm): re-running the full-fitness ratio inner loop
    with a large budget does not clear these fails — they are not local optima
    of the ratio, because the offending leaf is the *thin* side of a cut whose
    orientation runs parallel to its parent rectangle's long axis, so any ratio
    value on that axis yields a thin sliver. Rotating the defining (live) cut
    changes which axis the ratio divides; the inner loop then re-tunes the
    ratio on the new axis. Targets only the cut that actually produced a
    failing leaf, unlike the untargeted ``mutate_rotate``. Requires ``fit``
    (a ``fitness.Fitness``) to identify genuinely failing leaves.
    """
    if fit is None:
        return _finalise(copy.deepcopy(root)), "shape_rotate noop"
    child = copy.deepcopy(root)
    cands: list[tuple[int, dom.Node, dom.Node]] = []
    for li, n in _owned_branches(child):
        if n.below is not None:
            continue
        for side in ("l", "r"):
            leaf = n.left if side == "l" else n.right
            if not leaf.divided and _shape_failing(leaf, fit):
                cands.append((li, n, leaf))
    if not cands:
        return _finalise(child), "shape_rotate noop"
    li, n, leaf = _pick(rng, cands)
    n.rotation = (n.rotation + int(rng.integers(1, 4))) % 4
    return _finalise(child), f"shape_rotate {li}/{n.id or 'root'} (fixing {leaf.id})"


def mutate_deslim(root: dom.Node, rng: np.random.Generator,
                  types: list[str], fit=None) -> tuple[dom.Node, str]:
    """Repair operator (homemaker-py-7fm): merge a shape-failing (long-thin)
    leaf into its sibling, undoing the division that starved it.

    Unlike ``mutate_shape_rotate`` this addresses cuts whose *area* share is
    wrong (an upstream branch several levels up gave the whole subtree too
    little area to satisfy every leaf inside it — no ratio or rotation on the
    local cut can fix that, bd memory 7fm), not just its orientation. The
    displaced room becomes a missing-space fail that ``mutate_place_missing``
    (already in ``MUTATIONS``) re-inserts elsewhere on a later step. Requires
    ``fit`` (a ``fitness.Fitness``) to identify genuinely failing leaves.
    """
    if fit is None:
        return _finalise(copy.deepcopy(root)), "deslim noop"
    from . import geometry as _geo

    child = copy.deepcopy(root)
    cands = [
        (li, n) for li, n in _owned_branches(child)
        if not n.left.divided and not n.right.divided
        and (_shape_failing(n.left, fit) or _shape_failing(n.right, fit))
    ]
    if not cands:
        return _finalise(child), "deslim noop"
    li, n = _pick(rng, cands)
    l_fail, r_fail = _shape_failing(n.left, fit), _shape_failing(n.right, fit)
    if l_fail and not r_fail:
        survivor = n.right
    elif r_fail and not l_fail:
        survivor = n.left
    else:
        survivor = max((n.left, n.right), key=_geo.area)
    n.type = survivor.type if not dom.is_generic(survivor.type) and survivor.type else "C"
    n.division = None
    n.left = n.right = None
    return _finalise(child), f"deslim {li}/{n.id or 'root'} (kept {n.type})"


def _leaves_with_depth(n: dom.Node, d: int = 0) -> list[tuple[dom.Node, int]]:
    """Every leaf under ``n`` paired with its depth below ``n``."""
    if not n.divided:
        return [(n, d)]
    return _leaves_with_depth(n.left, d + 1) + _leaves_with_depth(n.right, d + 1)


def _grow_leaves(lvl: dom.Node, n_leaves: int, rng: np.random.Generator,
                 balance: bool = False) -> None:
    """Subdivide ``lvl``'s subtree in place until it has ``n_leaves`` leaves.

    ``balance`` (erc.4, §13.4): always split a *shallowest* current leaf, growing
    a near-complete binary tree instead of the default random caterpillar. Diag B
    (§13.2) localized the size fails to depth-driven MALDISTRIBUTION — leaf area is
    set by the product of cut fractions down its ancestry, so a random unbalanced
    tree lands equal-target rooms at depths that differ by many levels (same code
    seen at 0.05× and 14.7× target). Keeping all leaves at comparable depth lets
    the proportion-aware sizing pass hit each target with cut fractions near their
    proportional value, instead of compounding fmin/fmax clamp error down a deep
    spine."""
    while len(lvl.leaves()) < n_leaves:
        if balance:
            ld = _leaves_with_depth(lvl)
            dmin = min(d for _l, d in ld)
            leaf = _pick(rng, [l for l, d in ld if d == dmin])
        else:
            leaf = _pick(rng, lvl.leaves())
        leaf.division = [0.5, 0.5]
        leaf.rotation = int(rng.integers(4))
        leaf.left = dom.Node(type=leaf.type)
        leaf.right = dom.Node(type=leaf.type)
        leaf.type = None


def _share_grain(req, share_factor: int) -> int:
    """Per-code leaf-sharing grain (homemaker-py-x3b, §13.3).

    Returns the maximum number of same-code rooms that may collapse into one
    shared leaf, or 1 when the code must not be shared. Only sized codes are ever
    shareable (an unsized circulation/outside code absorbs slack and has no target
    to centre k rooms on). ``share_factor`` is the global selector:

    - ``0`` — per-code opt-in: a code is shared iff it carries an explicit
      ``share: N`` (>=2); everything else stays unshared. This is the safe
      default-on philosophy — the programme author chooses per space.
    - ``>=2`` — global mode: every sized code shares at grain ``share_factor``,
      except codes with an explicit ``share`` which overrides it (``share: 1``
      opts the code OUT, ``share: N`` sets that code's grain to N). This
      reproduces the §13.3 experiment without editing example programmes.
    """
    if req is None or not (req.has_size and req.size > 0):
        return 1
    if share_factor == 0:
        return req.share if req.has_share else 1
    return req.share if req.has_share else share_factor


def _share_rooms(rooms: list[str], reqs,
                 share_factor: int) -> tuple[list[str], dict[str, list[int]]]:
    """Collapse same-code room instances into fewer, larger shared leaves (erc.3).

    Each shareable code in ``rooms`` (grain from :func:`_share_grain`) is grouped
    into runs of up to its grain → one leaf per run carrying that run's
    multiplicity. Returns ``(reduced_codes, mult_plan)`` where ``reduced_codes``
    is the new per-leaf code list (fewer entries) and ``mult_plan[code]`` lists
    the multiplicities of that code's leaves (summing to the original count).
    Circulation/outside and single-instance, non-sized, or opted-out codes are
    untouched (multiplicity 1), so they cannot incur a missing fail under sharing.
    """
    from collections import Counter

    counts = Counter(rooms)
    reduced: list[str] = []
    plan: dict[str, list[int]] = {}
    for code in counts:
        c = counts[code]
        grain = _share_grain(reqs.get(code) if reqs else None, share_factor)
        if grain < 2 or c < 2:
            mults = [1] * c
        else:
            mults, remaining = [], c
            while remaining > 0:
                m = min(grain, remaining)
                mults.append(m)
                remaining -= m
        plan[code] = mults
        reduced.extend([code] * len(mults))
    return reduced, plan


def _leaf_mult_from_plan(lvl: dom.Node, plan: dict[str, list[int]]) -> dict:
    """Stamp each typed leaf with its share multiplicity from a ``_share_rooms``
    plan and return a leaf→multiplicity map for sizing.

    Sets ``leaf.share = k`` and ``leaf.share_type = leaf.type`` (the explicit,
    type-guarded multiplicity the fitness reads, §13.3) on shared leaves, and
    returns ``{leaf: k}`` so ``_size_divisions_from_targets`` sizes them to
    k×target. Bigger multiplicities go to whichever leaves already read largest,
    so the proportional sizing pass has the least work to do. Defensive against a
    leaf count that differs from the plan (assignment dropped/added a slot):
    extra leaves stay multiplicity 1, surplus plan entries are ignored."""
    from . import geometry
    by_code: dict[str, list[dom.Node]] = {}
    for lf in lvl.leaves():
        if lf.type:
            by_code.setdefault(lf.type, []).append(lf)
    leaf_mult: dict = {}
    for code, mults in plan.items():
        leaves = sorted(by_code.get(code, []), key=geometry.area, reverse=True)
        for lf, m in zip(leaves, sorted(mults, reverse=True)):
            if m > 1:
                leaf_mult[lf] = m
                lf.share = m
                lf.share_type = lf.type
    return leaf_mult


def _colocate_rooms(rooms: list[str], colocate_pairs,
                    rng: np.random.Generator) -> tuple[list[str], dict[str, list[str]]]:
    """Fuse single instances of DIFFERENT compatible codes onto one leaf
    (homemaker-py-1s3, §26 path b) — the same structural lever as
    ``_share_rooms`` (fewer, larger leaves), extended from *same*-code
    multiplicity to *different*-but-compatible codes.

    For each valid declared pair (``programme.derive_colocate_pairs``, order
    shuffled via ``rng``), pair up ``n = min(available a, available b)``
    instances: one code is chosen (via ``rng``, once per pair — NOT
    re-rolled per instance, which would let a code flip between primary and
    secondary roles across iterations and over-pair beyond what's actually
    available) as the "secondary" and fully removed (``n`` instances), the
    other (the "primary") keeps its slot in ``rooms`` unchanged and gets ``n``
    entries in ``plan``. A primary code may accumulate several secondaries
    from different declared pairs; ``_leaf_colocate_from_plan`` matches each
    to a distinct physical leaf. Codes with no available partner are
    untouched.
    """
    from collections import Counter

    counts = Counter(rooms)
    plan: dict[str, list[str]] = {}
    pairs = list(colocate_pairs)
    order = [pairs[i] for i in rng.permutation(len(pairs))] if pairs else []
    for pair in order:
        a, b = sorted(pair)
        n = min(counts[a], counts[b])
        if n <= 0:
            continue
        primary, secondary = (a, b) if rng.integers(2) == 0 else (b, a)
        counts[secondary] -= n
        plan.setdefault(primary, []).extend([secondary] * n)

    reduced: list[str] = []
    for code, c in counts.items():
        reduced.extend([code] * c)
    return reduced, plan


def _leaf_colocate_from_plan(lvl: dom.Node, plan: dict[str, list[str]], reqs) -> dict:
    """Stamp each plan's secondary codes onto that primary code's typed
    leaves (mirrors ``_leaf_mult_from_plan``) and return a leaf→co_type map
    for sizing. Secondaries are matched biggest-target-first to biggest-area
    leaves first, same descending-to-descending heuristic as leaf-sharing."""
    from . import geometry
    by_code: dict[str, list[dom.Node]] = {}
    for lf in lvl.leaves():
        if lf.type:
            by_code.setdefault(lf.type, []).append(lf)
    leaf_co: dict = {}
    for code, secondaries in plan.items():
        leaves = sorted(by_code.get(code, []), key=geometry.area, reverse=True)
        secs = sorted(secondaries, key=lambda c: reqs[c].size if c in reqs else 0.0,
                      reverse=True)
        for lf, co in zip(leaves, secs):
            lf.co_type = co
            leaf_co[lf] = co
    return leaf_co


def _size_divisions_from_targets(lvl: dom.Node, reqs, fmin: float = 0.04,
                                 fmax: float = 0.96, leaf_mult: dict | None = None,
                                 leaf_extra: dict | None = None) -> None:
    """Resize each divided node's split ratio from its leaves' TARGET areas.

    leu.2 (DESIGN.md §12.2, follow-up to §11.6/§11.7): the constructive seeders
    grow geometry with uniform ``[0.5, 0.5]`` cuts *before* types are assigned, so
    the raw seed is "more, smaller leaves" of equal area — rooms with a large
    programme target come out too small, small rooms too big, and the inner loop
    must recover all of size/width/proportion from scratch. Once types are known,
    every leaf carries a target area (a sized room's ``size``; circulation/outside
    absorb the slack), and because ``division=[f, f]`` cuts off left area-fraction
    ``f`` (rotation-independent), bottom-up target sums compose multiplicatively to
    give every leaf area ∝ its target.

    Area alone is not enough: choosing only the cut *fraction* to hit a target
    *area* slices thin slivers with terrible aspect (proportion/width/edge-too-long
    fails swamp the size gain — measured, §12.2). So each cut also picks the
    **rotation** (the two distinct cut directions) that makes its two children
    squarest. Rotation depends on the realised parent geometry, so the pass runs
    *top-down*; both the ratio and the rotation derive from the target dims, and
    neither touches topology or type assignment (§11.6/§11.7 placement is intact).

    Generic (non-sized) leaves get a nominal target: the per-leaf share of the
    plot slack, floored at ``0.4 ×`` mean room target so a circulation leaf never
    shrinks to a sub-door-width sliver (which would undo the §11.6 adjacency win).
    """
    from . import geometry

    reqs = reqs or {}
    geometry.clear_cache()
    leaves = lvl.leaves()
    if len(leaves) < 2:
        return

    leaf_mult = leaf_mult or {}
    leaf_extra = leaf_extra or {}
    sized = {lf: reqs[lf.type].size * leaf_mult.get(lf, 1) + leaf_extra.get(lf, 0.0)
             for lf in leaves if lf.type in reqs and reqs[lf.type].size > 0}
    mean_sized = (sum(sized.values()) / len(sized)) if sized else 1.0
    n_generic = len(leaves) - len(sized)
    slack = geometry.area(lvl) - sum(sized.values())
    floor = 0.4 * mean_sized  # keep circulation/outside above door-width scale
    generic_t = max(floor, slack / n_generic) if n_generic else floor
    target = {lf: sized.get(lf, generic_t) for lf in leaves}

    def _subtree_target(n: dom.Node) -> float:
        if not n.divided:
            return max(target.get(n, floor), 1e-6)
        return _subtree_target(n.left) + _subtree_target(n.right)

    def _rec(n: dom.Node) -> None:
        if not n.divided:
            return
        left = _subtree_target(n.left)
        f = min(max(left / (left + _subtree_target(n.right)), fmin), fmax)
        # Pick the cut direction (rotation 0 vs 1; 2/3 mirror these for aspect)
        # that makes the worse child squarest, given this node's settled geometry.
        best_rot, best_aspect = n.rotation, None
        for rot in (0, 1):
            n.rotation = rot
            n.division = [f, f]
            geometry.clear_cache()
            worst = max(geometry.aspect(n.left), geometry.aspect(n.right))
            if best_aspect is None or worst < best_aspect:
                best_aspect, best_rot = worst, rot
        n.rotation = best_rot
        n.division = [f, f]
        geometry.clear_cache()
        _rec(n.left)
        _rec(n.right)

    _rec(lvl)
    geometry.clear_cache()


def _circ_components(lvl: dom.Node) -> int:
    """Number of connected components among this storey's circulation leaves."""
    import networkx as nx

    from . import geometry as _geo, graph as _graph

    _geo.clear_cache()
    G = _geo.leaf_graph(lvl, _graph.DOOR_WIDTH)
    circ = [x for x in G.nodes() if dom.is_circulation(x)]
    if not circ:
        return 0
    return nx.number_connected_components(G.subgraph(circ))


def _circ_edges(lvl: dom.Node) -> list[tuple]:
    """Circulation-to-circulation adjacencies on this storey, as leaf pairs."""
    from . import geometry as _geo, graph as _graph

    _geo.clear_cache()
    G = _geo.leaf_graph(lvl, _graph.DOOR_WIDTH)
    return [(a, b) for a, b in G.edges()
            if dom.is_circulation(a) and dom.is_circulation(b)]


def _circ_edge_absent(lvl: dom.Node, a: dom.Node, b: dom.Node) -> bool:
    from . import geometry as _geo, graph as _graph

    _geo.clear_cache()
    G = _geo.leaf_graph(lvl, _graph.DOOR_WIDTH)
    return not (G.has_node(a) and G.has_node(b) and G.has_edge(a, b))


def _size_divisions_preserving_circulation(lvl: dom.Node, reqs,
                                           max_reverts: int = 12, **kw) -> int:
    """Resize toward the programme's area targets WITHOUT severing circulation.

    homemaker-py-3z0 (DESIGN.md §39.10). ``_assign_adjacency_aware`` picks
    circulation as a CONNECTED dominating set, then
    ``_size_divisions_from_targets`` re-cuts every node — new ratio *and* new
    rotation — and the shared boundaries the dominating set relied on shrink
    below ``door_width`` or vanish. Measured (§39.9): fully-connected constructed
    seeds 1/20, 1/20, 0/20 across the corpus, against 100% with the resize
    skipped entirely. Both halves of the re-cut do damage, in different
    proportions per programme — on health-centre it is entirely the ratio, on
    maple-court mostly the rotation — so a fix has to be able to give back
    either.

    Rather than rebuild the connection afterwards by retyping rooms to ``C``
    (measured a net loss — it displaces required rooms at a 3-5 fail cascade
    each, §39.9), this gives back the *geometry* and keeps the programme intact:
    snapshot every cut, resize, then greedily revert whichever single cut most
    reduces the circulation component count until the storey is connected again.
    Reverting a cut costs only the area-target accuracy of that one subtree, and
    the inner loop optimises ratios anyway — nothing is displaced and no label
    changes.

    Returns the number of cuts reverted.
    """
    from . import geometry as _geo

    nodes = []

    def _walk(node: dom.Node) -> None:
        if node.divided:
            nodes.append(node)
            _walk(node.left)
            _walk(node.right)

    _walk(lvl)
    before = {id(x): (x.rotation, list(x.division) if x.division else None)
              for x in nodes}
    _pre_circ_edges = _circ_edges(lvl)

    _size_divisions_from_targets(lvl, reqs, **kw)

    if _circ_components(lvl) <= 1:
        _geo.clear_cache()
        return 0

    # Which circulation pairs were adjacent BEFORE the re-cut and are not now?
    # Those are the connections the resize broke, and the cuts that govern each
    # are exactly the ones between the two leaves — so revert those, rather than
    # hunting for a single cut that happens to reduce the component count. A
    # plain greedy gets stuck: often no ONE revert helps even though two would.
    def _paths_between(a: dom.Node, b: dom.Node) -> list[dom.Node]:
        """Divided nodes on the tree path joining two leaves (via their LCA)."""
        def _chain(x: dom.Node) -> list[dom.Node]:
            out = []
            while x is not None:
                out.append(x)
                x = x.parent
            return out
        ca, cb = _chain(a), _chain(b)
        common = set(map(id, cb))
        lca = next((x for x in ca if id(x) in common), None)
        if lca is None:
            return []
        seen, out = set(), []
        for chain in (ca, cb):
            for x in chain:
                if x.divided and id(x) not in seen:
                    out.append(x)
                    seen.add(id(x))
                if x is lca:
                    break
        return out

    broken = [(a, b) for a, b in _pre_circ_edges
              if _circ_edge_absent(lvl, a, b)]
    reverted = 0
    for a, b in broken:
        if _circ_components(lvl) <= 1 or reverted >= max_reverts:
            break
        for node in _paths_between(a, b):
            rot, div = before.get(id(node), (None, None))
            if div is None or (node.rotation == rot and node.division == div):
                continue
            node.rotation, node.division = rot, list(div)
            reverted += 1
    _geo.clear_cache()
    return reverted


def _grow_balanced(node: dom.Node, code: str, k: int) -> None:
    """Turn ``node`` (a leaf) into a balanced binary subtree of ``k`` leaves, all
    typed ``code``. Split ratio/rotation are placeholders ([0.5,0.5], rot 0);
    ``_size_subtree_equal`` settles them from realised geometry afterwards."""
    if k < 2:
        node.type = code
        node.share = 1
        node.share_type = None
        return
    kl = k // 2
    node.type = None
    node.share = 1
    node.share_type = None
    node.division = [0.5, 0.5]
    node.rotation = 0
    node.left = dom.Node()
    node.right = dom.Node()
    _grow_balanced(node.left, code, kl)
    _grow_balanced(node.right, code, k - kl)


def _size_subtree_equal(node: dom.Node) -> None:
    """Size a freshly-grown balanced subtree (all leaves equal target) so each
    cut splits by leaf-count fraction and picks the rotation that makes its
    children squarest, given the subtree root's *settled* outer geometry. Unlike
    ``_size_divisions_from_targets`` this touches only ``node``'s subtree, so the
    unfold leaves every sibling leaf's evolved geometry untouched."""
    from . import geometry

    def _nleaves(n: dom.Node) -> int:
        return 1 if not n.divided else _nleaves(n.left) + _nleaves(n.right)

    def _rec(n: dom.Node) -> None:
        if not n.divided:
            return
        nl, nr = _nleaves(n.left), _nleaves(n.right)
        f = nl / (nl + nr)
        best_rot, best_aspect = n.rotation, None
        for rot in (0, 1):
            n.rotation = rot
            n.division = [f, f]
            geometry.clear_cache()
            worst = max(geometry.aspect(n.left), geometry.aspect(n.right))
            if best_aspect is None or worst < best_aspect:
                best_aspect, best_rot = worst, rot
        n.rotation = best_rot
        n.division = [f, f]
        geometry.clear_cache()
        _rec(n.left)
        _rec(n.right)

    _rec(node)


def unfold_shared_leaves(root: dom.Node, above: int = 1) -> int:
    """Materialise every live shared leaf into ``k`` distinct sibling leaves.

    homemaker-py-yaa: at the sharing→no-sharing phase change a leaf carrying
    ``share=k`` credits k same-code programme rooms but is a single physical
    space, so a de-shared genome starts k−1 rooms short per shared leaf — a deep
    'missing required space (critical)' hole that place_missing/divide dig out of
    only slowly (measured: naive warm-start from a sharing seed stalled ~60× worse
    than the direct no-sharing route). This replaces each live shared leaf
    (``share>1`` and ``share_type==type``) with a balanced binary subtree of k
    leaves of the SAME code, splitting the footprint into k equal-target children,
    then sizes each new subtree for squarest proportions. Share stamps are
    cleared and topology (adjacency skeleton) is otherwise preserved. Returns the
    number of extra leaves created (materialisation deficit paid down).

    ``above`` (homemaker-py-kpu, Schedule B grain ramp): unfold only leaves whose
    ``share`` *exceeds* this grain cap, leaving smaller-share leaves collapsed for
    the next (lower) grain. ``above=1`` (default) unfolds every shared leaf, the
    full materialisation the single-transition finish (§15) uses. At grain step
    ``g``, ``above=g`` materialises exactly the leaves the new evaluator cap
    (``leaf_share_max=g``) would under-credit, so no fresh missing fail appears."""
    from . import geometry

    grown: list[dom.Node] = []
    created = 0
    for lvl in dom.levels(root):
        for leaf in lvl.leaves():
            if leaf.share > above and leaf.share_type == leaf.type and leaf.type:
                created += leaf.share - 1
                _grow_balanced(leaf, leaf.type, leaf.share)
                grown.append(leaf)
    if grown:
        dom.link(root)
        geometry.clear_cache()
        for sub in grown:
            _size_subtree_equal(sub)
        geometry.clear_cache()
    return created


def _ext_exposure(leaf: dom.Node) -> int:
    """Number of the leaf's four edges that lie on the external plot perimeter
    ('a'/'b'/'c'/'d'); 0 means a fully landlocked (interior) leaf. Used by the
    interior-``O`` light-well placement (ld2, §13.6) to find the most landlocked
    leaves — those whose room neighbours have no facade and so would otherwise
    fail crinkliness (``area_outside`` ~ 0)."""
    from . import geometry
    return sum(1 for e in range(4)
               if geometry.boundary_id(leaf, e) in geometry._EXTERNAL)


def _assign_adjacency_aware(lvl: dom.Node, room_codes: list[str], reqs,
                            rng: np.random.Generator, door_width: float = 1.2,
                            fixed_circ: "list[dom.Node] | None" = None,
                            interior_outside: bool = False,
                            n_outside: int = 1,
                            scope: "set[dom.Node] | None" = None,
                            beam_width: int = 1,
                            assign_solver: str = "greedy") -> None:
    """Assign leaf types so rooms cluster around a connected circulation spine.

    s44 (DESIGN.md §11.2 follow-up): random type assignment leaves rooms stranded
    from circulation, so adjacency-to-``c`` and access ("inaccessible usable
    space") fails dominate the seeded design. Here the leftover (non-room,
    non-outside) leaf budget is spent on a **connected dominating set** of the
    geometric leaf-adjacency graph: every room leaf ends up adjacent to a
    circulation leaf, and the circulation set is connected, so access is
    satisfied by construction at the seed geometry. Rooms are placed on dominated
    leaves; one peripheral leaf becomes the outside ``O``.

    ``fixed_circ`` (ld5, §11.7): leaves that must stay circulation and seed the
    dominating set — the inherited vertical core when lifting upper storeys, so
    the spine grows *off the core* rather than from scratch. Rooms with a
    secondary adjacency requirement (beyond ``c``, e.g. ``k1↔da1``, ``da1↔o``)
    are then placed next to an already-typed neighbour of the required code.

    ``lvl`` already has the right number of leaves grown; their types are
    (re)written in place. Stochastic where it is free (room order, tie-breaks) so
    a bootstrap batch stays diverse.

    ``scope`` (homemaker-py-f1d): restrict retyping to this subset of ``lvl``'s
    leaves — used by the ruin-and-recreate LNS move to rebuild one wing of an
    already-typed storey in place. ``fixed_circ`` may then name leaves OUTSIDE
    ``scope`` (the surviving circulation bordering the wing) purely as
    dominating-set seeds; they anchor the spine but are never retyped, and the
    dominating-set growth and room/outside placement only ever touch ``scope``.
    ``None`` (default) reproduces the unrestricted whole-``lvl`` behaviour
    exactly — every existing caller is unaffected.

    ``beam_width`` (homemaker-py-c94, EXPERIMENTAL, default 1): the circulation
    spine and outside leaves are always placed by the single greedy pass above
    (unchanged, no beam). ``beam_width=1`` also keeps the *room* placement pass
    below exactly the prior one-shot greedy walk (byte-identical output for
    every existing caller). ``beam_width>1`` instead explores the same
    room-to-slot decisions with :func:`_beam_place_rooms`: several partial
    placements are kept alive and ranked by a cheap proxy (running total
    secondary-adjacency satisfaction — no extra geometry or fitness calls,
    since circulation/outside are already fixed and shared across every beam
    branch), so a room whose best slot is later needed by a harder-to-place
    room is no longer locked in by one irrevocable greedy step.

    ``assign_solver`` (homemaker-py-2g7.5, EXPERIMENTAL, default "greedy"):
    "cpsat" replaces the room-placement pass above (both the plain-greedy
    and beam variants) with an exact solve of the same decision via
    :func:`cpsat.solve_room_labels` — see DESIGN.md §37.7. Circulation and
    outside placement (the connected-dominating-set step above) is
    unaffected either way. Falls through to the greedy/beam path on any
    solver failure (OR-Tools unavailable, infeasible, or timeout), so
    behaviour is always defined.
    """
    from . import geometry

    reqs = reqs or {}
    leaves = lvl.leaves()
    idx = {leaf: i for i, leaf in enumerate(leaves)}
    assignable = scope if scope is not None else set(leaves)
    n = len(assignable)
    R = len(room_codes)
    n_circ = max(1, n - (R + max(1, n_outside)))  # leftover after rooms + outside
    seeds = [c for c in (fixed_circ or []) if c in idx]
    n_circ = max(n_circ, len(seeds))  # never fewer circ leaves than the fixed core

    # Geometry is type-independent (coords derive from divisions/rotations/plot);
    # clear the id-keyed cache so freshly grown leaves never hit stale entries.
    geometry.clear_cache()
    G = geometry.leaf_graph(lvl, door_width)
    deg = dict(G.degree())

    def _nbrs(leaf):
        return set(G.neighbors(leaf)) if G.has_node(leaf) else set()

    # Greedy connected dominating set of size n_circ: seed from the fixed core (or
    # the most central leaf), then repeatedly add the frontier leaf that newly
    # dominates the most leaves (keeping the set connected). Growth is confined to
    # ``assignable`` so a scoped call never annexes a leaf outside the wing.
    circ = (set(seeds) if seeds
            else {max(assignable, key=lambda L: (deg.get(L, 0), -idx[L]))})
    dominated = set().union(*( _nbrs(s) | {s} for s in circ))
    while len(circ) < n_circ:
        frontier = ((set().union(*(_nbrs(s) for s in circ)) - circ) & assignable
                    if circ else set())
        if frontier:
            pick = max(frontier, key=lambda L: (len(_nbrs(L) - dominated),
                                                deg.get(L, 0), -idx[L]))
        else:  # disconnected remainder — seed a new component by degree
            rest = [L for L in assignable if L not in circ]
            if not rest:
                break
            pick = max(rest, key=lambda L: (deg.get(L, 0), -idx[L]))
        circ.add(pick)
        dominated |= _nbrs(pick) | {pick}

    for s in circ:
        if s in assignable:  # never retype a fixed_circ seed outside scope
            s.type = "C"

    # homemaker-py-fdp: iterate `leaves` (tree order) and use `assignable` only
    # for MEMBERSHIP. `assignable` is a set of dom.Node, which hashes by id() --
    # a memory address -- so iterating it directly ordered `noncirc`, and hence
    # `room_slots`, by where the objects happened to land in memory. That varies
    # between runs in one process, so `assign_solver="cpsat"` returned a
    # different (equally optimal) labelling every time.
    #
    # The greedy path never noticed: it re-sorts every slot list with `-idx[L]`
    # as a unique tiebreak, which is immune to the incoming order. cpsat consumes
    # `room_slots` order as the model's variable order, so it exposed it.
    noncirc = [L for L in leaves if L in assignable and L not in circ]
    if interior_outside:
        # ld2 (§13.6): seed ``O`` as INTERIOR light wells instead of one
        # peripheral leaf. A landlocked room (no plot facade, no uncovered-O
        # neighbour) has area_outside ~ 0 → crinkliness ~ 0 → fail (the erc
        # crinkliness residual). Placing the outside leaves on the most
        # landlocked slots (fewest external edges, then highest degree = most
        # room neighbours to illuminate) gives those rooms a daylight source by
        # construction. Wells are spread greedily so each covers a fresh set of
        # rooms rather than clustering on one over-lit pocket.
        o_leaves: list[dom.Node] = []
        covered: set = set()
        cands = list(noncirc)
        for _ in range(max(1, n_outside)):
            if not cands:
                break
            pick = max(cands, key=lambda L: (-_ext_exposure(L),
                                             len(_nbrs(L) - covered),
                                             deg.get(L, 0), -idx[L]))
            o_leaves.append(pick)
            cands.remove(pick)
            covered |= _nbrs(pick) | {pick}
        for L in o_leaves:
            L.type = "O"
    else:
        # Outside on the most peripheral non-circulation leaf (fewest circulation
        # neighbours, then lowest degree) so it does not steal a circulation-
        # adjacent slot a room needs.
        o_leaf = min(noncirc, key=lambda L: (sum(1 for nb in _nbrs(L) if nb in circ),
                                             deg.get(L, 0), idx[L]))
        o_leaf.type = "O"
        o_leaves = [o_leaf]

    # Rooms onto the remaining leaves, dominated (circulation-adjacent) slots
    # first so adjacency-to-c holds. Codes are placed hardest-constrained first
    # (most adjacency requirements), each onto the open slot that satisfies the
    # most of its requirements against already-typed neighbours (circulation and
    # rooms placed so far) — clustering k1↔da1, da1↔o, etc. Ties broken randomly.
    o_set = set(o_leaves)
    room_slots = [L for L in noncirc if L not in o_set]
    codes = [room_codes[i] for i in rng.permutation(len(room_codes))]

    def _n_secondary(code: str) -> int:
        r = reqs.get(code)
        return len([a for a in (r.adjacency if r else []) if a and a[0].lower() != "c"])

    codes.sort(key=_n_secondary, reverse=True)

    placed = None
    if assign_solver == "cpsat":
        # homemaker-py-2g7.5 (DESIGN.md §37.7): exact assignment via
        # OR-Tools CP-SAT, in place of this block's greedy/beam heuristics
        # below. Falls through to them on any solver failure (unavailable/
        # infeasible/timeout) — always a defined outcome.
        from . import cpsat
        room_set = set(room_slots)
        neighbors = {L: {nb for nb in _nbrs(L) if nb in room_set} for L in room_slots}
        context_types = {L: {nb.type for nb in _nbrs(L) if nb.type and nb not in room_set}
                         for L in room_slots}
        placed = cpsat.solve_room_labels(room_slots, codes, reqs, neighbors, context_types)

    if placed is not None:
        for leaf, code in placed.items():
            leaf.type = code
        leftover = [L for L in room_slots if L not in placed]
    elif beam_width <= 1:
        open_slots = sorted(room_slots,
                            key=lambda L: (L in dominated, deg.get(L, 0), -idx[L]),
                            reverse=True)
        for code in codes:
            if not open_slots:
                break
            req_adj = [a[0].lower() for a in (reqs.get(code).adjacency if reqs.get(code) else [])]
            secondary = [a for a in req_adj if a != "c"]

            def _sat(slot, secondary=secondary) -> int:
                nb_types = {(nb.type or "")[:1].lower() for nb in _nbrs(slot) if nb.type}
                return sum(1 for a in secondary if a in nb_types)

            best = max(open_slots, key=lambda L: (_sat(L), L in dominated,
                                                  deg.get(L, 0), -idx[L]))
            best.type = code
            open_slots.remove(best)
        leftover = open_slots
    else:
        placed = _beam_place_rooms(codes, room_slots, dominated, deg, idx, _nbrs,
                                   reqs, beam_width)
        for leaf, code in placed.items():
            leaf.type = code
        leftover = [L for L in room_slots if L not in placed]
    for leaf in leftover:  # any leftover slot (count mismatch) → outside
        leaf.type = "O"


def _beam_place_rooms(codes: list[str], slots: list, dominated: set,
                      deg: dict, idx: dict, _nbrs, reqs,
                      beam_width: int) -> dict:
    """Beam/best-first search over room-to-slot placement (homemaker-py-c94).

    Same decision ``_assign_adjacency_aware`` makes greedily (which open slot a
    room lands on, hardest-constrained code first) but keeps up to
    ``beam_width`` partial placements alive per step instead of committing to
    one. Each step branches every surviving state into its top ``beam_width``
    candidate slots for the current code (by the same ``_sat``/dominated/
    degree ranking the greedy pass uses), scores each branch by the running
    total of secondary-adjacency matches satisfied so far — cheap: no
    geometry or fitness calls, since circulation/outside are already fixed and
    the leaf graph is shared read-only across every branch — then prunes back
    to the ``beam_width`` best-scoring states before the next code. Returns
    the highest-scoring complete placement as ``{leaf: code}``.
    """
    def secondary_of(code: str) -> list[str]:
        r = reqs.get(code)
        return [a[0].lower() for a in (r.adjacency if r else []) if a and a[0].lower() != "c"]

    def sat(slot, assign: dict, secondary: list[str]) -> int:
        nb_types = set()
        for nb in _nbrs(slot):
            t = assign.get(nb, nb.type)
            if t:
                nb_types.add(t[:1].lower())
        return sum(1 for a in secondary if a in nb_types)

    beam: list[tuple[int, dict]] = [(0, {})]
    for code in codes:
        secondary = secondary_of(code)
        candidates = []
        for score, assign in beam:
            open_slots = [L for L in slots if L not in assign]
            if not open_slots:
                candidates.append((score, assign))
                continue
            ranked = sorted(
                open_slots,
                key=lambda L: (sat(L, assign, secondary), L in dominated,
                               deg.get(L, 0), -idx[L]),
                reverse=True)
            for slot in ranked[:beam_width]:
                new_assign = dict(assign)
                new_assign[slot] = code
                candidates.append((score + sat(slot, assign, secondary), new_assign))
        candidates.sort(key=lambda c: c[0], reverse=True)
        beam = candidates[:beam_width]
    return max(beam, key=lambda c: c[0])[1] if beam else {}


def _cpsat_relabel_settled(lvl: dom.Node, reqs) -> None:
    """Re-solve room-code labelling against the storey's SETTLED geometry
    (homemaker-py-2g7.5, DESIGN.md §37.7's "alternating minimization"
    follow-up, §11.2's lesson applied at seed time).

    ``assign_solver="cpsat"``'s exact solve is measured (A/B, harbor-house)
    to be MORE fragile than the greedy/beam heuristic to the proportion-
    aware target-size resizing that runs right after assignment
    (``_size_divisions_from_targets``): resizing can shrink a shared-wall
    segment below the door-width adjacency threshold, silently invalidating
    an edge the exact solve specifically relied on (it packs adjacency
    satisfaction tightly against the pre-resize graph, leaving less slack
    than the greedy path's more conservative, degree-biased placement).
    Re-running the exact solve once more against the now-settled geometry
    recovers this — cheap (same small model) and never worse (it can only
    IMPROVE satisfied-adjacency count from wherever resizing left it).
    """
    from . import cpsat, geometry

    geometry.clear_cache()
    G = geometry.leaf_graph(lvl)
    room_slots = [lf for lf in lvl.leaves() if lf.type in reqs]
    if not room_slots:
        return
    codes = [lf.type for lf in room_slots]
    room_set = set(room_slots)
    neighbors = {L: {nb for nb in G.neighbors(L) if nb in room_set}
                for L in room_slots if G.has_node(L)}
    context_types = {L: {nb.type for nb in G.neighbors(L)
                         if nb.type and nb not in room_set}
                     for L in room_slots if G.has_node(L)}
    result = cpsat.solve_room_labels(room_slots, codes, reqs, neighbors, context_types)
    if result:
        for leaf, code in result.items():
            leaf.type = code


def constructive_topology(seed_root: dom.Node, reqs, rng: np.random.Generator,
                          types: list[str], min_storeys: int = 1,
                          adjacency_aware: bool = True,
                          proportion_aware: bool = True,
                          circ_divisor: int = 3,
                          leaf_sharing: bool = False,
                          leaf_share_factor: int = 2,
                          depth_balanced: bool = False,
                          interior_outside: bool = True,
                          outside_divisor: int = 3,
                          construction_beam_width: int = 1,
                          multi_use: bool = False,
                          assign_solver: str = "greedy",
                          repair_circulation: bool = False,
                          preserve_circulation: bool = False) -> dom.Node:
    """Build a seed that instantiates every required space by construction.

    The §11.0 diagnosis: random divide+retype chains leave required programme
    rooms missing on large programmes, so ``missing`` stacking dominates fitness.
    This seeder makes the required room set a *constructive invariant*: it sizes
    each storey to its required rooms (partitioning by ``level``; level-free
    rooms distributed across storeys), plus one circulation ``C`` and one
    outside ``O`` per storey, then assigns the types.  Stochastic (random split
    ratios/rotations and a shuffled type assignment) so a bootstrap batch is
    still a diverse population.

    ``construction_beam_width`` (homemaker-py-c94, EXPERIMENTAL, default 1):
    forwarded to ``_assign_adjacency_aware``'s ``beam_width`` — see there.
    ``1`` reproduces the prior greedy room placement exactly.

    ``assign_solver`` (homemaker-py-2g7.5, EXPERIMENTAL, default "greedy"):
    forwarded to ``_assign_adjacency_aware``'s same-named parameter — see
    there. ``"greedy"`` reproduces the prior placement exactly regardless
    of ``construction_beam_width``.

    Returns a finalised deep copy; ``seed_root`` is unchanged.
    """
    from . import genome as _g
    from . import programme as _prog

    child = copy.deepcopy(seed_root)
    prog = _programme_codes(reqs)
    levels_needed = [r.level for r in prog.values() if r.level is not None]
    n_storeys = max((max(levels_needed) + 1) if levels_needed else 1, min_storeys)
    colocate_pairs = _prog.derive_colocate_pairs(reqs) if multi_use else []

    # grow storeys from the bare base by duplicating the top storey (cf.
    # mutate_level_add / genome._copy_storey), inheriting floor height.
    while len(dom.levels(child)) < n_storeys:
        top = dom.levels(child)[-1]
        dup = _g._copy_storey(top)
        dup.height = top.height
        top.above = dup
    lvls = dom.levels(child)

    # Partition required instances across storeys: level-constrained rooms to
    # their storey, level-free rooms round-robin over a shuffled order.
    buckets: list[list[str]] = [[] for _ in range(n_storeys)]
    free: list[str] = []
    for code, req in prog.items():
        for _ in range(req.count):
            if req.level is not None and req.level < n_storeys:
                buckets[req.level].append(code)
            else:
                free.append(code)
    free = [free[i] for i in rng.permutation(len(free))]
    for i, code in enumerate(free):
        buckets[i % n_storeys].append(code)

    for li, lvl in enumerate(lvls):
        rooms = list(buckets[li])
        # erc.3 leaf-sharing (§13.3): collapse same-code rooms into fewer, larger
        # shared leaves BEFORE growing the tree, so the storey carries fewer total
        # leaves (each paying the ~1.8 shape-fail tax once, §13.1). The fitness
        # recovers each leaf's multiplicity from area; here we only reduce the
        # code list and remember the plan to size shared leaves to k×target.
        # 1s3 §26 path b: fuse different-but-compatible codes onto one leaf
        # BEFORE leaf-sharing, so leaf-sharing still groups whichever code
        # was kept as primary with its remaining same-code siblings.
        colocate_plan: dict[str, list[str]] = {}
        if multi_use:
            rooms, colocate_plan = _colocate_rooms(rooms, colocate_pairs, rng)
        share_plan: dict[str, list[int]] = {}
        if leaf_sharing:
            rooms, share_plan = _share_rooms(rooms, reqs, leaf_share_factor)
        if adjacency_aware:
            # Spend extra leaves on a circulation spine (~one circ per 3 rooms),
            # then assign so every room is adjacent to it (s44). Geometry must be
            # available to read the leaf-adjacency graph; _grow_leaves leaves the
            # tree finalisable and geometry.leaf_graph derives coords on demand.
            # c3g granularity knob: ~one circ per `circ_divisor` rooms (default 3).
            n_circ = max(1, -(-len(rooms) // circ_divisor))
            # ld2 (§13.6): scale the outside-leaf count with the room count when
            # seeding interior light wells (default 1 peripheral O otherwise).
            n_o = max(1, round(len(rooms) / outside_divisor)) if interior_outside else 1
            _grow_leaves(lvl, len(rooms) + n_o + n_circ, rng, balance=depth_balanced)
            dom.link(child)
            _assign_adjacency_aware(lvl, rooms, reqs, rng,
                                    interior_outside=interior_outside, n_outside=n_o,
                                    beam_width=construction_beam_width,
                                    assign_solver=assign_solver)
        else:
            assign = rooms + ["C", "O"]  # +core circulation, +outside
            _grow_leaves(lvl, len(assign), rng, balance=depth_balanced)
            leaves = lvl.leaves()
            order = rng.permutation(len(leaves))
            for slot, leaf_idx in enumerate(order):
                leaves[int(leaf_idx)].type = assign[slot] if slot < len(assign) else "O"

        if proportion_aware:
            # leu.2: now that leaves are typed, replace the uniform 0.5 cuts with
            # target-proportional ratios so the raw seed sits near feasible size/
            # width/proportion. Topology and type assignment are unchanged. Link
            # first so upper-storey roots resolve geometry (the else branch above
            # does not link, unlike the adjacency-aware branch).
            dom.link(child)
            leaf_co = _leaf_colocate_from_plan(lvl, colocate_plan, reqs) if multi_use else {}
            leaf_extra = {lf: reqs[co].size for lf, co in leaf_co.items()
                          if co in reqs and reqs[co].size > 0}
            _resize = (_size_divisions_preserving_circulation if preserve_circulation
                       else _size_divisions_from_targets)
            _resize(lvl, reqs, leaf_mult=_leaf_mult_from_plan(lvl, share_plan),
                    leaf_extra=leaf_extra)
            if adjacency_aware and assign_solver == "cpsat":
                _cpsat_relabel_settled(lvl, reqs)
            if repair_circulation:
                repair_circulation_settled(lvl, reqs)

    return _finalise(child)


def lift_base_to_storeys(base_root: dom.Node, upper_buckets: list[dict[str, int]],
                         rng: np.random.Generator, types: list[str],
                         reqs=None, adjacency_aware: bool = True,
                         proportion_aware: bool = True,
                         circ_divisor: int = 3,
                         leaf_sharing: bool = False,
                         leaf_share_factor: int = 2,
                         depth_balanced: bool = False,
                         interior_outside: bool = True,
                         outside_divisor: int = 3,
                         construction_beam_width: int = 1,
                         multi_use: bool = False,
                         assign_solver: str = "greedy") -> dom.Node:
    """Stack upper storeys onto an evolved single-storey base (DESIGN.md §11.3).

    Stage 2 seeder: the Stage-1 base is the credible ground floor and is left
    **untouched**; each upper storey is constructed as a delta that (a) inherits
    and preserves the base's largest circulation ``C`` leaf as a vertically-aligned
    core (so Stage 2 does not carve a core from scratch — the anti-bungalow
    invariant) and (b) instantiates its required room multiset (``upper_buckets``,
    one dict per storey >= 1) by construction, plus one outside ``O``. Stochastic
    splits/assignment keep a bootstrap batch diverse; ``mutate_place_missing``
    repairs any residual gaps during the loop.

    ``assign_solver`` (homemaker-py-2g7.5, EXPERIMENTAL, default "greedy"):
    forwarded to ``_assign_adjacency_aware``'s same-named parameter — see
    there.

    Returns a finalised deep copy; ``base_root`` is unchanged.
    """
    from . import genome as _g, geometry as _geo
    from . import programme as _prog

    child = copy.deepcopy(base_root)
    base = dom.levels(child)[0]
    base.above = None  # start from the single-storey base only

    base_cs = [lf for lf in base.leaves()
               if lf.type == "C"]
    core_path = max(base_cs, key=_geo.area).id if base_cs else None
    colocate_pairs = _prog.derive_colocate_pairs(reqs) if multi_use and reqs else []

    prev = base
    for bucket in upper_buckets:
        dup = _g._copy_storey(prev)
        dup.height = prev.height
        core_node = dup.by_id(core_path) if core_path is not None else None

        rooms = [code for code, cnt in bucket.items() for _ in range(cnt)]
        # 1s3: fuse different-but-compatible codes onto one leaf on this storey
        # too, before leaf-sharing (same ordering as constructive_topology).
        colocate_plan: dict[str, list[str]] = {}
        if multi_use:
            rooms, colocate_plan = _colocate_rooms(rooms, colocate_pairs, rng)
        # erc.3: collapse same-code rooms into fewer shared leaves on this storey
        # too (§13.3), so upper floors get the same per-leaf-tax saving.
        share_plan: dict[str, list[int]] = {}
        if leaf_sharing:
            rooms, share_plan = _share_rooms(rooms, reqs, leaf_share_factor)

        def _free() -> list[dom.Node]:
            return [lf for lf in dup.leaves() if lf is not core_node]

        if adjacency_aware:
            # ld5 (§11.7): grow the upper floor a circulation spine (~one circ per
            # 3 rooms, the inherited core counted) and assign rooms around it via
            # the geometric leaf graph, seeding the dominating set from the
            # inherited vertical core so the spine grows off the core, not anew.
            n_circ = max(1, -(-len(rooms) // circ_divisor))  # c3g granularity knob
            # ld2 (§13.6): scale interior light-well count with room count.
            n_o = max(1, round(len(rooms) / outside_divisor)) if interior_outside else 1
            target_total = len(rooms) + n_o + n_circ
            n_free_target = target_total - (1 if core_node is not None else 0)
            while len(_free()) < n_free_target:
                frees = _free()
                if depth_balanced:
                    fd = [(l, d) for l, d in _leaves_with_depth(dup) if l in frees]
                    dmin = min(d for _l, d in fd)
                    leaf = _pick(rng, [l for l, d in fd if d == dmin])
                else:
                    leaf = _pick(rng, frees)
                leaf.division = [0.5, 0.5]
                leaf.rotation = int(rng.integers(4))
                leaf.left = dom.Node(type=leaf.type)
                leaf.right = dom.Node(type=leaf.type)
                leaf.type = None
            prev.above = dup
            dom.link(child)  # link so the upper storey's geometry is computable
            _assign_adjacency_aware(
                dup, rooms, reqs, rng,
                fixed_circ=[core_node] if core_node is not None else None,
                interior_outside=interior_outside, n_outside=n_o,
                beam_width=construction_beam_width,
                assign_solver=assign_solver)
        else:
            assign = rooms + ["O"]  # courtyard / outside on the upper floor
            if core_node is None:
                assign.append("C")  # no inherited core to reuse — make one
            while len(_free()) < len(assign):
                frees = _free()
                if depth_balanced:
                    fd = [(l, d) for l, d in _leaves_with_depth(dup) if l in frees]
                    dmin = min(d for _l, d in fd)
                    leaf = _pick(rng, [l for l, d in fd if d == dmin])
                else:
                    leaf = _pick(rng, frees)
                leaf.division = [0.5, 0.5]
                leaf.rotation = int(rng.integers(4))
                leaf.left = dom.Node(type=leaf.type)
                leaf.right = dom.Node(type=leaf.type)
                leaf.type = None
            frees = _free()
            order = rng.permutation(len(frees))
            for slot, leaf_idx in enumerate(order):
                frees[int(leaf_idx)].type = assign[slot] if slot < len(assign) else "O"
            if core_node is not None:
                core_node.type = "C"  # keep the inherited core as circulation
            prev.above = dup

        if proportion_aware:
            # leu.2: size the upper-floor cuts from target areas too. The base is
            # the evolved Stage-1 ground floor and is left untouched; only the
            # constructed upper storey's ratios are rewritten. (Cuts inherited from
            # the base via below-links are no-ops here — their geometry is fixed
            # below — so this best-effort sizes the floor's own new divisions.)
            dom.link(child)
            leaf_co = _leaf_colocate_from_plan(dup, colocate_plan, reqs) if multi_use else {}
            leaf_extra = {lf: reqs[co].size for lf, co in leaf_co.items()
                          if co in reqs and reqs[co].size > 0}
            _size_divisions_from_targets(
                dup, reqs, leaf_mult=_leaf_mult_from_plan(dup, share_plan),
                leaf_extra=leaf_extra)
            if adjacency_aware and assign_solver == "cpsat":
                _cpsat_relabel_settled(dup, reqs)

        prev = dup

    return _finalise(child)


def mutate_ruin_recreate(root: dom.Node, rng: np.random.Generator,
                         types: list[str], reqs=None) -> tuple[dom.Node, str]:
    """LNS ruin-and-recreate: rebuild one wing of a storey with the constructor.

    homemaker-py-f1d (DESIGN.md's experiment log): every "search machinery"
    change tried so far (niching+restarts, graded objective, Wong-Liu
    reassociation, granularity, island model, grain annealing, circulation-
    repair ops) has come back null-to-negative, while construction/seeding
    quality (adjacency-aware seeding, proportion-aware seeding) is the only
    lever that has ever moved the fail count. ``_assign_adjacency_aware``
    currently only runs once, at seeding. This move reuses it repeatedly
    during search: pick a divided, live-cut subtree ("wing") of one storey
    holding a genuine partial neighbourhood of that storey's leaves (at least
    2, at most half), un-divide it back to a single leaf, then regrow and
    retype it with the same adjacency-aware constructor the seeders use —
    seeded (``fixed_circ``) from whichever already-typed circulation leaves
    border the wing, exactly the mechanism ``lift_base_to_storeys`` uses to
    grow an upper storey off an inherited core (ld5, §11.7), so the rebuilt
    interior spine reconnects to the surviving one instead of growing a
    disconnected island.

    The wing's programme room-code budget (the multiset of required-space
    types already inside it) is preserved exactly; only its internal
    circulation/outside counts and split are rebuilt, at the same
    circ_divisor=3/outside_divisor=3 ratio the constructive seeders default
    to (not threaded from the run config — an experimental repair op, like
    ``bridge_circulation``, kept parameter-light).
    """
    if not reqs:
        return _finalise(copy.deepcopy(root)), "ruin_recreate noop"
    from . import geometry

    child = copy.deepcopy(root)
    _finalise(child)
    lvls = dom.levels(child)
    totals = {li: len(lvl.leaves()) for li, lvl in enumerate(lvls)}
    cands = [(li, n) for li, n in _owned_branches(child)
             if totals[li] >= 4 and 2 <= len(n.leaves()) <= max(2, totals[li] // 2)]
    if not cands:
        return _finalise(child), "ruin_recreate noop"
    li, wing = _pick(rng, cands)
    lvl = lvls[li]

    G = geometry.leaf_graph(lvl)
    wing_leaves = set(wing.leaves())
    border_circ = sorted(
        {nb for lf in wing_leaves for nb in G.neighbors(lf)
         if nb not in wing_leaves and nb.type == "C"},
        key=lambda n: n.id or "")

    rooms = [lf.type for lf in wing.leaves() if lf.type in reqs]
    n_circ_total = max(1, -(-len(rooms) // 3))  # circ_divisor=3
    n_o = max(1, round(len(rooms) / 3))  # outside_divisor=3
    n_new = len(rooms) + n_o + max(0, n_circ_total - len(border_circ))

    wing.left = wing.right = None
    wing.division = None
    wing.type = None
    _grow_leaves(wing, max(1, n_new), rng, balance=True)
    dom.link(child)

    _assign_adjacency_aware(
        lvl, rooms, reqs, rng, fixed_circ=border_circ or None,
        interior_outside=True, n_outside=n_o, scope=set(wing.leaves()))
    dom.link(child)
    _size_divisions_from_targets(wing, reqs)

    return _finalise(child), (
        f"ruin_recreate {li}/{wing.id or 'root'} "
        f"({len(rooms)} rooms, {len(border_circ)} anchors)")


def mutate_reassign(root: dom.Node, rng: np.random.Generator,
                    types: list[str], reqs=None) -> tuple[dom.Node, str]:
    """CP-SAT re-labelling of one wing's room codes (homemaker-py-2g7.5).

    The "assignment analogue of ruin_recreate" (§23/DESIGN.md §37.7): picks
    the same kind of wing ``mutate_ruin_recreate`` does (a divided,
    live-cut subtree of one storey holding a genuine partial neighbourhood,
    at least 2 leaves, at most half the storey), but does NOT un-divide or
    regrow it — the topology and the wing's room-code multiset are both
    preserved exactly. Only which leaf gets which code is re-decided, via
    an exact :func:`cpsat.solve_room_labels` solve over the wing's room
    leaves (circulation/outside leaves inside or bordering the wing stay
    fixed, contributing as context for adjacency-to-``c`` credit). Where
    ``mutate_ruin_recreate`` repairs a badly-grown wing structurally, this
    move repairs a badly-LABELLED wing whose leaf structure is already
    fine — the seeder's own one-shot greedy assignment can be beaten by
    revisiting it once the wing's geometry (and therefore its adjacency
    graph) has settled during search, not just once at construction time.

    No ``reqs``, no eligible wing, no room leaves in the chosen wing, or
    solver failure (unavailable/infeasible/no improvement) all no-op.
    """
    if not reqs:
        return _finalise(copy.deepcopy(root)), "reassign noop"
    from . import cpsat, geometry

    child = copy.deepcopy(root)
    _finalise(child)
    lvls = dom.levels(child)
    totals = {li: len(lvl.leaves()) for li, lvl in enumerate(lvls)}
    cands = [(li, n) for li, n in _owned_branches(child)
             if totals[li] >= 4 and 2 <= len(n.leaves()) <= max(2, totals[li] // 2)]
    if not cands:
        return _finalise(child), "reassign noop"
    li, wing = _pick(rng, cands)
    lvl = lvls[li]

    room_slots = [lf for lf in wing.leaves() if lf.type in reqs]
    if not room_slots:
        return _finalise(child), "reassign noop"
    codes = [lf.type for lf in room_slots]

    G = geometry.leaf_graph(lvl)
    room_set = set(room_slots)
    neighbors = {L: {nb for nb in G.neighbors(L) if nb in room_set}
                for L in room_slots if G.has_node(L)}
    context_types = {L: {nb.type for nb in G.neighbors(L)
                         if nb.type and nb not in room_set}
                     for L in room_slots if G.has_node(L)}
    result = cpsat.solve_room_labels(room_slots, codes, reqs, neighbors, context_types)
    if not result or all(leaf.type == code for leaf, code in result.items()):
        return _finalise(child), "reassign noop"

    for leaf, code in result.items():
        leaf.type = code

    return _finalise(child), f"reassign {li}/{wing.id or 'root'} ({len(room_slots)} rooms)"


def mutate_reassociate(root: dom.Node, rng: np.random.Generator,
                       types: list[str]) -> tuple[dom.Node, str]:
    """Wong-Liu M3 associativity move: ``(a|b)|c <-> a|(b|c)`` on parallel cuts.

    A pure-topology reachability move (homemaker-py-9gp.2, DESIGN.md §12.3). M1
    (operand swap) is ``mutate_swap`` and M2 (single-cut orientation complement)
    is ``mutate_rotate``; the missing canonical-slicing move is *associativity* —
    regrouping three regions split by two **same-orientation** cuts into the
    mirror tree shape. It preserves the leaf set and types but reaches tree
    structures the divide/undivide/swap/rotate set cannot, attacking the
    reachability bottleneck §11.4/§11.5 both fingered.

    Only **live** cuts are restructured (``below is None``, as ``mutate_rotate``),
    so dead inherited fields are never touched and ``encode`` re-anchors any
    upper-storey deltas (operators edit the phenotype; the genome re-derives).
    The two restructured cuts default to ``[0.5, 0.5]`` and the inner loop
    recovers their ratios (cold, cf. ``mutate_divide``'s new cut).
    """
    child = copy.deepcopy(root)
    # Candidate parents P with a same-orientation, live, divided child on a side.
    cands: list[tuple[int, dom.Node, str]] = []
    for li, P in _owned_branches(child):
        if P.below is not None:
            continue
        for side in ("l", "r"):
            kid = P.left if side == "l" else P.right
            if (kid.divided and kid.below is None
                    and (kid.rotation % 2) == (P.rotation % 2)):
                cands.append((li, P, side))
    if not cands:
        return _finalise(child), "reassociate noop"

    li, P, side = _pick(rng, cands)
    rot = P.rotation
    if side == "l":  # (a|b)|c -> a|(b|c)
        a, b, c = P.left.left, P.left.right, P.right
        inner = dom.Node(rotation=rot)
        inner.division = [0.5, 0.5]
        inner.left, inner.right = b, c
        P.left, P.right = a, inner
    else:            # a|(b|c) -> (a|b)|c
        a, b, c = P.left, P.right.left, P.right.right
        inner = dom.Node(rotation=rot)
        inner.division = [0.5, 0.5]
        inner.left, inner.right = a, b
        P.left, P.right = inner, c
    P.division = [0.5, 0.5]
    return _finalise(child), f"reassociate {li}/{P.id or 'root'}"


def predicted_shape_fails(root: dom.Node, reqs, fit) -> int:
    """Predicted per-leaf shape fails at the proportion-aware target geometry.

    Shape-feasibility proxy (homemaker-py-9gp.1, DESIGN.md §12.3). Lays the
    topology out with :func:`_size_divisions_from_targets` — the squarest
    target-proportional geometry the inner loop warm-starts from, i.e. the best
    shape this topology can plausibly reach — then counts the
    size/width/proportion/crinkliness fails the native ``fit`` reports. Used to
    prune clearly-infeasible topologies *before* the inner loop, so budget flows
    to feasible ones. A heuristic lower-bound proxy, not a true bound; the caller
    guards against pruning anything that could still beat the incumbent.

    ``root`` is left untouched (a deep copy is laid out and scored).
    """
    child = copy.deepcopy(root)
    dom.link(child)
    for lvl in dom.levels(child):
        _size_divisions_from_targets(lvl, reqs)
    _, fails = fit.score_with_fails(child)
    return sum(1 for f in fails if f.endswith(_SHAPE_FAIL_SUFFIXES))


_SHAPE_FAIL_SUFFIXES = (" size", " width", " proportion", " crinkliness")


def mutate_core_divide(root: dom.Node, rng: np.random.Generator,
                       types: list[str]) -> tuple[dom.Node, str]:
    """Divide a circulation leaf at the same path across ALL storeys at once.

    Staircase cores (C leaves at the same path on 2+ consecutive floors) are
    disrupted if a single-storey divide changes the C path on only one floor.
    This operator applies the same rotation and division to every floor that
    has a C leaf at the chosen path, maintaining staircase consistency as an
    atomic invariant rather than a multi-step recovery task.
    """
    child = copy.deepcopy(root)
    lvls = dom.levels(child)

    # Collect paths that are C leaves on 2+ floors
    c_paths: dict[str, list[int]] = {}
    for li, lvl in enumerate(lvls):
        for lf in lvl.leaves():
            if lf.type and lf.type.upper() == "C":
                c_paths.setdefault(lf.id, []).append(li)
    core_paths = [(path, lis) for path, lis in c_paths.items() if len(lis) >= 2]
    if not core_paths:
        return _finalise(child), "core_divide noop"

    path, level_indices = _pick(rng, core_paths)
    rotation = int(rng.integers(4))
    division = [0.5, 0.5]

    for li in level_indices:
        node = lvls[li].by_id(path)
        if node is None or node.divided:
            continue
        node.division = list(division)
        node.rotation = rotation
        node.left = dom.Node(type="C")
        node.right = dom.Node(type=str(_pick(rng, types)))
        node.type = None

    return _finalise(child), f"core_divide {path} ({len(level_indices)} floors)"


def mutate_core_undivide(root: dom.Node, rng: np.random.Generator,
                         types: list[str]) -> tuple[dom.Node, str]:
    """Reverse of core_divide: merge a C sub-core back into a single C leaf on all floors.

    Picks a C leaf (e.g. 'rll') whose parent is also a C leaf on 2+ floors,
    then undivides the parent on every floor simultaneously, restoring the
    larger staircase footprint without a temporary path-mismatch fail.
    """
    child = copy.deepcopy(root)
    lvls = dom.levels(child)

    # Find divided nodes whose left child is C (candidate for core_undivide):
    # the parent path must have C.left on 2+ floors.
    parent_paths: dict[str, list[int]] = {}
    for li, lvl in enumerate(lvls):
        for n in [n for li2, n in _owned_branches(child) if li2 == li]:
            if (n.left.type and n.left.type.upper() == "C"
                    and not n.left.divided and not n.right.divided):
                parent_paths.setdefault(n.id or "", []).append(li)
    core_parents = [(p, lis) for p, lis in parent_paths.items() if len(lis) >= 2]
    if not core_parents:
        return _finalise(child), "core_undivide noop"

    path, level_indices = _pick(rng, core_parents)
    for li in level_indices:
        node = lvls[li].by_id(path)
        if node is None or not node.divided:
            continue
        keep = [t for t in (node.left.type, node.right.type)
                if t and not dom.is_generic(t)]
        node.type = keep[0] if keep else (node.left.type or str(_pick(rng, types)))
        node.division = None
        node.left = node.right = None

    return _finalise(child), f"core_undivide {path} ({len(level_indices)} floors)"


def mutate_level_retype(root: dom.Node, rng: np.random.Generator,
                        types: list[str]) -> tuple[dom.Node, str]:
    """Swap the types of two leaves on different storeys.

    The cross-storey equivalent of mutate_retype; directly addresses
    level-constraint failures (e.g. "l1 on wrong level") by moving a room
    type from one floor to another without changing topology or geometry.
    """
    child = copy.deepcopy(root)
    lvls = dom.levels(child)
    if len(lvls) < 2:
        return _finalise(child), "level_retype noop"
    all_lv = _leaves(child)
    li_a, a = _pick(rng, all_lv)
    other = [(li, lf) for li, lf in all_lv if li != li_a]
    if not other:
        return _finalise(child), "level_retype noop"
    li_b, b = _pick(rng, other)
    a.type, b.type = b.type, a.type
    return _finalise(child), f"level_retype {li_a}/{a.id or 'root'}<->{li_b}/{b.id or 'root'}"


def mutate_level_add(root: dom.Node, rng: np.random.Generator,
                     types: list[str]) -> tuple[dom.Node, str]:
    from . import genome as _g

    child = copy.deepcopy(root)
    top = dom.levels(child)[-1]
    dup = _g._copy_storey(top)
    dup.height = top.height
    # Retype all named-room leaves to generic C/O so the new storey carries no
    # duplicated programme rooms.  The outer search retypes them incrementally.
    generic = [t for t in types if t.upper() in ("C", "O")]
    if not generic:
        generic = ["C"]
    for leaf in dup.leaves():
        if leaf.type not in ("C", "O", None):
            leaf.type = str(rng.choice(generic))
    top.above = dup
    return _finalise(child), f"level_add ({len(dom.levels(child))} storeys)"


def mutate_level_delete(root: dom.Node, rng: np.random.Generator,
                        types: list[str]) -> tuple[dom.Node, str]:
    child = copy.deepcopy(root)
    lvls = dom.levels(child)
    if len(lvls) < 2:
        return _finalise(child), "level_delete noop"
    lvls[-2].above = None
    return _finalise(child), f"level_delete ({len(lvls) - 1} storeys)"


MUTATIONS = {
    "divide": mutate_divide,
    "undivide": mutate_undivide,
    "retype": mutate_retype,
    "swap": mutate_swap,
    "rotate": mutate_rotate,
    "reassociate": mutate_reassociate,
    "core_divide": mutate_core_divide,
    "core_undivide": mutate_core_undivide,
    "level_fix": mutate_level_fix,
    "level_compound_fix": mutate_level_compound_fix,
    "place_missing": mutate_place_missing,
    "bridge_circulation": mutate_bridge_circulation,
    "level_retype": mutate_level_retype,
    "level_add": mutate_level_add,
    "level_delete": mutate_level_delete,
    "shape_rotate": mutate_shape_rotate,
    "deslim": mutate_deslim,
    "ruin_recreate": mutate_ruin_recreate,
    "reassign": mutate_reassign,
}


# Exploratory ops that freely pick any leaf/branch; Stage 2 downweights the
# base storey for these via ``base_p`` (DESIGN.md §11.3). The repair op
# ``place_missing`` is deliberately excluded — a missing base room must still be
# repairable — as are the core_* ops, which exist to MAINTAIN the core.
_BASE_P_OPS = ("divide", "undivide", "retype", "swap", "rotate")


def mutate(root: dom.Node, rng: np.random.Generator, types: list[str],
           weights: dict[str, float] | None = None,
           reqs=None, base_p: float = 1.0, fit=None) -> tuple[dom.Node, str]:
    """Apply one random mutation drawn from MUTATIONS."""
    names = sorted(MUTATIONS)
    p = np.array([(weights or {}).get(n, 1.0) for n in names], dtype=float)
    # these operators need programme reqs; disable them when not available
    reqs_ops = ("level_fix", "level_compound_fix", "place_missing", "ruin_recreate",
               "reassign")
    # also takes reqs (to avoid displacing a required room) but works without
    # it — never zero-weighted, unlike reqs_ops above
    reqs_optional_ops = ("bridge_circulation",)
    # these need a Fitness instance to identify genuinely shape-failing leaves
    fit_ops = ("shape_rotate", "deslim")
    if reqs is None:
        for op in reqs_ops:
            p[names.index(op)] = 0.0
    if fit is None:
        for op in fit_ops:
            p[names.index(op)] = 0.0
    if p.sum() == 0:
        p[:] = 1.0
    name = str(rng.choice(names, p=p / p.sum()))
    if name in reqs_ops or name in reqs_optional_ops:
        return MUTATIONS[name](root, rng, types, reqs=reqs)
    if name in fit_ops:
        return MUTATIONS[name](root, rng, types, fit=fit)
    if name in _BASE_P_OPS:
        return MUTATIONS[name](root, rng, types, base_p=base_p)
    return MUTATIONS[name](root, rng, types)


# --------------------------------------------------------------------------- #
# Crossover
# --------------------------------------------------------------------------- #
def _graft(dst: dom.Node, src: dom.Node) -> None:
    """Replace dst's subtree content with a copy of src's (cf. Urb Crossover)."""
    sub = copy.deepcopy(src)
    dst.type = sub.type
    dst.rotation = sub.rotation
    dst.division = sub.division
    dst.left, dst.right = sub.left, sub.right


def crossover(a: dom.Node, b: dom.Node,
              rng: np.random.Generator) -> tuple[dom.Node, dom.Node, str]:
    """Area-matched base-storey subtree exchange (Urb Crossover.pm style):
    pick a random subtree of A's base storey, find the area-closest third of
    B's base subtrees, exchange. A subtree is a contiguous region, so this
    recombines whole neighbourhoods; storeys above re-anchor via encode."""
    from . import geometry

    ca, cb = copy.deepcopy(a), copy.deepcopy(b)
    _finalise(ca)
    _finalise(cb)
    base_a, base_b = dom.levels(ca)[0], dom.levels(cb)[0]
    na = _pick(rng, _level_nodes(base_a))
    by_area = sorted(_level_nodes(base_b),
                     key=lambda n: abs(geometry.area(n) - geometry.area(na)))
    nb = by_area[int(rng.integers(max(1, len(by_area) // 3)))]
    tmp = copy.deepcopy(na)
    _graft(na, nb)
    _graft(nb, tmp)
    desc = f"crossover {na.id or 'root'}<->{nb.id or 'root'}"
    return _finalise(ca), _finalise(cb), desc

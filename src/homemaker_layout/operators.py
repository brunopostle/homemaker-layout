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

    dom._link(root)
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
    # generic classes (circulation/outside/sahn) match case-insensitively,
    # cf. Urb Is_Circulation/Is_Outside
    keep = [t for t in (n.left.type, n.right.type) if t and t[0].lower() not in "cos"]
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
    return {c: r for c, r in reqs.items() if c[0].lower() not in "cos"}


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
            t0 = leaf.type[0].lower()
            if t0 == "o":
                pref = 0
            elif t0 in ("c", "s"):
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
        keep = host.type if host.type and host.type[0].lower() != "o" else "O"
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


def _grow_leaves(lvl: dom.Node, n_leaves: int, rng: np.random.Generator) -> None:
    """Subdivide ``lvl``'s subtree in place until it has ``n_leaves`` leaves."""
    while len(lvl.leaves()) < n_leaves:
        leaf = _pick(rng, lvl.leaves())
        leaf.division = [0.5, 0.5]
        leaf.rotation = int(rng.integers(4))
        leaf.left = dom.Node(type=leaf.type)
        leaf.right = dom.Node(type=leaf.type)
        leaf.type = None


def _assign_adjacency_aware(lvl: dom.Node, room_codes: list[str], reqs,
                            rng: np.random.Generator, door_width: float = 1.2,
                            fixed_circ: "list[dom.Node] | None" = None) -> None:
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
    """
    from . import geometry

    reqs = reqs or {}
    leaves = lvl.leaves()
    n = len(leaves)
    idx = {leaf: i for i, leaf in enumerate(leaves)}
    R = len(room_codes)
    n_circ = max(1, n - (R + 1))  # leftover after rooms + one outside
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
    # dominates the most leaves (keeping the set connected).
    circ = set(seeds) if seeds else {max(leaves, key=lambda L: (deg.get(L, 0), -idx[L]))}
    dominated = set().union(*( _nbrs(s) | {s} for s in circ))
    while len(circ) < n_circ:
        frontier = (set().union(*(_nbrs(s) for s in circ)) - circ) if circ else set()
        if frontier:
            pick = max(frontier, key=lambda L: (len(_nbrs(L) - dominated),
                                                deg.get(L, 0), -idx[L]))
        else:  # disconnected remainder — seed a new component by degree
            rest = [L for L in leaves if L not in circ]
            if not rest:
                break
            pick = max(rest, key=lambda L: (deg.get(L, 0), -idx[L]))
        circ.add(pick)
        dominated |= _nbrs(pick) | {pick}

    for s in circ:
        s.type = "C"

    # Outside on the most peripheral non-circulation leaf (fewest circulation
    # neighbours, then lowest degree) so it does not steal a circulation-adjacent
    # slot a room needs.
    noncirc = [L for L in leaves if L not in circ]
    o_leaf = min(noncirc, key=lambda L: (sum(1 for nb in _nbrs(L) if nb in circ),
                                         deg.get(L, 0), idx[L]))
    o_leaf.type = "O"

    # Rooms onto the remaining leaves, dominated (circulation-adjacent) slots
    # first so adjacency-to-c holds. Codes are placed hardest-constrained first
    # (most adjacency requirements), each onto the open slot that satisfies the
    # most of its requirements against already-typed neighbours (circulation and
    # rooms placed so far) — clustering k1↔da1, da1↔o, etc. Ties broken randomly.
    room_slots = [L for L in noncirc if L is not o_leaf]
    open_slots = sorted(room_slots,
                        key=lambda L: (L in dominated, deg.get(L, 0), -idx[L]),
                        reverse=True)
    codes = [room_codes[i] for i in rng.permutation(len(room_codes))]

    def _n_secondary(code: str) -> int:
        r = reqs.get(code)
        return len([a for a in (r.adjacency if r else []) if a and a[0].lower() != "c"])

    codes.sort(key=_n_secondary, reverse=True)
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
    for leaf in open_slots:  # any leftover slot (count mismatch) → outside
        leaf.type = "O"


def constructive_topology(seed_root: dom.Node, reqs, rng: np.random.Generator,
                          types: list[str], min_storeys: int = 1,
                          adjacency_aware: bool = True) -> dom.Node:
    """Build a seed that instantiates every required space by construction.

    The §11.0 diagnosis: random divide+retype chains leave required programme
    rooms missing on large programmes, so ``missing`` stacking dominates fitness.
    This seeder makes the required room set a *constructive invariant*: it sizes
    each storey to its required rooms (partitioning by ``level``; level-free
    rooms distributed across storeys), plus one circulation ``C`` and one
    outside ``O`` per storey, then assigns the types.  Stochastic (random split
    ratios/rotations and a shuffled type assignment) so a bootstrap batch is
    still a diverse population.

    Returns a finalised deep copy; ``seed_root`` is unchanged.
    """
    from . import genome as _g

    child = copy.deepcopy(seed_root)
    prog = _programme_codes(reqs)
    levels_needed = [r.level for r in prog.values() if r.level is not None]
    n_storeys = max((max(levels_needed) + 1) if levels_needed else 1, min_storeys)

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
        if adjacency_aware:
            # Spend extra leaves on a circulation spine (~one circ per 3 rooms),
            # then assign so every room is adjacent to it (s44). Geometry must be
            # available to read the leaf-adjacency graph; _grow_leaves leaves the
            # tree finalisable and geometry.leaf_graph derives coords on demand.
            n_circ = max(1, -(-len(rooms) // 3))  # ceil(rooms / 3)
            _grow_leaves(lvl, len(rooms) + 1 + n_circ, rng)
            dom._link(child)
            _assign_adjacency_aware(lvl, rooms, reqs, rng)
        else:
            assign = rooms + ["C", "O"]  # +core circulation, +outside
            _grow_leaves(lvl, len(assign), rng)
            leaves = lvl.leaves()
            order = rng.permutation(len(leaves))
            for slot, leaf_idx in enumerate(order):
                leaves[int(leaf_idx)].type = assign[slot] if slot < len(assign) else "O"

    return _finalise(child)


def lift_base_to_storeys(base_root: dom.Node, upper_buckets: list[dict[str, int]],
                         rng: np.random.Generator, types: list[str],
                         reqs=None, adjacency_aware: bool = True) -> dom.Node:
    """Stack upper storeys onto an evolved single-storey base (DESIGN.md §11.3).

    Stage 2 seeder: the Stage-1 base is the credible ground floor and is left
    **untouched**; each upper storey is constructed as a delta that (a) inherits
    and preserves the base's largest circulation ``C`` leaf as a vertically-aligned
    core (so Stage 2 does not carve a core from scratch — the anti-bungalow
    invariant) and (b) instantiates its required room multiset (``upper_buckets``,
    one dict per storey >= 1) by construction, plus one outside ``O``. Stochastic
    splits/assignment keep a bootstrap batch diverse; ``mutate_place_missing``
    repairs any residual gaps during the loop.

    Returns a finalised deep copy; ``base_root`` is unchanged.
    """
    from . import genome as _g, geometry as _geo

    child = copy.deepcopy(base_root)
    base = dom.levels(child)[0]
    base.above = None  # start from the single-storey base only

    base_cs = [lf for lf in base.leaves()
               if lf.type and lf.type[0].lower() == "c"]
    core_path = max(base_cs, key=_geo.area).id if base_cs else None

    prev = base
    for bucket in upper_buckets:
        dup = _g._copy_storey(prev)
        dup.height = prev.height
        core_node = dup.by_id(core_path) if core_path is not None else None

        rooms = [code for code, cnt in bucket.items() for _ in range(cnt)]

        def _free() -> list[dom.Node]:
            return [lf for lf in dup.leaves() if lf is not core_node]

        if adjacency_aware:
            # ld5 (§11.7): grow the upper floor a circulation spine (~one circ per
            # 3 rooms, the inherited core counted) and assign rooms around it via
            # the geometric leaf graph, seeding the dominating set from the
            # inherited vertical core so the spine grows off the core, not anew.
            n_circ = max(1, -(-len(rooms) // 3))  # ceil(rooms / 3)
            target_total = len(rooms) + 1 + n_circ
            n_free_target = target_total - (1 if core_node is not None else 0)
            while len(_free()) < n_free_target:
                leaf = _pick(rng, _free())
                leaf.division = [0.5, 0.5]
                leaf.rotation = int(rng.integers(4))
                leaf.left = dom.Node(type=leaf.type)
                leaf.right = dom.Node(type=leaf.type)
                leaf.type = None
            prev.above = dup
            dom._link(child)  # link so the upper storey's geometry is computable
            _assign_adjacency_aware(
                dup, rooms, reqs, rng,
                fixed_circ=[core_node] if core_node is not None else None)
        else:
            assign = rooms + ["O"]  # courtyard / outside on the upper floor
            if core_node is None:
                assign.append("C")  # no inherited core to reuse — make one
            while len(_free()) < len(assign):
                leaf = _pick(rng, _free())
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

        prev = dup

    return _finalise(child)


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
                if t and t[0].lower() not in "cos"]
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
    "core_divide": mutate_core_divide,
    "core_undivide": mutate_core_undivide,
    "level_fix": mutate_level_fix,
    "level_compound_fix": mutate_level_compound_fix,
    "place_missing": mutate_place_missing,
    "level_retype": mutate_level_retype,
    "level_add": mutate_level_add,
    "level_delete": mutate_level_delete,
}


# Exploratory ops that freely pick any leaf/branch; Stage 2 downweights the
# base storey for these via ``base_p`` (DESIGN.md §11.3). The repair op
# ``place_missing`` is deliberately excluded — a missing base room must still be
# repairable — as are the core_* ops, which exist to MAINTAIN the core.
_BASE_P_OPS = ("divide", "undivide", "retype", "swap", "rotate")


def mutate(root: dom.Node, rng: np.random.Generator, types: list[str],
           weights: dict[str, float] | None = None,
           reqs=None, base_p: float = 1.0) -> tuple[dom.Node, str]:
    """Apply one random mutation drawn from MUTATIONS."""
    names = sorted(MUTATIONS)
    p = np.array([(weights or {}).get(n, 1.0) for n in names], dtype=float)
    # these operators need programme reqs; disable them when not available
    reqs_ops = ("level_fix", "level_compound_fix", "place_missing")
    if reqs is None:
        for op in reqs_ops:
            p[names.index(op)] = 0.0
    if p.sum() == 0:
        p[:] = 1.0
    name = str(rng.choice(names, p=p / p.sum()))
    if name in reqs_ops:
        return MUTATIONS[name](root, rng, types, reqs=reqs)
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

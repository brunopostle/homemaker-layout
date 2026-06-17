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
                  types: list[str]) -> tuple[dom.Node, str]:
    child = copy.deepcopy(root)
    li, leaf = _pick(rng, _leaves(child))
    leaf.division = [0.5, 0.5]
    leaf.rotation = int(rng.integers(4))
    leaf.left = dom.Node(type=leaf.type)
    leaf.right = dom.Node(type=str(_pick(rng, types)))
    leaf.type = None
    return _finalise(child), f"divide {li}/{leaf.id or 'root'}"


def mutate_undivide(root: dom.Node, rng: np.random.Generator,
                    types: list[str]) -> tuple[dom.Node, str]:
    child = copy.deepcopy(root)
    cands = [(li, n) for li, n in _owned_branches(child)
             if not n.left.divided and not n.right.divided]
    if not cands:
        return _finalise(child), "undivide noop"
    li, n = _pick(rng, cands)
    # generic classes (circulation/outside/sahn) match case-insensitively,
    # cf. Urb Is_Circulation/Is_Outside
    keep = [t for t in (n.left.type, n.right.type) if t and t[0].lower() not in "cos"]
    n.type = keep[0] if keep else (n.left.type or str(_pick(rng, types)))
    n.division = None
    n.left = n.right = None
    return _finalise(child), f"undivide {li}/{n.id or 'root'}"


def mutate_retype(root: dom.Node, rng: np.random.Generator,
                  types: list[str]) -> tuple[dom.Node, str]:
    child = copy.deepcopy(root)
    li, leaf = _pick(rng, _leaves(child))
    leaf.type = str(_pick(rng, [t for t in types if t != leaf.type] or types))
    return _finalise(child), f"retype {li}/{leaf.id or 'root'}->{leaf.type}"


def mutate_swap(root: dom.Node, rng: np.random.Generator,
                types: list[str]) -> tuple[dom.Node, str]:
    child = copy.deepcopy(root)
    cands = _owned_branches(child)
    if not cands:  # undivided topology (e.g. a bare plot seed)
        return _finalise(child), "swap noop"
    li, n = _pick(rng, cands)
    n.left, n.right = n.right, n.left
    return _finalise(child), f"swap {li}/{n.id or 'root'}"


def mutate_rotate(root: dom.Node, rng: np.random.Generator,
                  types: list[str]) -> tuple[dom.Node, str]:
    # re-orient a live cut; live rotation = node without a below link (base
    # storey or inside an upper-storey divide delta)
    child = copy.deepcopy(root)
    cands = [(li, n) for li, n in _owned_branches(child) if n.below is None]
    if not cands:
        return _finalise(child), "rotate noop"
    li, n = _pick(rng, cands)
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


def constructive_topology(seed_root: dom.Node, reqs, rng: np.random.Generator,
                          types: list[str], min_storeys: int = 1) -> dom.Node:
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
        assign = list(buckets[li]) + ["C", "O"]  # +core circulation, +outside
        _grow_leaves(lvl, len(assign), rng)
        leaves = lvl.leaves()
        order = rng.permutation(len(leaves))
        for slot, leaf_idx in enumerate(order):
            leaves[int(leaf_idx)].type = assign[slot] if slot < len(assign) else "O"

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


def mutate(root: dom.Node, rng: np.random.Generator, types: list[str],
           weights: dict[str, float] | None = None,
           reqs=None) -> tuple[dom.Node, str]:
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

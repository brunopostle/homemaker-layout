"""Operator tests (oracle-free): every child is a valid, canonical genome."""

from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, genome, operators

CORPUS = Path(__file__).parent.parent / "examples" / "programme-house"
FILES = ["2f45907abd9accac2a124d311732f749.dom", "candidate-002.dom",
         "c964435454c459f86c3ed9a5a7621132.dom"]
TYPES = ["k1", "l1", "b1", "b2", "t1", "C", "O"]

pytestmark = pytest.mark.skipif(not CORPUS.is_dir(), reason="Corpus not available")


def canonical(root: dom.Node) -> None:
    """Child must encode to a genome that decode/encode holds fixed."""
    g1 = genome.encode(root)
    g2 = genome.encode(genome.decode(g1))
    assert g2 == g1


@pytest.mark.parametrize("name", sorted(operators.MUTATIONS))
def test_mutations_yield_canonical_genomes(name):
    op = operators.MUTATIONS[name]
    for f in FILES:
        root = genome.decode(genome.encode(dom.load(str(CORPUS / f))))
        for seed in range(5):
            child, desc = op(root, np.random.default_rng(seed), TYPES)
            assert desc.startswith(name.split("_")[0]) or "noop" in desc
            canonical(child)
            # the parent must never be mutated in place
            canonical(root)


def test_divide_grows_and_undivide_shrinks():
    root = genome.decode(genome.encode(dom.load(str(CORPUS / FILES[0]))))
    n_leaves = sum(len(lvl.leaves()) for lvl in dom.levels(root))
    child, _ = operators.mutate_divide(root, np.random.default_rng(0), TYPES)
    assert sum(len(lvl.leaves()) for lvl in dom.levels(child)) == n_leaves + 1
    child, desc = operators.mutate_undivide(root, np.random.default_rng(0), TYPES)
    if "noop" not in desc:
        assert sum(len(lvl.leaves()) for lvl in dom.levels(child)) < n_leaves


def test_level_add_delete():
    root = genome.decode(genome.encode(dom.load(str(CORPUS / FILES[0]))))
    n = len(dom.levels(root))
    up, _ = operators.mutate_level_add(root, np.random.default_rng(0), TYPES)
    assert len(dom.levels(up)) == n + 1
    canonical(up)
    down, _ = operators.mutate_level_delete(root, np.random.default_rng(0), TYPES)
    assert len(dom.levels(down)) == n - 1


def test_relink_clears_stale_below_after_base_undivide():
    # regression: dom._link must clear below-links whose path vanished, or
    # geometry on the mutated tree dereferences orphaned nodes
    from homemaker_layout import geometry

    root = genome.decode(genome.encode(dom.load(str(CORPUS / FILES[0]))))
    # force an undivide on the BASE storey specifically
    base = dom.levels(root)[0]
    cands = [n for li, n in operators._owned_branches(root)
             if li == 0 and not n.left.divided and not n.right.divided]
    assert cands, "corpus design has no base leaf-pair branch"
    import copy as _copy

    child = _copy.deepcopy(root)
    target = dom.levels(child)[0].by_id(cands[0].id)
    target.division = None
    target.left = target.right = None
    target.type = "l1"
    dom._link(child)
    geometry.clear_cache()
    for lvl in dom.levels(child):
        for leaf in lvl.leaves():
            for i in range(4):
                geometry.coordinate(leaf, i)  # must not raise
    canonical(child)
    assert base.by_id(cands[0].id) is not None  # parent untouched


def test_all_mutations_survive_undivided_tree():
    # an undivided plot (init.dom-style seed) must never crash an operator
    bare = dom.Node(type="O", node=[[0, 0], [10, 0], [10, 8], [0, 8]],
                    height=2.7, wall_outer=0.25, wall_inner=0.08)
    dom._link(bare)
    for name, op in operators.MUTATIONS.items():
        for seed in range(3):
            child, desc = op(bare, np.random.default_rng(seed), TYPES)
            assert desc, name
            canonical(child)


def test_unfold_shared_leaves_materialises_deficit():
    # homemaker-py-yaa: a share=k leaf must unfold into k distinct same-code
    # leaves (paying down the count deficit) with the share stamp cleared, while
    # every non-shared leaf keeps its identity. Footprint is preserved: the k
    # children tile the original leaf, so total plot area is unchanged.
    from homemaker_layout import geometry

    root = dom.Node(node=[[0, 0], [12, 0], [12, 8], [0, 8]],
                    height=2.7, wall_outer=0.25, wall_inner=0.08,
                    rotation=0, division=[0.5, 0.5])
    root.left = dom.Node(type="n", share=3, share_type="n")   # 3-room shared leaf
    root.right = dom.Node(type="C")                            # untouched
    dom._link(root)
    geometry.clear_cache()
    area_before = geometry.area(root)

    created = operators.unfold_shared_leaves(root)

    assert created == 2                                        # 3 rooms - 1 leaf
    leaves = root.leaves()
    assert sum(1 for lf in leaves if lf.type == "n") == 3      # three distinct n
    assert sum(1 for lf in leaves if lf.type == "C") == 1      # C untouched
    assert all(lf.share == 1 for lf in leaves)                 # stamps cleared
    geometry.clear_cache()
    assert geometry.area(root) == pytest.approx(area_before)   # footprint kept
    canonical(root)                                            # genome round-trips


HARBOR = Path(__file__).parent.parent / "examples" / "harbor-house"


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_constructive_topology_has_no_missing_spaces():
    # §11.2: the constructive seeder must instantiate every required space by
    # construction (count + level), so check_space_counts reports zero missing.
    from homemaker_layout import graph, programme

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    seed = dom.load(str(HARBOR / "init.dom"))
    for trial in range(5):
        root = operators.constructive_topology(
            seed, reqs, np.random.default_rng(trial), types)
        _, missing = graph.check_space_counts(root, reqs)
        assert missing == [], f"trial {trial} left {missing}"
        # required level partition respected: level-N rooms land on storey N
        lvls = dom.levels(root)
        for code, req in reqs.items():
            if code[0].lower() in "cos" or req.level is None:
                continue
            for li, lvl in enumerate(lvls):
                for leaf in lvl.leaves():
                    if leaf.type == code:
                        assert li == req.level
        canonical(root)


def test_leaf_share_explicit_and_type_guarded():
    # erc.3 §13.3: explicit multiplicity, honoured only while type==share_type so
    # a retype silently invalidates a stale share (no operator reset needed).
    from homemaker_layout.graph import leaf_share

    leaf = dom.Node(type="n", share=3, share_type="n")
    assert leaf_share(leaf, 4) == 3
    assert leaf_share(leaf, 2) == 2          # clamped at max_share
    leaf.type = "ba"                          # retyped → share no longer matches
    assert leaf_share(leaf, 4) == 1
    plain = dom.Node(type="n")                # default share 1
    assert leaf_share(plain, 4) == 1


def _reqs(**share_kw):
    """Build a tiny programme: sized 'b' (share per kwarg), sized 'k', unsized 'C'."""
    from homemaker_layout.programme import SpaceReq

    b = SpaceReq(code="b", size=12.0, has_size=True, count=5)
    if "b" in share_kw:
        b.share, b.has_share = share_kw["b"], True
    k = SpaceReq(code="k", size=20.0, has_size=True, count=4)
    if "k" in share_kw:
        k.share, k.has_share = share_kw["k"], True
    c = SpaceReq(code="C", size=0.0, has_size=False, count=3)  # unsized circulation
    return {"b": b, "k": k, "C": c}


def _mults(plan_entry):
    return sorted(plan_entry)


def test_share_grain_opt_in_mode():
    # homemaker-py-x3b: factor 0 = per-code opt-in. A code shares iff it carries an
    # explicit share:N>=2; sized codes without the key, and unsized codes, do not.
    reqs = _reqs(b=3)
    assert operators._share_grain(reqs["b"], 0) == 3   # explicit opt-in
    assert operators._share_grain(reqs["k"], 0) == 1   # sized but no key → unshared
    assert operators._share_grain(reqs["C"], 0) == 1   # unsized → never shareable
    assert operators._share_grain(_reqs(b=1)["b"], 0) == 1  # share:1 stays unshared


def test_share_grain_global_mode_with_per_code_override():
    # factor>=2 = global: every sized code shares at the factor unless its entry
    # overrides — share:1 opts OUT, share:N sets that code's grain to N.
    reqs = _reqs(b=1, k=4)
    assert operators._share_grain(reqs["b"], 3) == 1   # explicit share:1 → opt out
    assert operators._share_grain(reqs["k"], 3) == 4   # explicit share:4 → grain 4
    assert operators._share_grain(_reqs()["k"], 3) == 3  # no key → global factor 3
    assert operators._share_grain(_reqs()["C"], 3) == 1  # unsized → never shareable


def test_share_rooms_opt_in_groups_only_flagged_code():
    # factor 0: only 'b' (share:3) collapses into runs of 3; 'k' and 'C' untouched.
    rooms = ["b"] * 5 + ["k"] * 4 + ["C"] * 3
    reduced, plan = operators._share_rooms(rooms, _reqs(b=3), 0)
    assert _mults(plan["b"]) == [2, 3]      # 5 rooms → runs of 3 + 2
    assert plan["k"] == [1, 1, 1, 1]        # no share key → unshared
    assert plan["C"] == [1, 1, 1]           # unsized → unshared
    assert reduced.count("b") == 2 and reduced.count("k") == 4


def test_share_rooms_global_with_opt_out():
    # factor 3 global: 'k' shares at 3 (no key), 'b' opted OUT via share:1.
    rooms = ["b"] * 5 + ["k"] * 4
    reduced, plan = operators._share_rooms(rooms, _reqs(b=1), 3)
    assert plan["b"] == [1, 1, 1, 1, 1]     # share:1 → opt out, stays 5 leaves
    assert _mults(plan["k"]) == [1, 3]      # 4 rooms → run of 3 + 1
    # multiplicities always sum back to the original room counts (no rooms lost)
    assert sum(plan["b"]) == 5 and sum(plan["k"]) == 4


def test_share_rooms_default_off_parity():
    # Master switch off path: callers never invoke _share_rooms, but a single
    # instance or grain<2 must yield the identity plan regardless of factor.
    rooms = ["b", "k", "k", "C"]
    reduced, plan = operators._share_rooms(rooms, _reqs(), 0)  # opt-in, no keys
    assert reduced == rooms and all(m == 1 for ms in plan.values() for m in ms)


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_leaf_sharing_reduces_leaves_and_covers_rooms():
    # erc.3 §13.3: leaf_sharing builds fewer leaves, and coverage-counting lets
    # the larger shared leaves satisfy several same-code rooms without missing.
    from homemaker_layout import graph, programme

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    seed = dom.load(str(HARBOR / "init.dom"))
    for trial in range(3):
        plain = operators.constructive_topology(
            seed, reqs, np.random.default_rng(trial), types)
        shared = operators.constructive_topology(
            seed, reqs, np.random.default_rng(trial), types,
            leaf_sharing=True, leaf_share_factor=2)

        n_plain = sum(len(l.leaves()) for l in dom.levels(plain))
        n_shared = sum(len(l.leaves()) for l in dom.levels(shared))
        assert n_shared < n_plain, f"trial {trial}: {n_shared} !< {n_plain}"

        # Default-OFF parity: the flag defaults reproduce the strict count check.
        assert (graph.check_space_counts(shared, reqs)
                == graph.check_space_counts(shared, reqs, leaf_sharing=False))

        # Coverage suppresses missings: the shared tree scored WITH leaf_sharing
        # has fewer missing fails than the same tree scored without it.
        _strict, miss_off = graph.check_space_counts(shared, reqs)
        _cov, miss_on = graph.check_space_counts(shared, reqs, leaf_sharing=True)
        assert len(miss_on) < len(miss_off), f"trial {trial}: sharing didn't cover"


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_interior_outside_seeds_landlocked_wells_and_scales_count():
    # ld2 §13.6: interior_outside seeds O on the most landlocked leaves (lower
    # external-perimeter exposure) instead of the most peripheral one, and scales
    # the O count with the room count. Construction must still cover every room.
    from homemaker_layout import graph, geometry, programme

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    seed = dom.load(str(HARBOR / "init.dom"))

    def _outside_exposure(root):
        geometry.clear_cache()
        dom._link(root)
        exps, n_o = [], 0
        for lvl in dom.levels(root):
            for leaf in lvl.leaves():
                if leaf.type and leaf.type[0].lower() == "o":
                    n_o += 1
                    exps.append(operators._ext_exposure(leaf))
        return n_o, (sum(exps) / len(exps) if exps else 0.0)

    for trial in range(3):
        peri = operators.constructive_topology(
            seed, reqs, np.random.default_rng(trial), types,
            interior_outside=False)
        inter = operators.constructive_topology(
            seed, reqs, np.random.default_rng(trial), types,
            interior_outside=True, outside_divisor=3)

        # no missing rooms either way
        assert graph.check_space_counts(inter, reqs)[1] == []

        n_peri, _exp_peri = _outside_exposure(peri)
        n_inter, exp_inter = _outside_exposure(inter)

        # the lever adds more outside leaves (scaled with room count)…
        assert n_inter > n_peri, f"trial {trial}: {n_inter} !> {n_peri}"
        # …and places them on landlocked leaves: a well averaging < 1 external
        # plot edge is interior by construction (peripheral mode does not aim
        # for this — its single O is chosen by circulation distance, so it can
        # land anywhere — hence we assert the absolute landlocked property).
        assert exp_inter < 1.0, (
            f"trial {trial}: interior O wells not landlocked (mean exp {exp_inter})")


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_adjacency_aware_seeding_cuts_adjacency_access_fails():
    # s44: adjacency-aware construction clusters rooms around a connected
    # circulation spine, cutting the adjacency-to-c + access fails that random
    # type assignment leaves stranded. Compare like-for-like over several seeds.
    import copy

    from homemaker_layout import fitness, programme

    reqs = programme.load_programme_dir(str(HARBOR))
    conf, cost = fitness.load_config(str(HARBOR))
    fit = fitness.Fitness(conf, cost)
    types = sorted(reqs) + ["C", "O"]
    seed = dom.load(str(HARBOR / "init.dom"))

    def adj_access(aware: bool) -> float:
        total = 0
        for trial in range(6):
            root = operators.constructive_topology(
                seed, reqs, np.random.default_rng(trial), types,
                adjacency_aware=aware)
            _, fails = fit.score_with_fails(copy.deepcopy(root))
            total += sum(1 for f in fails if "adjacent" in f or "access" in f
                         or "inaccessible" in f)
        return total / 6

    assert adj_access(True) < adj_access(False)


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_adjacency_aware_lift_cuts_adjacency_access_fails():
    # ld5: lift_base_to_storeys grows the upper-floor circulation spine off the
    # inherited core and clusters rooms around it, cutting the same fail classes
    # on the storeys above the base.
    import copy

    from homemaker_layout import fitness, programme

    reqs = programme.load_programme_dir(str(HARBOR))
    conf, cost = fitness.load_config(str(HARBOR))
    fit = fitness.Fitness(conf, cost)
    types = sorted(reqs) + ["C", "O"]
    n_st = programme.n_storeys_required(reqs)
    seed = dom.load(str(HARBOR / "init.dom"))

    def adj_access(aware: bool) -> float:
        total = 0
        for trial in range(5):
            rng = np.random.default_rng(trial)
            buckets = programme.partition_rooms_by_storey(reqs, n_st, rng)
            base = operators.constructive_topology(seed, reqs, rng, types)
            base0 = dom.levels(base)[0]
            base0.above = None
            lifted = operators.lift_base_to_storeys(
                base0, buckets[1:], rng, types, reqs=reqs, adjacency_aware=aware)
            _, fails = fit.score_with_fails(copy.deepcopy(lifted))
            total += sum(1 for f in fails if "adjacent" in f or "access" in f
                         or "inaccessible" in f)
        return total / 5

    assert adj_access(True) < adj_access(False)


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_place_missing_repairs_deficient_tree():
    # §11.2 repair: iterating mutate_place_missing drives a deficient design's
    # missing-space count to zero, then noops once the required set is complete.
    from homemaker_layout import graph, programme

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    rng = np.random.default_rng(0)
    root = dom.load(str(HARBOR / "generated.dom"))
    _, missing0 = graph.check_space_counts(root, reqs)
    assert missing0, "fixture should start deficient"
    for _ in range(len(missing0) + 5):
        root, desc = operators.mutate_place_missing(root, rng, types, reqs=reqs)
        canonical(root)
        _, missing = graph.check_space_counts(root, reqs)
        if not missing:
            break
    assert missing == []
    _, desc = operators.mutate_place_missing(root, rng, types, reqs=reqs)
    assert desc == "place_missing noop"


def test_crossover_yields_canonical_pair():
    a = genome.decode(genome.encode(dom.load(str(CORPUS / FILES[0]))))
    b = genome.decode(genome.encode(dom.load(str(CORPUS / FILES[1]))))
    for seed in range(5):
        ca, cb, desc = operators.crossover(a, b, np.random.default_rng(seed))
        assert desc.startswith("crossover")
        canonical(ca)
        canonical(cb)


# --------------------------------------------------------------------------- #
# 9gp.2 — M3 re-association move
# --------------------------------------------------------------------------- #
def _leaf_types(root: dom.Node) -> list[str]:
    return sorted(lf.type or "." for lvl in dom.levels(root) for lf in lvl.leaves())


def _same_axis_chain() -> dom.Node:
    """A 3-leaf ``(a|b)|c`` tree with two parallel (same-orientation) cuts."""
    root = dom.Node(rotation=0, division=[0.4, 0.4])
    root.left = dom.Node(rotation=0, division=[0.5, 0.5])
    root.left.left = dom.Node(type="A")
    root.left.right = dom.Node(type="B")
    root.right = dom.Node(type="C")
    dom._link(root)
    return root


def test_reassociate_preserves_leaves_changes_shape():
    root = _same_axis_chain()
    before_types = _leaf_types(root)
    before_sig = genome.signature(root)
    child, desc = operators.mutate_reassociate(root, np.random.default_rng(0), TYPES)
    assert "noop" not in desc
    # leaf set + types are an invariant; only the tree shape changes
    assert _leaf_types(child) == before_types
    assert genome.signature(child) != before_sig
    canonical(child)
    # parent untouched in place
    assert genome.signature(root) == before_sig
    canonical(root)


def test_reassociate_noop_on_perpendicular_cuts():
    # Outer cut rotation 0, inner cut rotation 1 (perpendicular) → not the
    # associativity precondition, so there is no candidate and it noops.
    root = dom.Node(rotation=0, division=[0.4, 0.4])
    root.left = dom.Node(rotation=1, division=[0.5, 0.5])
    root.left.left = dom.Node(type="A")
    root.left.right = dom.Node(type="B")
    root.right = dom.Node(type="C")
    dom._link(root)
    _, desc = operators.mutate_reassociate(root, np.random.default_rng(0), TYPES)
    assert desc == "reassociate noop"


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_reassociate_on_corpus_is_canonical_and_total():
    from homemaker_layout import programme

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    root = dom.load(str(HARBOR / "generated.dom"))
    before = _leaf_types(root)
    for seed in range(8):
        child, desc = operators.mutate_reassociate(root, np.random.default_rng(seed), types)
        canonical(child)
        if "noop" not in desc:
            # leaf multiset preserved even on a real multi-storey tree
            assert _leaf_types(child) == before


# --------------------------------------------------------------------------- #
# 9gp.1 — shape-feasibility proxy
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_predicted_shape_fails_is_nonneg_and_pure():
    from homemaker_layout import fitness, programme

    reqs = programme.load_programme_dir(str(HARBOR))
    conf, cost = fitness.load_config(str(HARBOR))
    fit = fitness.Fitness(conf, cost)
    root = dom.load(str(HARBOR / "generated.dom"))
    n_leaves = sum(len(lvl.leaves()) for lvl in dom.levels(root))

    pred = operators.predicted_shape_fails(root, reqs, fit)
    assert isinstance(pred, int) and pred >= 0
    # input root is untouched (a deep copy is laid out and scored)
    assert sum(len(lvl.leaves()) for lvl in dom.levels(root)) == n_leaves
    # deterministic
    assert operators.predicted_shape_fails(root, reqs, fit) == pred

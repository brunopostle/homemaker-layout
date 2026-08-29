"""Operator tests (oracle-free): every child is a valid, canonical genome."""

import copy
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
    # regression: dom.link must clear below-links whose path vanished, or
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
    dom.link(child)
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
    dom.link(bare)
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
    dom.link(root)
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


def test_unfold_shared_leaves_above_grain_cap():
    # homemaker-py-kpu (Schedule B): ``above=cap`` unfolds only leaves whose
    # share EXCEEDS the grain cap, leaving smaller-share leaves collapsed for the
    # next lower grain. A share=4 leaf unfolds under above=3; a share=3 leaf does
    # not — it stays a single shared leaf.
    from homemaker_layout import geometry

    root = dom.Node(node=[[0, 0], [12, 0], [12, 8], [0, 8]],
                    height=2.7, wall_outer=0.25, wall_inner=0.08,
                    rotation=0, division=[0.5, 0.5])
    root.left = dom.Node(type="n", share=4, share_type="n")    # exceeds cap 3
    root.right = dom.Node(type="m", share=3, share_type="m")   # at cap 3, kept
    dom.link(root)
    geometry.clear_cache()

    created = operators.unfold_shared_leaves(root, above=3)

    assert created == 3                                        # only the share=4 leaf
    leaves = root.leaves()
    assert sum(1 for lf in leaves if lf.type == "n") == 4      # materialised
    assert all(lf.share == 1 for lf in leaves if lf.type == "n")
    m = [lf for lf in leaves if lf.type == "m"]
    assert len(m) == 1 and m[0].share == 3                     # kept collapsed
    canonical(root)


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
        dom.link(root)
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
def test_construction_beam_width_default_matches_greedy():
    # homemaker-py-c94: beam_width=1 (the default, both explicit and implicit)
    # must reproduce the prior one-shot greedy room placement byte-for-byte.
    from homemaker_layout import programme

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    seed = dom.load(str(HARBOR / "init.dom"))
    for trial in range(3):
        plain = operators.constructive_topology(
            seed, reqs, np.random.default_rng(trial), types)
        explicit = operators.constructive_topology(
            seed, reqs, np.random.default_rng(trial), types,
            construction_beam_width=1)
        assert genome.encode(plain) == genome.encode(explicit)


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_construction_beam_width_yields_valid_seed():
    # A beam_width>1 seed must still satisfy the same construction invariants
    # as the greedy path: every required space present, canonical genome.
    from homemaker_layout import graph, programme

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    seed = dom.load(str(HARBOR / "init.dom"))
    for trial in range(5):
        root = operators.constructive_topology(
            seed, reqs, np.random.default_rng(trial), types,
            construction_beam_width=4)
        _, missing = graph.check_space_counts(root, reqs)
        assert missing == [], f"trial {trial} left {missing}"
        canonical(root)


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_construction_beam_width_lift_yields_valid_seed():
    # Each upper storey's placed room multiset must match its requested
    # bucket exactly (the invariant lift_base_to_storeys/_assign_adjacency_
    # aware owns) and the whole tree must stay canonical. Unlike
    # constructive_topology, a base built from the FULL reqs (as in
    # test_adjacency_aware_lift_cuts_adjacency_access_fails above) need not
    # sum with an independently-drawn upper bucket split to the whole-building
    # total, so this checks the per-storey bucket invariant instead of
    # graph.check_space_counts.
    from collections import Counter

    from homemaker_layout import programme

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    n_st = programme.n_storeys_required(reqs)
    seed = dom.load(str(HARBOR / "init.dom"))
    for trial in range(3):
        rng = np.random.default_rng(trial)
        buckets = programme.partition_rooms_by_storey(reqs, n_st, rng)
        base = operators.constructive_topology(seed, reqs, rng, types)
        base0 = dom.levels(base)[0]
        base0.above = None
        lifted = operators.lift_base_to_storeys(
            base0, buckets[1:], rng, types, reqs=reqs,
            construction_beam_width=4)
        lvls = dom.levels(lifted)
        for bucket, lvl in zip(buckets[1:], lvls[1:]):
            placed = Counter(lf.type for lf in lvl.leaves() if lf.type in bucket)
            assert placed == Counter(bucket), f"trial {trial}: {placed} != {bucket}"
        canonical(lifted)


def test_beam_place_rooms_is_deterministic_given_inputs():
    # _beam_place_rooms takes no rng — same inputs must give the same
    # placement every call (only the caller's code-order shuffle is
    # stochastic, already exercised via constructive_topology above).
    class Req:
        def __init__(self, adjacency):
            self.adjacency = adjacency

    reqs = {"a": Req([("c",)]), "b": Req([("a",)]), "c": Req([])}
    slots = [dom.Node(type=None) for _ in range(3)]
    idx = {L: i for i, L in enumerate(slots)}
    deg = {L: 1 for L in slots}
    dominated = set(slots)

    def _nbrs(L):
        return set(slots) - {L}

    codes = ["a", "b"]
    r1 = operators._beam_place_rooms(codes, slots, dominated, deg, idx,
                                     _nbrs, reqs, beam_width=2)
    r2 = operators._beam_place_rooms(codes, slots, dominated, deg, idx,
                                     _nbrs, reqs, beam_width=2)
    assert r1 == r2


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_construction_assign_cpsat_yields_valid_seed():
    # homemaker-py-2g7.5: the CP-SAT room-labelling path must satisfy the same
    # construction invariants as the greedy path — every required space
    # present, canonical genome.
    from homemaker_layout import graph, programme

    from homemaker_layout import cpsat as cpsat_mod

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    seed = dom.load(str(HARBOR / "init.dom"))

    # This test asserts INVARIANTS -- every required space present, canonical
    # genome -- which do not depend on the labelling being optimal. So it buys
    # its runtime back with a reduced deterministic budget (homemaker-py-7t1);
    # harbor's model needs ~3.6 work units for optimality since §38.14's added
    # adjacency, and paying that here dominated the suite for no extra coverage.
    #
    # The trap: too small a budget makes solve_room_labels return None, and
    # _assign_adjacency_aware then falls back to GREEDY -- the test would pass
    # while exercising nothing. Guarded by counting fallbacks and requiring the
    # solver to have answered every time.
    fell_back = []
    orig = cpsat_mod.solve_room_labels

    def counting(*a, **k):
        r = orig(*a, **k)
        fell_back.append(r is None)
        return r

    cpsat_mod.solve_room_labels = counting
    operators.cpsat = cpsat_mod
    try:
        for trial in range(5):
            root = operators.constructive_topology(
                seed, reqs, np.random.default_rng(trial), types,
                assign_solver="cpsat", cpsat_limits=(30.0, 0.25))
            _, missing = graph.check_space_counts(root, reqs)
            assert missing == [], f"trial {trial} left {missing}"
            canonical(root)
    finally:
        cpsat_mod.solve_room_labels = orig
        operators.cpsat = cpsat_mod

    assert fell_back and not any(fell_back), (
        f"cpsat fell back to greedy on {sum(fell_back)}/{len(fell_back)} solves "
        f"-- the reduced budget is too small and this test stopped testing cpsat")


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_assign_cpsat_matches_or_beats_greedy_secondary_adjacency():
    # homemaker-py-2g7.5: CP-SAT solves the same room-labelling decision the
    # greedy/beam heuristic approximates exactly — its secondary-adjacency
    # (not the access/adjacent-to-c fails the dominating-set step already
    # solves) fail count must be strictly lower in aggregate.
    import copy

    from homemaker_layout import fitness, programme

    reqs = programme.load_programme_dir(str(HARBOR))
    conf, cost = fitness.load_config(str(HARBOR))
    fit = fitness.Fitness(conf, cost)
    types = sorted(reqs) + ["C", "O"]
    seed = dom.load(str(HARBOR / "init.dom"))

    def secondary_fails(solver: str) -> list[int]:
        counts = []
        for trial in range(10):
            root = operators.constructive_topology(
                seed, reqs, np.random.default_rng(trial), types,
                assign_solver=solver)
            _, fails = fit.score_with_fails(copy.deepcopy(root))
            counts.append(sum(1 for f in fails if "not adjacent to" in f))
        return counts

    # Per-seed outcomes are noisy (both solvers depend on the same random
    # room-order shuffle before falling into their own placement logic), so
    # the comparison is on the aggregate over several seeds, not every seed
    # individually.
    #
    # This used to run the cpsat arm THREE times and compare the mean, because
    # `homemaker-py-fdp` left the cpsat path non-bit-reproducible -- a single
    # 10-seed aggregate could straddle greedy's deterministic value, so the test
    # was flaky by construction. fdp is fixed (§38.15: `noncirc` was ordered by
    # `id()`), so cpsat is now deterministic and one pass says exactly as much
    # as three did, at a third of the cost -- this test dominated the suite.
    #
    # NOTE this measures ONLY secondary-adjacency fails ("not adjacent to"),
    # which is the decision cpsat actually solves. It is not a claim that cpsat
    # seeds better overall: measured over 12 seeds it is markedly WORSE on total
    # fails (§38.20), which is why `assign_solver` stays default greedy.
    greedy = sum(secondary_fails("greedy"))
    cpsat = sum(secondary_fails("cpsat"))
    assert cpsat < greedy, f"cpsat {cpsat} vs greedy {greedy}"


def test_reassign_noop_without_reqs():
    root = genome.decode(genome.encode(dom.load(str(CORPUS / FILES[0]))))
    child, desc = operators.mutate_reassign(root, np.random.default_rng(0), TYPES)
    assert desc == "reassign noop"
    canonical(child)


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_reassign_fires_and_preserves_room_multiset():
    # homemaker-py-2g7.5: the reassign operator must fire (find at least one
    # wing to re-label) on a real seeded design, and it must preserve the
    # wing's exact room-code multiset — only the leaf<->code labelling
    # changes, never the topology or which codes are present.
    from collections import Counter

    from homemaker_layout import programme

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    seed = dom.load(str(HARBOR / "init.dom"))

    # Sweep several constructive seeds rather than pinning seed 0. The operator
    # only fires when it finds a wing worth re-labelling, so a seed that happens
    # to be already-optimal is a legitimate noop, not a broken operator --
    # declaring harbor's `t -> n` adjacency (homemaker-py-3qj) made the
    # adjacency-aware seeder good enough that seed 0 became exactly that case,
    # while 5 of 6 other seeds still fire. Pinning one seed was testing the
    # seeder's luck, not the operator.
    fired = False
    for construct_seed in range(6):
        root = operators.constructive_topology(
            seed, reqs, np.random.default_rng(construct_seed), types)
        before = Counter(lf.type for lf in root.leaves())
        for trial in range(20):
            child, desc = operators.mutate_reassign(
                root, np.random.default_rng(trial), types, reqs=reqs)
            canonical(child)
            after = Counter(lf.type for lf in child.leaves())
            assert after == before, (
                f"construct seed {construct_seed}, trial {trial}: "
                f"room multiset changed ({desc})")
            if not desc.endswith("noop"):
                fired = True
    assert fired, "reassign never fired on any of 6 real seeded designs"


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
    dom.link(root)
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
    dom.link(root)
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


# --------------------------------------------------------------------------- #
# 7fm — targeted shape repair (shape_rotate / deslim)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_shape_failing_flags_known_fail_only():
    from homemaker_layout import fitness, programme

    conf, cost = fitness.load_config(str(HARBOR))
    fit = fitness.Fitness(conf, cost)
    root = dom.load(str(HARBOR / "generated.dom"))
    lvl0 = dom.levels(root)[0]

    # generated.dom/0/rr (type "r") has a real proportion fail (fixture,
    # verified via homemaker-fitness); an outside leaf is never a candidate
    # regardless of its geometry.
    assert operators._shape_failing(lvl0.by_id("rr"), fit)
    assert not operators._shape_failing(lvl0.by_id("lllrl"), fit)  # type O


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_mutate_shape_rotate_noop_without_fit():
    root = dom.load(str(HARBOR / "generated.dom"))
    child, desc = operators.mutate_shape_rotate(root, np.random.default_rng(0), TYPES)
    assert "noop" in desc
    canonical(child)


def _with_forced_slim_leaf(root: dom.Node, code: str = "r") -> tuple[dom.Node, str]:
    """Force a real, deterministic shape fail: divide the largest outside leaf
    95/5 into (``code``, "C"). The 5% side is narrow/high-aspect on any real
    plot, and both sides are fresh leaves (a valid deslim candidate too),
    unlike the fixture's organic fails which may not have a mergeable sibling."""
    from homemaker_layout import geometry

    child = copy.deepcopy(root)
    lvl0 = dom.levels(child)[0]
    host = max((lf for lf in lvl0.leaves() if lf.type == "O"), key=geometry.area)
    host_id = host.id
    host.division = [0.05, 0.05]
    host.rotation = 0
    host.left = dom.Node(type=code)
    host.right = dom.Node(type="C")
    host.type = None
    child = operators._finalise(child)
    leaf_id = (host_id + "l") if host_id else "l"
    return child, leaf_id


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_mutate_shape_rotate_targets_a_failing_cut():
    from homemaker_layout import fitness, programme

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    conf, cost = fitness.load_config(str(HARBOR))
    fit = fitness.Fitness(conf, cost)
    root, leaf_id = _with_forced_slim_leaf(dom.load(str(HARBOR / "generated.dom")))
    assert operators._shape_failing(dom.levels(root)[0].by_id(leaf_id), fit)

    child, desc = operators.mutate_shape_rotate(root, np.random.default_rng(0), types, fit=fit)
    assert "noop" not in desc
    canonical(child)
    # only the rotation of the targeted cut changes; leaf multiset preserved
    assert _leaf_types(child) == _leaf_types(root)


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_mutate_deslim_merges_failing_leaf_and_is_repairable():
    from homemaker_layout import fitness, graph, programme

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    conf, cost = fitness.load_config(str(HARBOR))
    fit = fitness.Fitness(conf, cost)
    root, _leaf_id = _with_forced_slim_leaf(dom.load(str(HARBOR / "generated.dom")))
    n_leaves = sum(len(lvl.leaves()) for lvl in dom.levels(root))

    child, desc = operators.mutate_deslim(root, np.random.default_rng(0), types, fit=fit)
    assert "noop" not in desc
    canonical(child)
    # a merge strictly reduces the leaf count...
    assert sum(len(lvl.leaves()) for lvl in dom.levels(child)) == n_leaves - 1
    # ...and the displaced room is repairable by the existing place_missing op
    _, missing = graph.check_space_counts(child, reqs)
    assert missing
    rng = np.random.default_rng(0)
    for _ in range(len(missing) + 5):
        child, _ = operators.mutate_place_missing(child, rng, types, reqs=reqs)
        _, missing = graph.check_space_counts(child, reqs)
        if not missing:
            break
    assert missing == []


# --------------------------------------------------------------------------- #
# 8sh — insert/relocate-circulation repair (mechanism (a) follow-on to qi6)
# --------------------------------------------------------------------------- #
def _row_of_three(mid_type: str) -> dom.Node:
    """Three same-height leaves in a row: ``C | [mid_type | C]``. The two ``C``
    leaves each share a full-height edge with the middle leaf but not with
    each other, so their circulation components are disconnected — a 2-fail
    ``level 0 not connected`` fixture for a single ``mid_type`` leaf bridge."""
    root = dom.Node(rotation=0, division=[1 / 3, 1 / 3],
                    node=[[0, 0], [12, 0], [12, 4], [0, 4]],
                    height=2.7, wall_outer=0.25, wall_inner=0.08)
    root.left = dom.Node(type="C")
    root.right = dom.Node(rotation=0, division=[0.5, 0.5])
    root.right.left = dom.Node(type=mid_type)
    root.right.right = dom.Node(type="C")
    dom.link(root)
    return root


def _diamond(top_right_type: str) -> dom.Node:
    """2x2 grid: ``C``/``O`` on the left column, ``top_right_type``/``C`` on
    the right, so the two ``C`` corners have two equal-length bridge routes —
    one through the free ``O`` leaf, one through ``top_right_type``."""
    root = dom.Node(rotation=0, division=[0.5, 0.5],
                    node=[[0, 0], [8, 0], [8, 8], [0, 8]],
                    height=2.7, wall_outer=0.25, wall_inner=0.08)
    root.left = dom.Node(rotation=1, division=[0.5, 0.5])
    root.left.left = dom.Node(type="C")
    root.left.right = dom.Node(type="O")
    root.right = dom.Node(rotation=1, division=[0.5, 0.5])
    root.right.left = dom.Node(type=top_right_type)
    root.right.right = dom.Node(type="C")
    dom.link(root)
    return root


def _n_circ_components(root: dom.Node) -> int:
    import networkx as nx

    G = _geo_leaf_graph(root)
    circ = [n for n in G.nodes() if dom.is_circulation(n)]
    return len(list(nx.connected_components(G.subgraph(circ))))


def _geo_leaf_graph(lvl: dom.Node):
    from homemaker_layout import geometry, graph as _graph
    return geometry.leaf_graph(lvl, _graph.DOOR_WIDTH)


def test_mutate_bridge_circulation_noop_when_already_connected():
    root = _row_of_three("C")  # all three already circulation → one component
    assert _n_circ_components(root) == 1
    _, desc = operators.mutate_bridge_circulation(root, np.random.default_rng(0), TYPES)
    assert desc == "bridge_circulation noop"


def test_mutate_bridge_circulation_bridges_fragmented_level():
    root = _row_of_three("O")
    assert _n_circ_components(root) == 2
    child, desc = operators.mutate_bridge_circulation(root, np.random.default_rng(0), TYPES)
    assert "noop" not in desc
    assert desc.startswith("bridge_circulation")
    canonical(child)
    assert _n_circ_components(child) == 1
    # the free 'O' leaf was converted; the two original 'C' leaves untouched
    mid = dom.levels(child)[0].by_id("rl")
    assert mid.type == "C"
    # parent left untouched
    assert dom.levels(root)[0].by_id("rl").type == "O"


def test_mutate_bridge_circulation_falls_back_to_required_room_if_only_route():
    from homemaker_layout import programme

    root = _row_of_three("b1")
    reqs = {"b1": programme.SpaceReq(code="b1")}
    assert _n_circ_components(root) == 2
    child, desc = operators.mutate_bridge_circulation(
        root, np.random.default_rng(0), TYPES + ["b1"], reqs=reqs)
    assert "noop" not in desc
    assert _n_circ_components(child) == 1
    assert dom.levels(child)[0].by_id("rl").type == "C"


def test_mutate_bridge_circulation_prefers_free_leaf_over_required_room():
    from homemaker_layout import programme

    root = _diamond("b1")
    reqs = {"b1": programme.SpaceReq(code="b1")}
    assert _n_circ_components(root) == 2
    child, desc = operators.mutate_bridge_circulation(
        root, np.random.default_rng(0), TYPES + ["b1"], reqs=reqs)
    assert "noop" not in desc
    canonical(child)
    assert _n_circ_components(child) == 1
    # bridges via the free 'O' leaf ('lr'), not the required 'b1' ('rl')
    lvl0 = dom.levels(child)[0]
    assert lvl0.by_id("lr").type == "C"
    assert lvl0.by_id("rl").type == "b1"


@pytest.mark.skipif(not (HARBOR.parent / "maple-court").is_dir(),
                    reason="maple-court not available")
def test_assign_cpsat_beats_greedy_on_a_namespace_clean_programme():
    """§39.5 companion: the same property on a second, namespace-clean
    programme.

    Kept because it was this pair that caught an incomplete §39.4 sweep:
    ``cpsat._matches`` was still matching adjacency by raw prefix after
    ``graph.has_adjacency`` had been tightened, so the exact solver was
    optimising a different relation than the scorer checked. Two programmes
    make that class of drift visible instead of looking like noise.
    """
    import copy

    from homemaker_layout import fitness, programme

    maple = HARBOR.parent / "maple-court"
    reqs = programme.load_programme_dir(str(maple))
    conf, cost = fitness.load_config(str(maple))
    fit = fitness.Fitness(conf, cost)
    types = sorted(reqs) + ["C", "O"]
    seed = dom.load(str(maple / "init.dom"))

    def secondary_fails(solver: str) -> int:
        total = 0
        for trial in range(6):
            root = operators.constructive_topology(
                seed, reqs, np.random.default_rng(trial), types,
                assign_solver=solver)
            _, fails = fit.score_with_fails(copy.deepcopy(root))
            total += sum(1 for f in fails if "not adjacent to" in f)
        return total

    assert secondary_fails("cpsat") < secondary_fails("greedy")


# --------------------------------------------------------------------------- #
# homemaker-py-yql / DESIGN.md §39.9 — settled-geometry circulation repair
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_repair_circulation_default_off_reproduces_prior_seeds():
    """Default off must be byte-identical, like every other experimental flag."""
    from homemaker_layout import programme

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    seed = dom.load(str(HARBOR / "init.dom"))
    kw = dict(min_storeys=programme.storey_minimum(str(HARBOR)),
              adjacency_aware=True, proportion_aware=True, circ_divisor=3)

    def sig(**extra):
        root = operators.constructive_topology(
            seed, reqs, np.random.default_rng(3), types, **kw, **extra)
        return tuple(lf.type for lvl in dom.levels(root) for lf in lvl.leaves())

    assert sig() == sig(repair_circulation=False)


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_repair_circulation_reconnects_every_storey():
    """§39.9: the constructed circulation dominating set is connected, but
    _size_divisions_from_targets then moves every wall and the shared
    boundaries it relied on drop below door_width. Repairing against the
    SETTLED geometry restores connectivity — measured 52% -> 100% of levels on
    harbor-house. (Whether that is a net WIN is a different question: it is
    not, see §39.9 — it displaces required rooms. Hence default off.)
    """
    import networkx as nx

    from homemaker_layout import geometry, graph as graph_mod, programme

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    seed = dom.load(str(HARBOR / "init.dom"))

    def levels_connected(repair: bool) -> tuple[int, int]:
        ok = tot = 0
        for s in range(6):
            root = operators.constructive_topology(
                seed, reqs, np.random.default_rng(s), types,
                min_storeys=programme.storey_minimum(str(HARBOR)),
                adjacency_aware=True, proportion_aware=True, circ_divisor=3,
                repair_circulation=repair)
            for lvl in dom.levels(root):
                geometry.clear_cache()
                G = geometry.leaf_graph(lvl, graph_mod.DOOR_WIDTH)
                circ = [n for n in G.nodes() if dom.is_circulation(n)]
                tot += 1
                if circ and nx.is_connected(G.subgraph(circ)):
                    ok += 1
        return ok, tot

    off_ok, off_tot = levels_connected(False)
    on_ok, on_tot = levels_connected(True)

    # The claim is that repairing against the SETTLED geometry restores
    # connectivity the wall-settling destroyed -- not that it never fails. It is
    # a heuristic over already-placed walls; nothing makes it complete. The
    # original `on_ok == on_tot` hardened a sampled 100% into a guarantee, and
    # it broke the moment the seeds changed (homemaker-py-3qj's `t -> n`
    # adjacency reseeds harbor): measured 25% -> 92%, stable across 6 and 12
    # seeds. The bar below is a real regression detector, comfortably clear of
    # 92% but well above the 25% baseline.
    assert on_ok > off_ok, f"repair did not help: {off_ok}/{off_tot} -> {on_ok}/{on_tot}"
    assert on_ok / on_tot >= 0.85, (
        f"repair reconnected only {on_ok}/{on_tot} storeys "
        f"({100 * on_ok / on_tot:.0f}%), against ~92% expected")


@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
def test_preserve_circulation_default_off_reproduces_prior_seeds():
    """§39.10 measured NULL, so the default must stay byte-identical."""
    from homemaker_layout import geometry, programme

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    seed = dom.load(str(HARBOR / "init.dom"))
    kw = dict(min_storeys=programme.storey_minimum(str(HARBOR)),
              adjacency_aware=True, proportion_aware=True, circ_divisor=3)

    def sig(**extra):
        geometry.clear_cache()
        root = operators.constructive_topology(
            seed, reqs, np.random.default_rng(5), types, **kw, **extra)
        geometry.clear_cache()
        return tuple((lf.type, round(geometry.area(lf), 6))
                     for lvl in dom.levels(root) for lf in lvl.leaves())

    assert sig() == sig(preserve_circulation=False)
    # ...and it does change something when enabled, or the A/B measured nothing
    assert sig() != sig(preserve_circulation=True)


# --------------------------------------------------------------------------- #
# homemaker-py-fdp / DESIGN.md §38.15 — constructive_topology must be
# bit-reproducible on BOTH assignment solvers.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not HARBOR.is_dir(), reason="harbor-house not available")
@pytest.mark.parametrize("solver", ["greedy", "cpsat"])
def test_constructive_topology_is_bit_reproducible(solver):
    """Same seed, same signature -- every time, on either solver.

    `assignable` is a set of dom.Node, which hashes by id(), so deriving the
    room-slot list by iterating it ordered the slots by memory address. That
    varies between calls in ONE process, and cpsat consumes the slot order as
    its model's variable order, so it returned a different equally-optimal
    labelling each run. Greedy never noticed because it re-sorts with `-idx[L]`
    as a unique tiebreak.

    Repetition in-process is what catches this class: allocation patterns
    differ between calls, so id()-derived order changes without any seed
    changing.
    """
    from homemaker_layout import programme

    reqs = programme.load_programme_dir(str(HARBOR))
    types = sorted(reqs) + ["C", "O"]
    seed = dom.load(str(HARBOR / "init.dom"))

    sigs = {
        tuple(lf.type for lf in operators.constructive_topology(
            seed, reqs, np.random.default_rng(0), types,
            min_storeys=programme.storey_minimum(str(HARBOR)),
            adjacency_aware=True, proportion_aware=True, circ_divisor=3,
            assign_solver=solver).leaves())
        for _ in range(4)
    }
    assert len(sigs) == 1, (
        f"assign_solver={solver!r} produced {len(sigs)} distinct leaf-type "
        f"signatures from one seed")

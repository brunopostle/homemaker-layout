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

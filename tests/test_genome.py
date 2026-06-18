"""Genome encode/decode tests (oracle-free; corpus-backed)."""

from pathlib import Path

import pytest

from homemaker_layout import dom, genome, solver

CORPUS = Path(__file__).parent.parent / "examples" / "programme-house"

pytestmark = pytest.mark.skipif(not CORPUS.is_dir(), reason="Corpus not available")


def corpus():
    return sorted(CORPUS.glob("*.dom"))


def owned_projection(root: dom.Node):
    """Everything fitness can see: per-level shape+leaf types, owned cut
    divisions, heights, base metadata. Dead fields excluded by construction."""
    def shape(n: dom.Node):
        if not n.divided:
            return n.type
        return (shape(n.left), shape(n.right))

    lvls = dom.levels(root)
    owned = {}
    for li, lvl in enumerate(lvls):
        for b in solver._branches(lvl):
            if b.below is None or not b.below.divided:
                owned[(li, b.id)] = tuple(b.division)
    return {
        "shapes": [shape(lvl) for lvl in lvls],
        "owned_cuts": owned,
        "heights": [lvl.height for lvl in lvls],
        "base_meta": {k: getattr(lvls[0], k) for k in
                      ("node", "node_file", "perimeter", "elevation",
                       "wall_inner", "wall_outer")},
    }


def test_roundtrip_preserves_owned_projection():
    for f in corpus():
        root = dom.load(str(f))
        root2 = genome.decode(genome.encode(root))
        assert owned_projection(root2) == owned_projection(root), f.name


def test_genome_is_a_fixed_point():
    # encode(decode(g)) == g: nothing fitness-relevant is lost or invented
    for f in corpus():
        g1 = genome.encode(dom.load(str(f)))
        g2 = genome.encode(genome.decode(g1))
        assert g2 == g1, f.name


def test_decoded_tree_dumps_and_reloads():
    for f in corpus():
        root2 = genome.decode(genome.encode(dom.load(str(f))))
        dom.dump(root2, "/tmp/genome_rt.dom")
        root3 = dom.load("/tmp/genome_rt.dom")
        assert owned_projection(root3) == owned_projection(root2), f.name


def test_storey_counts():
    for f in corpus():
        root = dom.load(str(f))
        assert genome.encode(root).n_storeys == len(dom.levels(root)), f.name


# --- signature (§11.5 structural niching) --------------------------------- #

def test_signature_invariant_under_roundtrip():
    # genome-equal trees (decode canonicalises dead fields) share a signature
    for f in corpus():
        root = dom.load(str(f))
        root2 = genome.decode(genome.encode(root))
        assert genome.signature(root) == genome.signature(root2), f.name


def test_signature_ignores_division_ratios():
    # same topology, different geometry -> same signature (the niching premise)
    import copy
    for f in corpus():
        root = dom.load(str(f))
        sig0 = genome.signature(root)
        perturbed = copy.deepcopy(root)
        for lvl in dom.levels(perturbed):
            for b in solver._branches(lvl):
                b.division = [0.37, 0.63]  # arbitrary ratio change, same shape
        assert genome.signature(perturbed) == sig0, f.name


def test_signature_changes_with_topology():
    # a divide mutation changes the structure -> changes the signature
    import numpy as np

    from homemaker_layout import operators
    for f in corpus():
        root = genome.decode(genome.encode(dom.load(str(f))))
        child, _ = operators.mutate_divide(root, np.random.default_rng(0),
                                            ["k1", "l1", "C", "O"])
        assert genome.signature(child) != genome.signature(root), f.name

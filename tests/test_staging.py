"""Staged per-floor search tests (DESIGN.md §11.3, homemaker-py-c4c.3).

Cover the building blocks: programme partition, derived single-storey base
programme, substrate-readiness score, base-lift seeder, and the storey-weighted
mutation pick. Oracle-free; harbor-house is the multi-storey fixture.
"""

import collections
import tempfile
from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, fitness, genome, graph, operators, programme

CORPUS = Path(__file__).parent.parent / "examples" / "harbor-house"

pytestmark = pytest.mark.skipif(not CORPUS.is_dir(), reason="harbor-house not available")


@pytest.fixture
def reqs():
    return programme.load_programme_dir(CORPUS)


def _required_counts(reqs):
    return {c: r.count for c, r in reqs.items() if c[0].lower() not in "cos"}


def test_n_storeys_required(reqs):
    assert programme.n_storeys_required(reqs) == 2


def test_partition_sums_to_required_counts(reqs):
    n = programme.n_storeys_required(reqs)
    buckets = programme.partition_rooms_by_storey(reqs, n, np.random.default_rng(0))
    assert len(buckets) == n
    tot = collections.Counter()
    for b in buckets:
        tot.update(b)
    assert dict(tot) == _required_counts(reqs)
    # level-constrained rooms land on their required storey
    assert buckets[1].get("r") == 10  # r is level: 1
    assert "r" not in buckets[0]


def test_write_stage1_programme_single_storey(reqs):
    n = programme.n_storeys_required(reqs)
    buckets = programme.partition_rooms_by_storey(reqs, n, np.random.default_rng(0))
    with tempfile.TemporaryDirectory() as tmp:
        programme.write_stage1_programme(CORPUS, tmp, buckets[0])
        s1 = programme.load_programme_dir(tmp)
        conf, _ = fitness.load_config(tmp)
    # exactly the base-floor codes, levels dropped, single-storey constraints
    assert set(s1) == set(buckets[0])
    assert all(r.level is None for r in s1.values())
    assert conf["storey_limit"] == 1 and conf["storey_minimum"] == 1
    assert conf["staircase_min"] == 1 and conf["staircase_max"] == 1
    # adjacency pruned to surviving / generic refs only
    for r in s1.values():
        for ref in r.adjacency:
            assert ref in s1 or ref[0].lower() in "cos"


def test_substrate_readiness_range_and_core(reqs):
    n = programme.n_storeys_required(reqs)
    rng = np.random.default_rng(0)
    buckets = programme.partition_rooms_by_storey(reqs, n, rng)
    with tempfile.TemporaryDirectory() as tmp:
        programme.write_stage1_programme(CORPUS, tmp, buckets[0])
        s1 = programme.load_programme_dir(tmp)
        base = operators.constructive_topology(
            dom.load(str(CORPUS / "init.dom")), s1, rng, sorted(s1) + ["C", "O"])
    r = graph.substrate_readiness(base, reqs, n)
    assert 0.0 <= r <= 1.0

    # stripping every C leaf to a non-core type drops the core factor
    for leaf in dom.levels(base)[0].leaves():
        if leaf.type and leaf.type[0].lower() == "c":
            leaf.type = "m"
    dom.link(base)
    r_nocore = graph.substrate_readiness(base, reqs, n)
    assert r_nocore < r  # losing the reserved core lowers readiness


def test_lift_preserves_base_and_builds_upper(reqs):
    n = programme.n_storeys_required(reqs)
    rng = np.random.default_rng(1)
    buckets = programme.partition_rooms_by_storey(reqs, n, rng)
    with tempfile.TemporaryDirectory() as tmp:
        programme.write_stage1_programme(CORPUS, tmp, buckets[0])
        s1 = programme.load_programme_dir(tmp)
        base = operators.constructive_topology(
            dom.load(str(CORPUS / "init.dom")), s1, rng, sorted(s1) + ["C", "O"])

    base_leaf_types = collections.Counter(l.type for l in dom.levels(base)[0].leaves())
    lifted = operators.lift_base_to_storeys(
        base, buckets[1:], rng, sorted(reqs) + ["C", "O"])
    lv = dom.levels(lifted)
    assert len(lv) == n
    # base storey untouched
    assert collections.Counter(l.type for l in lv[0].leaves()) == base_leaf_types
    # upper storey instantiates its required room set + keeps a circulation core
    up = collections.Counter(l.type for l in lv[1].leaves())
    for code, cnt in buckets[1].items():
        assert up.get(code, 0) >= cnt
    assert up.get("C", 0) >= 1
    # result is a canonical genome
    g = genome.encode(lifted)
    assert genome.encode(genome.decode(g)) == g


def test_pick_weighted_by_storey_biases_base():
    items = [(0, "base"), (1, "upper")]
    rng = np.random.default_rng(0)
    picks = [operators._pick_weighted_by_storey(rng, items, base_p=0.0)[0]
             for _ in range(50)]
    assert all(li == 1 for li in picks)  # base_p=0 ⇒ never pick the base storey
    # base_p=1.0 is the plain uniform pick (no bias)
    rng2 = np.random.default_rng(0)
    p1 = operators._pick_weighted_by_storey(rng2, items, base_p=1.0)
    rng3 = np.random.default_rng(0)
    p2 = operators._pick(rng3, items)
    assert p1 == p2

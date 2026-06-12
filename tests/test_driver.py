"""Driver tests with a faked inner loop (no oracle, no perl)."""

from pathlib import Path

import numpy as np
import pytest

from homemaker import dom, driver, innerloop, solver

CORPUS = Path("/home/bruno/src/urb/examples/programme-house")
SEED_FILE = CORPUS / "c964435454c459f86c3ed9a5a7621132.dom"

pytestmark = pytest.mark.skipif(not CORPUS.is_dir(), reason="Urb corpus not available")


def test_free_with_keys_aligns_with_free_branches():
    for f in sorted(CORPUS.glob("*.dom")):
        root = dom.load(str(f))
        assert [b for _, b in innerloop.free_with_keys(root)] == solver.free_branches(root), f.name


@pytest.fixture
def fake_inner(monkeypatch):
    """Deterministic fake fitness: rewards leaf count up to 12; consumes the
    full budget; applies a recognisable ratio so Lamarckian write-back is
    observable."""
    calls = []

    def fake_optimise(root, programme_dir, x0=None, budget=200, urb_root=None, **kw):
        n_leaves = sum(len(lvl.leaves()) for lvl in dom.levels(root))
        fitness = 1.0 / (1.0 + abs(12 - n_leaves)) + 1e-6 * len(calls)
        calls.append({"budget": budget, "x0": x0, "kw": kw})
        for _, b in innerloop.free_with_keys(root):
            b.division = [0.25, 0.25]
        return innerloop.Result(
            x=np.array([0.25]), fitness=fitness, n_fails=0, fail_lines=(),
            x0_fitness=fitness / 2, x0_n_fails=1, n_evals=budget, n_oracle_calls=1,
        )

    monkeypatch.setattr(innerloop, "optimise", fake_optimise)
    return calls


def test_search_respects_budget_and_logs(fake_inner):
    seed_root = dom.load(str(SEED_FILE))
    lines = []
    r = driver.search(seed_root, CORPUS, budget=1000, pop_size=4,
                      child_budget=80, seed_budget=120, seed=1, log=lines.append)
    # budget accounting: seed (120) + children (80 each), stop at >= 1000
    assert r.n_evals >= 1000
    assert r.n_evals == 120 + 80 * ((r.n_evals - 120) // 80)
    assert r.n_evals - 1000 < 80
    assert r.n_topologies == 1 + (r.n_evals - 120) // 80
    assert lines, "improvements must be logged"
    # history monotone in evals and fitness
    evs = [h[0] for h in r.history]
    fits = [h[1] for h in r.history]
    assert evs == sorted(evs)
    assert fits == sorted(fits)
    assert r.best.fitness == max(fits)
    assert len(r.population) <= 4
    # Lamarckian write-back observable in the best individual
    assert all(b.division == [0.25, 0.25] for _, b in innerloop.free_with_keys(r.best.root))


def test_search_children_warm_start_and_local_sigma(fake_inner):
    seed_root = dom.load(str(SEED_FILE))
    driver.search(seed_root, CORPUS, budget=500, pop_size=4,
                  child_budget=60, seed_budget=100, seed=0)
    seed_call, child_calls = fake_inner[0], fake_inner[1:]
    assert seed_call["x0"] is None and seed_call["budget"] == 100
    assert child_calls
    for c in child_calls:
        assert c["budget"] == 60
        assert c["x0"] is not None  # warm-started
        # inherited cuts carry the parent's written-back ratios
        assert np.isin(c["x0"], [0.25, 0.5]).all()
        assert c["kw"].get("sigmas") == (0.05,)


def test_best_root_dumps_valid_dom(fake_inner, tmp_path):
    seed_root = dom.load(str(SEED_FILE))
    r = driver.search(seed_root, CORPUS, budget=400, pop_size=3,
                      child_budget=60, seed_budget=100, seed=2)
    out = tmp_path / "best.dom"
    dom.dump(r.best.root, str(out))
    reloaded = dom.load(str(out))
    assert sum(len(lvl.leaves()) for lvl in dom.levels(reloaded)) == \
           sum(len(lvl.leaves()) for lvl in dom.levels(r.best.root))

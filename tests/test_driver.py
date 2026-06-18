"""Driver tests with a faked inner loop (no oracle, no perl)."""

from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, driver, innerloop, solver

CORPUS = Path(__file__).parent.parent / "examples" / "programme-house"
SEED_FILE = CORPUS / "c964435454c459f86c3ed9a5a7621132.dom"
INIT_FILE = CORPUS / "init.dom"

pytestmark = pytest.mark.skipif(not CORPUS.is_dir(), reason="Corpus not available")


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
        assert "sigmas" not in c["kw"]  # NM inner loop takes no sigmas


def test_best_root_dumps_valid_dom(fake_inner, tmp_path):
    seed_root = dom.load(str(SEED_FILE))
    r = driver.search(seed_root, CORPUS, budget=400, pop_size=3,
                      child_budget=60, seed_budget=100, seed=2)
    out = tmp_path / "best.dom"
    dom.dump(r.best.root, str(out))
    reloaded = dom.load(str(out))
    assert sum(len(lvl.leaves()) for lvl in dom.levels(reloaded)) == \
           sum(len(lvl.leaves()) for lvl in dom.levels(r.best.root))


def test_bootstrap_cold_start(fake_inner):
    """Bootstrap auto-triggers from a bare undivided plot and fills the
    population with pop_size diverse random topologies before the main loop."""
    init_root = dom.load(str(INIT_FILE))
    assert not init_root.divided, "init.dom should be an undivided bare plot"

    pop_size = 4
    child_budget = 60
    budget = 500
    r = driver.search(init_root, CORPUS, budget=budget, pop_size=pop_size,
                      child_budget=child_budget, seed_budget=100, seed=7)

    # All evaluations use child_budget (no seed_budget call)
    assert r.n_evals % child_budget == 0
    assert r.n_evals >= budget
    assert r.n_evals - budget < child_budget
    # Every topology (bootstrap + main loop) is counted
    assert r.n_topologies == r.n_evals // child_budget
    # Population is full
    assert len(r.population) == pop_size
    # Bootstrap individuals all had x0=None (cold starts)
    assert all(c["x0"] is None for c in fake_inner[:pop_size])
    # Bootstrap uses exploratory sigma schedule (inner_kw={}, no sigmas override)
    assert all("sigmas" not in c["kw"] for c in fake_inner[:pop_size])
    # Main loop children are warm-started
    main_calls = fake_inner[pop_size:]
    assert main_calls  # at least one main-loop child
    assert all(c["x0"] is not None for c in main_calls)


def test_bootstrap_disabled_for_divided_seed(fake_inner):
    """A divided seed (warm start) auto-selects the legacy single-seed path."""
    seed_root = dom.load(str(SEED_FILE))
    assert seed_root.divided

    r = driver.search(seed_root, CORPUS, budget=500, pop_size=4,
                      child_budget=60, seed_budget=100, seed=0)

    # First call is the seed evaluated at seed_budget
    assert fake_inner[0]["budget"] == 100
    assert fake_inner[0]["x0"] is None
    # Remaining are warm-started children at child_budget
    assert all(c["budget"] == 60 for c in fake_inner[1:])


def test_random_topology_leaf_count():
    """random_topology produces a topology with at least n_leaves leaves."""
    import numpy as np
    init_root = dom.load(str(INIT_FILE))
    rng = np.random.default_rng(0)
    types = ["b1", "b2", "l1", "t1", "t2", "t3", "C", "O"]
    for n in (3, 5, 7, 10):
        topo = driver.random_topology(init_root, n, rng, types)
        n_leaves = sum(len(lvl.leaves()) for lvl in dom.levels(topo))
        assert n_leaves >= n
        assert n_leaves <= n + 1  # mutate_divide adds exactly one leaf per call


def test_niche_by_signature_keeps_distinct_topologies(fake_inner):
    """§11.5: niching admits at most one individual per topology signature, so
    the population is structurally distinct and diversity is reported."""
    from homemaker_layout import genome
    init_root = dom.load(str(INIT_FILE))
    r = driver.search(init_root, CORPUS, budget=2000, pop_size=6,
                      child_budget=60, seed=3, niche_by_signature=True)
    sigs = [genome.signature(p.root) for p in r.population]
    assert len(sigs) == len(set(sigs)), "population must be one-per-topology"
    assert r.n_distinct_signatures >= len(r.population)
    assert r.diversity_history  # recorded on each improvement


def test_restart_keeps_elite_and_counts(monkeypatch):
    """§11.5: a stagnation restart fires, is counted, and preserves the best."""
    # Saturating fake (no monotone tiebreaker, unlike `fake_inner`): fitness
    # peaks at 12 leaves and plateaus, so the best stalls and restarts trigger.
    def fake_optimise(root, programme_dir, x0=None, budget=200, urb_root=None, **kw):
        n_leaves = sum(len(lvl.leaves()) for lvl in dom.levels(root))
        fitness = 1.0 / (1.0 + abs(12 - n_leaves))
        return innerloop.Result(
            x=np.array([0.25]), fitness=fitness, n_fails=0, fail_lines=(),
            x0_fitness=fitness / 2, x0_n_fails=1, n_evals=budget, n_oracle_calls=1,
        )

    monkeypatch.setattr(innerloop, "optimise", fake_optimise)
    init_root = dom.load(str(INIT_FILE))
    r = driver.search(init_root, CORPUS, budget=4000, pop_size=4,
                      child_budget=60, seed=5, niche_by_signature=True,
                      restart_patience=300, restart_elite=1)
    assert r.n_restarts >= 1
    assert r.best is not None and r.best.fitness > 0


def test_search_parallel_smoke():
    """n_workers>1 runs without error and produces valid results."""
    init_root = dom.load(str(INIT_FILE))
    r = driver.search(init_root, CORPUS, budget=160, pop_size=2,
                      child_budget=80, seed=0, n_workers=2)
    assert r.best is not None
    assert r.best.fitness > 0
    assert r.n_evals >= 160
    assert 1 <= len(r.population) <= 2
    assert r.n_topologies >= 2  # at least the bootstrap individuals

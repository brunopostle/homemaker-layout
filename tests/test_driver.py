"""Driver tests with a faked inner loop (no oracle, no perl)."""

import copy
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


def test_feasibility_filter_off_matches_baseline(fake_inner):
    """§12.3: with the filter and reassociate OFF (defaults), the run is
    identical to one that omits the params — a clean A/B control."""
    init_root = dom.load(str(INIT_FILE))
    base = driver.search(init_root, CORPUS, budget=600, pop_size=4,
                         child_budget=60, seed_budget=100, seed=9)
    off = driver.search(init_root, CORPUS, budget=600, pop_size=4,
                        child_budget=60, seed_budget=100, seed=9,
                        enable_reassociate=False, feasibility_filter=False,
                        feasibility_max_shape_fails=0)
    # Same search trajectory: identical best topology and accounting. (Absolute
    # fitness carries the fake_inner monotone tiebreaker, which shares one call
    # counter across both runs in this fixture, so compare the signature.)
    assert off.best.sig == base.best.sig
    assert off.n_topologies == base.n_topologies
    assert off.n_evals == base.n_evals


def test_enable_shape_repair_threads_fit_into_mutate(fake_inner, monkeypatch):
    """homemaker-py-161: shape_rotate/deslim need a live ``fitness.Fitness`` to
    identify failing leaves; ``search`` must only build and pass one when
    ``enable_shape_repair=True`` — off by default, so ``operators.mutate`` sees
    ``fit=None`` and (per its own gating) never selects those two operators."""
    from homemaker_layout import fitness, operators

    seen_fit = []
    real_mutate = operators.mutate

    def spy_mutate(root, rng, types, **kw):
        seen_fit.append(kw.get("fit"))
        return real_mutate(root, rng, types, **kw)

    monkeypatch.setattr(operators, "mutate", spy_mutate)
    init_root = dom.load(str(INIT_FILE))

    off = driver.search(init_root, CORPUS, budget=400, pop_size=4,
                        child_budget=60, seed_budget=100, seed=5)
    assert seen_fit and all(f is None for f in seen_fit)

    seen_fit.clear()
    on = driver.search(init_root, CORPUS, budget=400, pop_size=4,
                       child_budget=60, seed_budget=100, seed=5,
                       enable_shape_repair=True)
    assert seen_fit and all(isinstance(f, fitness.Fitness) for f in seen_fit)
    # NOTE: no bit-identical-trajectory assertion here. Passing a live `fit`
    # gives shape_rotate/deslim nonzero weight in operators.mutate's op-choice
    # draw, which shifts the RNG mapping for every draw (not just those two
    # ops') — same-seed off/on trajectories only coincided by chance for one
    # fixed MUTATIONS size, and that coincidence breaks on any addition to
    # MUTATIONS (e.g. homemaker-py-8sh's bridge_circulation). The gating
    # itself (seen_fit above) is the actual contract under test.
    assert off.best.sig and on.best.sig


def test_feasibility_filter_prunes_cheaply(fake_inner, monkeypatch):
    """§12.3 (homemaker-py-9gp.1): a pruned topology costs one feasibility eval
    instead of the full child_budget, so the filter explores far more topologies
    per budget; pruned individuals never displace the incumbent."""
    from homemaker_layout import operators

    # Force every filtered child to be pruned (shape-fail floor above any
    # threshold and ≥ the incumbent's fail count).
    monkeypatch.setattr(operators, "predicted_shape_fails",
                        lambda root, reqs, fit: 999)

    init_root = dom.load(str(INIT_FILE))
    budget, child_budget, pop_size = 1200, 60, 4
    on = driver.search(init_root, CORPUS, budget=budget, pop_size=pop_size,
                       child_budget=child_budget, seed_budget=100, seed=4,
                       feasibility_filter=True, feasibility_max_shape_fails=0)

    # Bootstrap (pop_size topologies at child_budget) then 1-eval prunes: the
    # remaining budget buys ~one topology per eval, far more than child_budget.
    bootstrap_evals = pop_size * child_budget
    assert on.n_topologies > pop_size + (budget - bootstrap_evals) // child_budget
    assert on.n_evals >= budget
    # No pruned (untuned, fitness=0) individual is admitted to the population.
    assert all(p.lineage and not p.lineage.startswith("pruned/") for p in on.population)
    assert on.best is not None and not on.best.lineage.startswith("pruned/")


def test_shapecurve_warmstart_off_matches_baseline(fake_inner):
    """homemaker-py-6xh: with the flag off (default), the run is identical to
    one that omits the param — a clean A/B control, mirroring the existing
    feasibility-filter control test."""
    init_root = dom.load(str(INIT_FILE))
    base = driver.search(init_root, CORPUS, budget=600, pop_size=4,
                         child_budget=60, seed_budget=100, seed=9)
    off = driver.search(init_root, CORPUS, budget=600, pop_size=4,
                        child_budget=60, seed_budget=100, seed=9,
                        shapecurve_warmstart=False)
    assert off.best.sig == base.best.sig
    assert off.n_topologies == base.n_topologies
    assert off.n_evals == base.n_evals


def test_shapecurve_warmstart_seeds_ratios_when_eligible(monkeypatch):
    """homemaker-py-6xh: when eligible (single storey, no leaf_sharing/
    superpose/max_share/multi_use) and no caller-supplied x0, ``shapecurve.
    solve`` is called and its written ratios are on the tree by the time
    ``innerloop.optimise`` runs — the mechanism the inner loop's own
    ``x0=None`` (tree's current ratios) picks up as the warm start."""
    from homemaker_layout import shapecurve

    divisions_at_optimise = []

    def fake_optimise(root, programme_dir, x0=None, budget=200, urb_root=None, **kw):
        divisions_at_optimise.append(
            [tuple(b.division) for _, b in innerloop.free_with_keys(root)])
        n_leaves = sum(len(lvl.leaves()) for lvl in dom.levels(root))
        fit = 1.0 / (1.0 + abs(12 - n_leaves))
        for _, b in innerloop.free_with_keys(root):
            b.division = [0.25, 0.25]
        return innerloop.Result(
            x=np.array([0.25]), fitness=fit, n_fails=0, fail_lines=(),
            x0_fitness=fit / 2, x0_n_fails=1, n_evals=budget, n_oracle_calls=1,
        )

    monkeypatch.setattr(innerloop, "optimise", fake_optimise)

    solve_calls = []

    def spy_solve(root, fit, grid_n=150):
        solve_calls.append(len(dom.levels(root)))
        for _, b in innerloop.free_with_keys(root):
            b.division = [0.37, 0.37]
        return True, {}

    monkeypatch.setattr(shapecurve, "solve", spy_solve)

    # harbor-house-l0 (storey_minimum=1) rather than CORPUS (programme-house,
    # storey_minimum=2) — constructive_topology would otherwise grow a
    # multi-storey seed and shapecurve.eligible would rightly never fire.
    harbor_l0 = Path(__file__).parent.parent / "examples" / "harbor-house-l0"
    if not harbor_l0.is_dir():
        pytest.skip("harbor-house-l0 not available")
    init_root = dom.load(str(harbor_l0 / "init.dom"))
    driver.search(init_root, harbor_l0, budget=300, pop_size=2,
                  child_budget=60, seed_budget=60, seed=3,
                  shapecurve_warmstart=True, leaf_sharing=False)

    assert solve_calls, "shapecurve.solve must be called for eligible children"
    assert all(n == 1 for n in solve_calls), "only ever called on single-storey trees"
    # the DP-written ratio (0.37) was on the tree when optimise saw it
    assert any(
        any(abs(t[0] - 0.37) < 1e-9 for t in divs)
        for divs in divisions_at_optimise if divs
    )


def test_shapecurve_warmstart_skips_multistorey(monkeypatch):
    """homemaker-py-6xh: the DP has no notion of ``below``-inherited
    (wall-stacked) fixed splits, so it must never be invoked on a
    multi-storey topology — ``shapecurve.eligible`` guards this."""
    from homemaker_layout import shapecurve

    def fake_optimise(root, programme_dir, x0=None, budget=200, urb_root=None, **kw):
        for _, b in innerloop.free_with_keys(root):
            b.division = [0.25, 0.25]
        return innerloop.Result(
            x=np.array([0.25]), fitness=0.5, n_fails=0, fail_lines=(),
            x0_fitness=0.25, x0_n_fails=1, n_evals=budget, n_oracle_calls=1,
        )

    monkeypatch.setattr(innerloop, "optimise", fake_optimise)
    solve_calls = []
    monkeypatch.setattr(shapecurve, "solve",
                        lambda root, fit, grid_n=150: (solve_calls.append(1), (True, {}))[1])

    multi_root = dom.load(str(SEED_FILE))
    assert len(dom.levels(multi_root)) > 1
    driver.search(multi_root, CORPUS, budget=200, pop_size=2,
                  child_budget=60, seed_budget=60, seed=1,
                  bootstrap=False, shapecurve_warmstart=True, leaf_sharing=False)
    assert not solve_calls


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


def test_search_parallel_is_reproducible():
    """Two same-seed parallel runs must be byte-identical (homemaker-py-xcy).

    ``_run_batch`` used to admit futures in completion order (``as_completed``),
    which varies run-to-run; with the order-sensitive ``admit`` (n_evals accrual,
    first-of-tie wins ``best``) that made parallel searches non-reproducible.
    Admitting in submission order fixed it. Guard the invariant directly: same
    seed + same worker count ⇒ identical best (n_fails, fitness, signature) and
    identical improvement history."""
    def run():
        r = driver.search(dom.load(str(INIT_FILE)), CORPUS, budget=1200,
                          pop_size=8, child_budget=80, seed=0, n_workers=3)
        return (r.best.n_fails, r.best.fitness, r.best.sig, tuple(r.history))

    a = run()
    b = run()
    assert a == b, "parallel search is not reproducible run-to-run"


def _shared_best_result() -> driver.SearchResult:
    """A SearchResult whose best carries a live 3-room shared leaf (share=3),
    plus a distinct C leaf — the harbor-house pathology in miniature."""
    root = dom.Node(node=[[0, 0], [12, 0], [12, 8], [0, 8]],
                    height=2.7, wall_outer=0.25, wall_inner=0.08,
                    rotation=0, division=[0.5, 0.5])
    root.left = dom.Node(type="n", share=3, share_type="n")
    root.right = dom.Node(type="C")
    dom.link(root)
    best = driver.Individual(root=root, fitness=1e-5, n_fails=3, ratios={},
                             lineage="construct/0")
    r = driver.SearchResult(best=best, population=[best], n_evals=1000,
                            n_topologies=5, n_distinct_signatures=4, n_restarts=1)
    r.history = [(80, 1e-6, "construct/0"), (160, 1e-5, "core_divide noop")]
    return r


def test_polish_finish_unfolds_and_stitches_rescore(fake_inner):
    # homemaker-py-3l6, polish_budget<=0: unfold the shared leaf, rescore once
    # under leaf_sharing off, and stitch accounting/history onto the sharing run.
    r0 = _shared_best_result()
    r = driver.polish_finish(r0, CORPUS, polish_budget=0, rescore_budget=150)

    # the shared leaf is materialised into 3 distinct n rooms, stamps cleared
    leaves = r.best.root.leaves()
    assert sum(1 for lf in leaves if lf.type == "n") == 3
    assert all(lf.share == 1 for lf in leaves)
    # accounting is cumulative (1000 sharing evals + one 150-eval rescore)
    assert r.n_evals == 1000 + 150
    assert r.n_topologies == 5 + 1
    assert r.n_distinct_signatures == 4 + 1
    assert r.n_restarts == 1
    # history keeps both phases, tagged so the objective change is visible
    assert [lin for *_, lin in r.history[:2]] == [
        "share:construct/0", "share:core_divide noop"]
    assert r.history[-1][2].startswith("polish:")
    # the rescore ran with leaf_sharing off (no sharing override reaches the
    # inner) but collapse_insearch defaults on (homemaker-py-1ph), so that's
    # the only override present
    assert fake_inner[-1]["kw"].get("conf_overrides") == {"collapse_insearch": True}


def test_polish_finish_runs_polish_search(fake_inner):
    # polish_budget>0: a warm-started no-sharing search runs from the unfolded
    # genome and its evals accrue on top of the sharing run.
    r0 = _shared_best_result()
    r = driver.polish_finish(r0, CORPUS, polish_budget=400, pop_size=3,
                             child_budget=80, seed=1)
    assert r.n_evals > 1000 + 400 - 80  # sharing 1000 + ~400 polish evals
    assert r.best.root.leaves()  # a valid materialised genome survived
    assert sum(1 for lf in r.best.root.leaves() if lf.share > 1) == 0
    assert r.history[0][2].startswith("share:")
    assert any(lin.startswith("polish:") for *_, lin in r.history)


def test_polish_finish_noop_without_best():
    empty = driver.SearchResult(best=None, population=[], n_evals=0, n_topologies=0)
    assert driver.polish_finish(empty, CORPUS, polish_budget=100) is empty


def test_search_seed_pop_evaluates_given_population(fake_inner):
    # homemaker-py-kpu: seed_pop supplies an explicit initial population; each
    # given root is evaluated (not bootstrapped/single-seeded) before the loop.
    pop_roots = [dom.load(str(SEED_FILE)) for _ in range(3)]
    r = driver.search(dom.load(str(INIT_FILE)), CORPUS, budget=0, pop_size=3,
                      child_budget=80, seed_budget=100, seed=0, seed_pop=pop_roots)
    # budget 0 ⇒ only the 3 seed-pop evals run (100 each), no children
    assert r.n_evals == 300
    assert r.n_topologies == 3
    assert all(ind.lineage.startswith("anneal-seed/") for ind in r.population)


def test_search_annealed_stitches_phases_and_finishes_honest(fake_inner):
    # homemaker-py-kpu (Schedule B): the grain ramp runs one phase per ladder
    # step plus a de-share polish, with cumulative accounting, a grain-tagged
    # history, and a materialised (share-free) honest best.
    r = driver.search_annealed(
        dom.load(str(INIT_FILE)), CORPUS, budget=600, polish_budget=200,
        grain_ladder=(3, 2), pop_size=3, child_budget=80, seed_budget=80, seed=0)

    assert r.best is not None
    # honest output: every shared leaf is materialised before the polish phase
    assert all(lf.share == 1 for lf in r.best.root.leaves())
    # accounting is cumulative across both sharing phases + polish
    assert r.n_evals >= 600 + 200 - 80
    # history is grain-tagged and ordered: first phase g3, then g2, then polish
    tags = [lin.split(":", 1)[0] for *_, lin in r.history]
    assert tags[0] == "g3"
    assert "g2" in tags
    assert tags[-1] == "polish"
    # eval offsets are monotone non-decreasing across the stitched phases
    evs = [e for e, *_ in r.history]
    assert evs == sorted(evs)


def test_search_annealed_degenerate_ladder_falls_back(fake_inner):
    # A ladder with no grain >= 2 has nothing to anneal: a plain no-sharing search
    # over the full budget (+ polish), and the best is honest (share-free).
    r = driver.search_annealed(
        dom.load(str(INIT_FILE)), CORPUS, budget=300, polish_budget=100,
        grain_ladder=(1,), pop_size=3, child_budget=80, seed_budget=80, seed=0)
    assert r.best is not None
    assert r.n_evals >= 300
    assert all(lf.share == 1 for lf in r.best.root.leaves())


def test_use_tiers_prefers_fewer_hard_over_fewer_total_fails(monkeypatch):
    """homemaker-py-2g7.3: with use_tiers=True the outer comparator is
    (-n_hard, -n_soft, fitness) instead of (-n_fails, fitness). Construct a
    seed (0 hard, 2 soft) vs. a mutated child (1 hard, 0 soft, FEWER total
    fails and HIGHER raw fitness) — the flat comparator prefers the child
    (1 < 2 total fails); the tiered comparator must keep the seed (0 < 1
    hard fails dominates regardless of soft count or fitness)."""
    from homemaker_layout import innerloop

    seed_root = dom.load(str(SEED_FILE))
    calls = []  # first call is always the seed eval; every later call is a child

    def fake_optimise(root, programme_dir, x0=None, budget=200, urb_root=None, **kw):
        for _, b in innerloop.free_with_keys(root):
            b.division = [0.25, 0.25]
        is_seed = len(calls) == 0
        calls.append(1)
        if is_seed:
            fail_lines = ("0/lr proportion", "0/lr crinkliness")  # 0 hard, 2 soft
            fit = 0.5
        else:
            fail_lines = ("level 0 not connected",)  # 1 hard, 0 soft
            fit = 0.9  # higher raw fitness AND fewer total fails than the seed
        return innerloop.Result(
            x=np.array([0.25]), fitness=fit, n_fails=len(fail_lines),
            fail_lines=fail_lines, x0_fitness=fit, x0_n_fails=len(fail_lines),
            n_evals=budget, n_oracle_calls=1,
        )

    monkeypatch.setattr(innerloop, "optimise", fake_optimise)

    common_kw = dict(programme_dir=CORPUS, pop_size=1, seed_budget=50,
                     child_budget=50, budget=100, bootstrap=False, seed=0)

    flat = driver.search(seed_root, **common_kw)
    assert flat.best.n_fails == 1  # flat comparator: fewer total fails wins

    calls.clear()
    tiered = driver.search(copy.deepcopy(seed_root), use_tiers=True, **common_kw)
    assert tiered.best.n_hard == 0  # tiered comparator: fewer hard fails wins
    assert tiered.best.n_fails == 2

"""Memetic search driver, small-scale (DESIGN.md §5, §7 Phase 2).

Steady-state memetic GA over topology: the outer loop owns *topology only*
(operators.py moves on decoded Node trees); every child's geometry is
delegated to the warm-started inner loop (innerloop.optimise), and the
optimised ratios are written back into the individual (Lamarckian — measured
mandatory, homemaker-py-8cs: cold starts never catch up at equal budget).

Budgets are stated and accounted in **oracle evaluations** (scored .dom
files), never generations (§4.6 arithmetic). This driver is deliberately
small-scale for the Phase-2 proof on the batched Perl oracle; scaling up
waits for the native fitness (Phase 3).

Cold-start bootstrap (homemaker-py-0px): when the seed is an undivided bare
plot, the search auto-generates a diverse initial population by randomly
applying divide mutations until each topology has approximately the programme
room count, then evaluates all pop_size individuals before the memetic loop
begins.  This crosses the zero-feasibility region that single-seed chaining
cannot escape.

Parallelism (homemaker-py-5l6): ``n_workers > 1`` evaluates a batch of
children per iteration using ``concurrent.futures.ProcessPoolExecutor``.
Each worker is independent (NativeEvaluator has no shared mutable state).
The geometry module-level cache is cleared in each worker after fork to
prevent stale id-keyed entries inherited from the parent process.
"""

from __future__ import annotations

import copy
import functools
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import dom, fitness, genome, innerloop, operators, programme

_CHILD_INNER_KW: dict = {}


@functools.lru_cache(maxsize=None)
def _fitness_for(programme_dir: str, leaf_sharing: bool = False) -> "fitness.Fitness":
    """Cached Fitness evaluator per (programme dir, leaf_sharing) (config load is
    the cost).

    Used only to read the graded proximity scalar (§11.4) and the shape-fail
    feasibility proxy off an already-optimised tree in :func:`_evaluate`; the
    inner loop's own NativeEvaluator is untouched. ``leaf_sharing`` (homemaker-py-
    x3b) injects the run-level flag so this off-tree scorer agrees with the
    inner loop instead of reading the on-disk (sharing-free) patterns.config.
    Cached per process — workers fork their own copy.
    """
    overrides = {"leaf_sharing": True} if leaf_sharing else None
    conf, cost = fitness.load_config(programme_dir, overrides=overrides)
    return fitness.Fitness(conf, cost)


@functools.lru_cache(maxsize=None)
def _reqs_for(programme_dir: str) -> dict:
    """Cached programme requirements per dir, for the §12.3 shape-feasibility
    pre-filter (homemaker-py-9gp.1). Cached per process — workers fork a copy."""
    return programme.load_programme_dir(programme_dir)

# storey add/delete are drastic (geometry perturbation 0.25-0.33 and a
# deleted storey stacks missing-space failures) — sample them rarely.
# place_missing is the high-leverage §11.2 repair: it noops cheaply once the
# required set is complete, so over-sampling it costs little and directly
# attacks the dominant missing-space failure mode.
_MUTATION_WEIGHTS = {"level_add": 0.2, "level_delete": 0.2, "place_missing": 2.0}


def _worker_init() -> None:
    """Clear the geometry cache in each forked worker process.

    geometry._cache is keyed by id(node) (Python memory address). After
    fork the inherited cache holds parent-process ids that could collide
    with freshly allocated nodes in the worker, producing wrong hits.
    """
    from . import geometry
    geometry.clear_cache()


@dataclass
class Individual:
    root: dom.Node
    fitness: float
    n_fails: int
    ratios: dict[tuple[int, str], float]
    lineage: str = "seed"
    grade: float = 0.0  # §11.4 graded proximity; secondary comparator key only
    sig: str = ""  # §11.5 structural topology signature; niching key


@dataclass
class SearchResult:
    best: Individual
    population: list[Individual]
    n_evals: int
    n_topologies: int
    history: list[tuple[int, float, str]] = field(default_factory=list)
    # (oracle evals consumed, new best fitness, lineage) per improvement
    interrupted: bool = False
    n_distinct_signatures: int = 0  # §11.5 total distinct topologies ever admitted
    diversity_history: list[tuple[int, int, int]] = field(default_factory=list)
    # (evals, distinct sigs in population, cumulative distinct sigs seen)
    n_restarts: int = 0  # §11.5 diversity restarts triggered


def random_topology(seed_root: dom.Node, n_leaves: int,
                    rng: np.random.Generator, types: list[str]) -> dom.Node:
    """Grow a random topology from ``seed_root`` by repeated divide mutations.

    Applies ``mutate_divide`` until the total leaf count across all storeys
    reaches ``n_leaves``.  The result is a deep copy; ``seed_root`` is
    unchanged.
    """
    root = copy.deepcopy(seed_root)
    while sum(len(lvl.leaves()) for lvl in dom.levels(root)) < n_leaves:
        root, _ = operators.mutate_divide(root, rng, types)
    return root


def _evaluate(root: dom.Node, programme_dir, urb_root, x0, budget, inner_kw,
              lineage: str, want_grade: bool = False,
              feasibility_max_shape_fails: int | None = None,
              best_n_fails: int | None = None,
              leaf_sharing: bool = False) -> tuple[Individual, int]:
    # §12.3 shape-feasibility pre-filter (homemaker-py-9gp.1): if even the best
    # achievable (proportion-aware) geometry of this topology already has at least
    # as many shape fails as the incumbent's TOTAL fails — and exceeds the tunable
    # threshold — it cannot beat the incumbent, so prune it for one feasibility
    # eval instead of spending the full inner-loop budget. The best_n_fails guard
    # makes the proxy safe: a topology whose shape-fail floor is still below the
    # incumbent is never discarded. Pruned individuals are tagged and never admitted.
    overrides = {"leaf_sharing": True} if leaf_sharing else None
    if (feasibility_max_shape_fails is not None and best_n_fails is not None):
        pred = operators.predicted_shape_fails(
            root, _reqs_for(str(programme_dir)),
            _fitness_for(str(programme_dir), leaf_sharing))
        if pred > feasibility_max_shape_fails and pred >= best_n_fails:
            ind = Individual(root=root, fitness=0.0, n_fails=pred, ratios={},
                             lineage=f"pruned/{lineage}", grade=0.0,
                             sig=genome.signature(root))
            return ind, 1
    r = innerloop.optimise(root, programme_dir, x0=x0, budget=budget,
                           urb_root=urb_root, conf_overrides=overrides, **inner_kw)
    # §11.4: read the graded proximity scalar off the optimised tree. The inner
    # loop left ``root`` at the optimum (Lamarckian write-back), so re-scoring a
    # copy reproduces r.fitness/r.n_fails exactly and adds the grade. One extra
    # native eval per child (~1/child_budget overhead); skipped unless requested.
    grade = 0.0
    if want_grade:
        _, _, grade = _fitness_for(str(programme_dir), leaf_sharing).score_with_grade(
            copy.deepcopy(root))
    ind = Individual(root=root, fitness=r.fitness, n_fails=r.n_fails,
                     ratios=innerloop.ratio_map(root), lineage=lineage,
                     grade=grade, sig=genome.signature(root))
    return ind, r.n_evals


def _tournament(pop: list[Individual], rng: np.random.Generator, key_fn, k: int = 2) -> Individual:
    picks = rng.integers(len(pop), size=k)
    return max((pop[int(i)] for i in picks), key=key_fn)


def search(
    seed_root: dom.Node,
    programme_dir: str | Path,
    budget: int = 2000,
    pop_size: int = 8,
    child_budget: int = 80,
    seed_budget: int = 200,
    bootstrap: bool | None = None,
    bootstrap_n_leaves: int | None = None,
    p_crossover: float = 0.2,
    seed: int = 0,
    types: list[str] | None = None,
    inner_kw: dict | None = None,
    urb_root=None,
    log=None,
    n_workers: int = 1,
    use_lex: bool = True,
    rank_bonus_fn=None,
    rank_bonus_weight: float = 1.0,
    seed_factory=None,
    base_p: float = 1.0,
    child_probe=None,
    use_grade: bool = False,
    tournament_k: int = 2,
    niche_by_signature: bool = False,
    restart_patience: int | None = None,
    restart_elite: int = 1,
    seed_adjacency_aware: bool = True,
    seed_proportion_aware: bool = True,
    enable_reassociate: bool = False,
    feasibility_filter: bool = False,
    feasibility_max_shape_fails: int | None = None,
    circ_divisor: int = 3,
    leaf_sharing: bool = True,
    leaf_share_factor: int = 3,
    depth_balanced: bool = True,
    interior_outside: bool = True,
    outside_divisor: int = 3,
) -> SearchResult:
    """Run the memetic loop from ``seed_root`` until ``budget`` oracle
    evaluations are consumed. Returns the best individual found; its ``root``
    carries the optimised geometry and dumps to a valid ``.dom``.

    ``bootstrap=None`` (default) auto-detects: if ``seed_root`` is an
    undivided bare plot, generates a diverse initial population of ``pop_size``
    random topologies (each with approximately ``bootstrap_n_leaves`` leaves)
    before the memetic loop starts.  Pass ``bootstrap=False`` to force the
    legacy single-seed path (appropriate for warm starts from existing designs).

    ``n_workers=1`` (default) runs serially; ``n_workers > 1`` evaluates
    children in parallel using ``ProcessPoolExecutor``.  The bootstrap batch
    is fully parallel; the main loop generates ``n_workers`` children per
    iteration from the current population snapshot and evaluates them in
    parallel.  Results are admitted in completion order (fastest first), so
    later children in each batch see an already-updated population.

    ``niche_by_signature`` (DESIGN.md §11.5, default ``False`` — REJECTED, kept
    for reuse) replaces the legacy fitness-scalar duplicate guard with structural
    niching: the population holds at most one individual per
    :func:`genome.signature` (topology), keeping the better of any collision, so
    distinct topologies whose fitness scalars coincide (common in the high-fail
    ``0.5^n`` regime) are no longer discarded. ``restart_patience`` (default
    ``None`` = off) triggers a soft restart when the best has not improved for
    that many evals: the top ``restart_elite`` incumbents are kept and the rest of
    the population is refilled with fresh constructive/random seeds, the
    soft-restart analog of urb-evolve's upfront random-population diversity.

    Both default off: §11.5 measured that they raise structural diversity as
    designed (final-population distinct topologies ~5/16 → 16/16) but do **not**
    lower the fail count — a tie within seed noise on blank-slate programme-house
    (mean 12.3 → 12.7) and harbor (95 → 94), with restarts strictly worse. The
    high-fail plateau is therefore not a population-diversity deficit; the lever
    is the canonical encoding (``homemaker-py-9gp``) and richer operators.
    """
    from .oracle import DEFAULT_URB_ROOT

    urb_root = urb_root or DEFAULT_URB_ROOT
    rng = np.random.default_rng(seed)
    inner_kw = dict(_CHILD_INNER_KW, **(inner_kw or {}))
    # §12.3 M3 reassociate (homemaker-py-9gp.2) is default-OFF: force its weight to
    # 0 unless enabled, so the leu.2 baseline reproduces byte-for-byte (the operator
    # never fires) and the A/B is a clean single-variable toggle.
    mutation_weights = dict(_MUTATION_WEIGHTS)
    if not enable_reassociate:
        mutation_weights["reassociate"] = 0.0
    # Optional ranking bonus (DESIGN.md §11.3 Stage 1): bias selection toward
    # individuals with high substrate-readiness via a multiplicative factor
    # (1 + W·bonus) on fitness. The reported fitness/history stay the TRUE
    # fitness; only the comparison key changes. rank_bonus_fn=None (default) ⇒
    # the key is unchanged, so normal/Stage-2/programme-house runs are unaffected.
    def _rank_fitness(ind: Individual) -> float:
        if rank_bonus_fn is None:
            return ind.fitness
        return ind.fitness * (1.0 + rank_bonus_weight * rank_bonus_fn(ind.root))

    # §11.4 graded objective (EXPERIMENT, default off — REJECTED, see DESIGN.md
    # §11.4): a continuous proximity bonus (ind.grade) inserted as a secondary key
    # BENEATH fail-count and ABOVE fitness, ordering neighbours by how close their
    # failing constraints are to satisfaction. Hypothesis was that fitness is
    # ~flat (0.5^n) in the high-fail regime; this was FALSIFIED — within a fixed
    # fail-tier 0.5^n is constant so fitness still spans ~6 orders of magnitude,
    # and grade above it merely displaces that working signal (no plateau escape).
    # Kept default-off for reproducibility. Strictly beneath -n_fails ⇒ the
    # missing-space hierarchy (§6) is preserved and the inner-loop cliff (§5.4)
    # is untouched.
    if use_lex and use_grade:
        _key = lambda ind: (-ind.n_fails, ind.grade, _rank_fitness(ind))
    elif use_lex:
        _key = lambda ind: (-ind.n_fails, _rank_fitness(ind))
    else:
        _key = lambda ind: _rank_fitness(ind)
    # Always load reqs so bootstrap_n_leaves can be auto-derived from programme.
    reqs = programme.load_programme_dir(programme_dir)
    # Constructive seed must honour storey_minimum, not just level: keys (§12.2).
    min_storeys = programme.storey_minimum(programme_dir)
    if types is None:
        # Urb's generic types are canonically UPPERCASE (get_space_types:
        # qw/C O S/; the corpus is 100% uppercase). Predicates match
        # case-insensitively but Dom->Ratios keys raw strings — mixing cases
        # fragments the class buckets, so never emit lowercase generics.
        types = sorted(reqs) + ["C", "O"]

    do_bootstrap = (not seed_root.divided) if bootstrap is None else bootstrap

    def _log(msg: str) -> None:
        if log:
            log(msg)

    n_evals = 0
    n_topologies = 0
    last_improve = 0  # n_evals at the last best-fitness improvement (restart clock)
    seen_sigs: set[str] = set()  # §11.5 cumulative distinct topologies ever admitted
    result = SearchResult(best=None, population=[], n_evals=0, n_topologies=0)

    def admit(ind: Individual, pop: list[Individual]) -> None:
        nonlocal n_topologies, last_improve
        n_topologies += 1
        seen_sigs.add(ind.sig)
        # §12.3 pruned by the shape-feasibility filter: counted as an explored
        # topology (so the prune rate is visible) but never bred from or ranked.
        if ind.lineage.startswith("pruned/"):
            return
        if result.best is None or _key(ind) > _key(result.best):
            result.best = ind
            last_improve = n_evals
            result.history.append((n_evals, ind.fitness, ind.lineage))
            result.diversity_history.append(
                (n_evals, len({p.sig for p in pop} | {ind.sig}), len(seen_sigs)))
            _log(f"[{n_evals:6d} evals] best {ind.fitness:.6g} "
                 f"(fails {ind.n_fails}) via {ind.lineage}")
        if niche_by_signature:
            # §11.5 structural niching: at most one individual per topology
            # signature, keeping the better of any collision. This preserves
            # STRUCTURAL diversity directly — distinct topologies whose fitness
            # scalars happen to coincide (common in the high-fail 0.5^n regime)
            # are no longer wrongly discarded, and neutral geometry variants of an
            # incumbent topology can never crowd out a rival topology.
            for i, p in enumerate(pop):
                if p.sig == ind.sig:
                    if _key(ind) > _key(p):
                        pop[i] = ind
                    return
        else:
            # legacy fitness-scalar dedup (population collapse guard —
            # neutral mutations are common, homemaker-py-8cs)
            if any(abs(ind.fitness - p.fitness) <= 1e-9 * max(abs(p.fitness), 1e-300)
                   for p in pop):
                return
        if len(pop) < pop_size:
            pop.append(ind)
            return
        worst = min(range(len(pop)), key=lambda i: _key(pop[i]))
        if _key(ind) > _key(pop[worst]):
            pop[worst] = ind

    pop: list[Individual] = []

    # homemaker-py-psk (island model §14): optional per-child instrumentation
    # hook, default off (no behaviour change). ``child_probe(ind)`` is called
    # once per evaluated child. Used by the island-migration A/B to measure
    # whether area-matched crossover across independently-converged elites EVER
    # yields a child that beats max(parent fails) — distinguishing a mechanistic
    # (alignment) null from a budget null. The crossover parents' fail counts are
    # appended to the child's lineage as ``|pf=a,b`` (only when the probe is set),
    # so the signal survives the ProcessPoolExecutor pickle round-trip that an
    # id(root) key cannot (the worker returns a deserialised, distinct object).

    # Set up optional process pool for parallel child evaluation.
    _pool = None
    if n_workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        _pool = ProcessPoolExecutor(max_workers=n_workers, initializer=_worker_init)

    def _run_batch(
        tasks: list[tuple],  # (root, x0, budget_, inner_kw_, lineage)
        filter_on: bool = False,
    ) -> None:
        """Evaluate a batch of tasks and admit results; parallel when _pool set.

        ``filter_on`` enables the §12.3 shape-feasibility pre-filter for this
        batch — used for mutation children only, never for the seed/bootstrap or
        restart batches (construction invariants must survive)."""
        nonlocal n_evals
        mx = feasibility_max_shape_fails if (filter_on and feasibility_filter) else None
        best_nf = result.best.n_fails if result.best is not None else None
        full = [
            (root, programme_dir, urb_root, x0, budget_, kw_, lin, use_grade,
             mx, best_nf, leaf_sharing)
            for root, x0, budget_, kw_, lin in tasks
        ]
        if _pool is not None:
            # Submit the whole batch in parallel, but admit results in SUBMISSION
            # order, not completion order (homemaker-py-xcy). ``admit`` is
            # order-sensitive — it accrues ``n_evals`` per result and keeps the
            # FIRST individual of any equal-key tie as ``best`` — so consuming
            # futures as they complete made a parallel run non-reproducible
            # (completion order varies run-to-run; measured 167 vs 161 fails for
            # maple-court seed 0). Iterating ``futs`` in order blocks on each in
            # turn while all still run concurrently, reproducing the serial
            # admission sequence exactly (verified byte-identical .dom).
            futs = [_pool.submit(_evaluate, *t) for t in full]
            for f in futs:
                ind, used = f.result()
                n_evals += used
                if child_probe is not None:
                    child_probe(ind)
                admit(ind, pop)
        else:
            for t in full:
                ind, used = _evaluate(*t)
                n_evals += used
                if child_probe is not None:
                    child_probe(ind)
                admit(ind, pop)

    # A fresh seed individual (used for the initial bootstrap and for §11.5
    # restart injections). Mirrors the construction order: custom seed_factory >
    # programme-aware construction > random divide-grown topology.
    prog = {c: r for c, r in reqs.items() if c[0].lower() not in "cos"}
    n_target = bootstrap_n_leaves or max(len(reqs), 3)

    def _make_seed_task(tag: str) -> tuple:
        if seed_factory is not None:
            # Custom seed (DESIGN.md §11.3 Stage 2: lift the evolved base into a
            # full multi-storey design with the upper room sets instantiated by
            # construction).
            return (seed_factory(rng), None, child_budget, {}, f"lift/{tag}")
        if prog:
            topo = operators.constructive_topology(
                seed_root, reqs, rng, types, min_storeys=min_storeys,
                adjacency_aware=seed_adjacency_aware,
                proportion_aware=seed_proportion_aware,
                circ_divisor=circ_divisor,
                leaf_sharing=leaf_sharing, leaf_share_factor=leaf_share_factor,
                depth_balanced=depth_balanced,
                interior_outside=interior_outside, outside_divisor=outside_divisor)
            return (topo, None, child_budget, {}, f"construct/{tag}")
        n = int(rng.integers(max(1, n_target - 1), n_target + 2))
        return (random_topology(seed_root, n, rng, types), None, child_budget,
                {}, f"bootstrap/{tag}")

    interrupted = False
    try:
        if do_bootstrap:
            # Bootstrap: diverse initial population from random topologies.
            # Each individual is a cold start, so use the exploratory sigma
            # schedule (inner_kw={} → cma_search defaults: sigmas=(0.05, 0.15)).
            # Leaf count varied ±1 around the target to increase structural diversity.
            # Programme-aware constructive seeding (§11.2): when the programme
            # has required spaces, instantiate each by construction so the seed
            # population starts with ~zero missing-space failures instead of a
            # random divide+retype walk that leaves required rooms absent.
            _run_batch([_make_seed_task(str(i)) for i in range(pop_size)])
        else:
            seed_ind, used = _evaluate(copy.deepcopy(seed_root), programme_dir, urb_root,
                                       x0=None, budget=seed_budget,
                                       inner_kw={}, lineage="seed",
                                       want_grade=use_grade,
                                       leaf_sharing=leaf_sharing)
            n_evals += used
            admit(seed_ind, pop)

        while n_evals < budget:
            # §11.5 diversity restart: if the best has not improved for
            # restart_patience evals, keep the top restart_elite incumbents and
            # refill the population with fresh constructive/random seeds. This
            # re-injects the upfront structural diversity a single mutation chain
            # loses (the blank-slate gap, §7 Phase 2) — the soft-restart analog of
            # urb-evolve's random initial population. Off by default
            # (restart_patience=None) so existing experiments are unaffected.
            if (restart_patience is not None and pop
                    and n_evals - last_improve >= restart_patience
                    and n_evals + child_budget <= budget):
                keep = sorted(pop, key=_key, reverse=True)[:max(1, restart_elite)]
                pop[:] = keep
                result.n_restarts += 1
                last_improve = n_evals  # reset clock; avoid immediate re-trigger
                n_fresh = min(pop_size - len(pop),
                              max(0, (budget - n_evals) // child_budget))
                _log(f"[{n_evals:6d} evals] restart #{result.n_restarts}: "
                     f"keep {len(keep)}, inject {n_fresh} fresh seeds")
                if n_fresh:
                    _run_batch([_make_seed_task(f"r{result.n_restarts}.{i}")
                                for i in range(n_fresh)])
                continue
            # How many children to generate this iteration: n_workers in parallel,
            # but cap at what the remaining budget can afford (ceiling division).
            batch_n = (
                min(n_workers,
                    max(1, (budget - n_evals + child_budget - 1) // child_budget))
                if _pool is not None else 1
            )
            tasks = []
            for _ in range(batch_n):
                if len(pop) >= 2 and rng.random() < p_crossover:
                    a, b = (_tournament(pop, rng, _key, k=tournament_k),
                            _tournament(pop, rng, _key, k=tournament_k))
                    child_root, _, desc = operators.crossover(a.root, b.root, rng)
                    if child_probe is not None:
                        desc = f"{desc}|pf={a.n_fails},{b.n_fails}"
                    ratios = {**b.ratios, **a.ratios}  # primary parent wins
                else:
                    parent = _tournament(pop, rng, _key, k=tournament_k)
                    child_root, desc = operators.mutate(parent.root, rng, types,
                                                        weights=mutation_weights,
                                                        reqs=reqs, base_p=base_p)
                    # Carry operator-specified ratios for nodes that are genuinely
                    # newly divided (existed as leaves in the parent, are now
                    # divided in the child).  Structural mutations (e.g. swap) can
                    # reveal previously-hidden nodes whose stale pre-writeback
                    # ratios must NOT be propagated — those default to 0.5.
                    parent_lvls = dom.levels(parent.root)
                    new_splits = {
                        (li, path): val
                        for (li, path), val in innerloop.ratio_map(child_root).items()
                        if li >= len(parent_lvls)
                        or not (pn := parent_lvls[li].by_id(path))
                        or not pn.divided
                    }
                    ratios = {**new_splits, **parent.ratios}
                x0 = innerloop.warm_x0(child_root, ratios)
                tasks.append((child_root, x0, child_budget, inner_kw, desc))
            _run_batch(tasks, filter_on=True)
    except KeyboardInterrupt:
        interrupted = True
        _log(f"[{n_evals:6d} evals] interrupted — returning best-so-far")
    finally:
        if _pool is not None:
            _pool.shutdown(wait=True)

    result.population = sorted(pop, key=_key, reverse=True)
    result.n_evals = n_evals
    result.n_topologies = n_topologies
    result.n_distinct_signatures = len(seen_sigs)
    result.interrupted = interrupted
    return result


def search_staged(
    seed_root: dom.Node,
    programme_dir: str | Path,
    budget: int = 20000,
    pop_size: int = 16,
    child_budget: int = 80,
    seed_budget: int = 300,
    stage1_frac: float = 0.4,
    base_p: float = 0.15,
    rank_bonus_weight: float = 1.0,
    p_crossover: float = 0.2,
    seed: int = 0,
    types: list[str] | None = None,
    inner_kw: dict | None = None,
    log=None,
    n_workers: int = 1,
    use_grade: bool = False,
    tournament_k: int = 2,
    niche_by_signature: bool = False,
    restart_patience: int | None = None,
    restart_elite: int = 1,
    seed_adjacency_aware: bool = True,
    seed_proportion_aware: bool = True,
    enable_reassociate: bool = False,
    feasibility_filter: bool = False,
    feasibility_max_shape_fails: int | None = None,
    circ_divisor: int = 3,
    leaf_sharing: bool = True,
    leaf_share_factor: int = 3,
    depth_balanced: bool = True,
    interior_outside: bool = True,
    outside_divisor: int = 3,
) -> SearchResult:
    """Staged per-floor topology search (DESIGN.md §11.3, ``homemaker-py-c4c.3``).

    Searches the genome in causal dependency order:

    - **Stage 1** (``stage1_frac`` of the budget): a single-storey base over the
      level-0 room set (a programme auto-derived to a tempdir), ranked with a
      substrate-readiness bonus so the base is selected as a good *substrate* —
      a reserved, vertically-alignable core and enough divisible footprint for the
      upper floors — not merely a good ground floor (anti-bungalow, §4.2).
    - **Stage 2** (remaining budget): the best base is lifted into a full
      multi-storey design with each upper storey's required room set instantiated
      by construction (``operators.lift_base_to_storeys``); the deltas are searched
      with the base kept mutable at low probability (``base_p``).

    Single-storey programmes (e.g. programme-house) have no upper floors to stage,
    so this falls through to a plain :func:`search` — guaranteeing no regression.
    """
    import shutil
    import tempfile

    from . import graph

    reqs = programme.load_programme_dir(programme_dir)
    # Honour storey_minimum even when no room is pinned to an upper level (§12.2):
    # e.g. programme-house is storey_minimum:2 with all rooms level:0, so its
    # valid solutions are multi-storey and it must stage, not fall through.
    n_storeys = max(programme.n_storeys_required(reqs),
                    programme.storey_minimum(programme_dir))

    def _log(msg: str) -> None:
        if log:
            log(msg)

    if n_storeys < 2:
        _log("[staged] single-storey programme — falling back to plain search")
        return search(seed_root, programme_dir, budget=budget, pop_size=pop_size,
                      child_budget=child_budget, seed_budget=seed_budget,
                      p_crossover=p_crossover, seed=seed, types=types,
                      inner_kw=inner_kw, log=log, n_workers=n_workers,
                      use_grade=use_grade, tournament_k=tournament_k,
                      niche_by_signature=niche_by_signature,
                      restart_patience=restart_patience, restart_elite=restart_elite,
                      seed_adjacency_aware=seed_adjacency_aware,
                      seed_proportion_aware=seed_proportion_aware,
                      enable_reassociate=enable_reassociate,
                      feasibility_filter=feasibility_filter,
                      feasibility_max_shape_fails=feasibility_max_shape_fails,
                      circ_divisor=circ_divisor,
                      leaf_sharing=leaf_sharing,
                      leaf_share_factor=leaf_share_factor,
                      depth_balanced=depth_balanced,
                      interior_outside=interior_outside,
                      outside_divisor=outside_divisor)

    if types is None:
        types = sorted(reqs) + ["C", "O"]
    rng = np.random.default_rng(seed)
    buckets = programme.partition_rooms_by_storey(reqs, n_storeys, rng)

    tmp = Path(tempfile.mkdtemp(prefix="homemaker_stage1_"))
    try:
        programme.write_stage1_programme(programme_dir, tmp, buckets[0])

        # Stage 1 — single-storey base, readiness-biased ranking.
        b1 = max(1, int(budget * stage1_frac))
        _log(f"[staged] stage 1: base floor, budget {b1} "
             f"(rooms {sum(buckets[0].values())}, +readiness bonus)")
        r1 = search(
            seed_root, tmp, budget=b1, pop_size=pop_size,
            child_budget=child_budget, seed_budget=seed_budget,
            p_crossover=p_crossover, seed=seed, types=None,
            inner_kw=inner_kw, log=log, n_workers=n_workers,
            rank_bonus_fn=lambda root: graph.substrate_readiness(root, reqs, n_storeys),
            rank_bonus_weight=rank_bonus_weight,
            tournament_k=tournament_k,
            niche_by_signature=niche_by_signature,
            restart_patience=restart_patience, restart_elite=restart_elite,
            seed_adjacency_aware=seed_adjacency_aware,
            seed_proportion_aware=seed_proportion_aware,
            enable_reassociate=enable_reassociate,
            feasibility_filter=feasibility_filter,
            feasibility_max_shape_fails=feasibility_max_shape_fails,
            circ_divisor=circ_divisor,
            leaf_sharing=leaf_sharing,
            leaf_share_factor=leaf_share_factor,
            depth_balanced=depth_balanced,
            interior_outside=interior_outside,
            outside_divisor=outside_divisor,
        )
        best_base = r1.best.root
        _log(f"[staged] stage 1 done: base {r1.best.fitness:.6g} "
             f"({r1.best.n_fails} fails), readiness "
             f"{graph.substrate_readiness(best_base, reqs, n_storeys):.3f}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # Stage 2 — lift base into full multi-storey, search deltas, base low-prob.
    b2 = max(1, budget - r1.n_evals)
    upper = buckets[1:]

    def _seed_factory(rng2):
        return operators.lift_base_to_storeys(
            best_base, upper, rng2, types, reqs=reqs,
            adjacency_aware=seed_adjacency_aware,
            proportion_aware=seed_proportion_aware,
            circ_divisor=circ_divisor,
            leaf_sharing=leaf_sharing, leaf_share_factor=leaf_share_factor,
            depth_balanced=depth_balanced,
            interior_outside=interior_outside, outside_divisor=outside_divisor)

    _log(f"[staged] stage 2: upper floors as deltas, budget {b2}, base_p {base_p}")
    r2 = search(
        best_base, programme_dir, budget=b2, pop_size=pop_size,
        child_budget=child_budget, seed_budget=seed_budget,
        p_crossover=p_crossover, seed=seed, types=types,
        inner_kw=inner_kw, log=log, n_workers=n_workers,
        bootstrap=True, seed_factory=_seed_factory, base_p=base_p,
        # §11.4: the graded objective targets the dense two-floor quality-fail
        # regime, which is Stage 2. Stage 1 keeps its readiness-biased key so the
        # substrate-selection semantics (§11.3) are unchanged.
        use_grade=use_grade, tournament_k=tournament_k,
        niche_by_signature=niche_by_signature,
        restart_patience=restart_patience, restart_elite=restart_elite,
        enable_reassociate=enable_reassociate,
        feasibility_filter=feasibility_filter,
        feasibility_max_shape_fails=feasibility_max_shape_fails,
        circ_divisor=circ_divisor,
        leaf_sharing=leaf_sharing,
        leaf_share_factor=leaf_share_factor,
        depth_balanced=depth_balanced,
        interior_outside=interior_outside,
        outside_divisor=outside_divisor,
    )

    # Stitch the two stages into one accounting (total evals, tagged history).
    r2.n_evals += r1.n_evals
    r2.n_topologies += r1.n_topologies
    r2.n_distinct_signatures += r1.n_distinct_signatures
    r2.n_restarts += r1.n_restarts
    r2.history = (
        [(e, f, f"S1:{lin}") for e, f, lin in r1.history]
        + [(e + r1.n_evals, f, f"S2:{lin}") for e, f, lin in r2.history]
    )
    r2.diversity_history = (
        [(e, d, c) for e, d, c in r1.diversity_history]
        + [(e + r1.n_evals, d, c) for e, d, c in r2.diversity_history]
    )
    return r2

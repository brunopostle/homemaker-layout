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


def _overrides_for(leaf_sharing: bool, superpose: bool,
                   max_share: int | None = None,
                   conn_grade: bool = False,
                   collapse_insearch: bool = False) -> dict | None:
    """Run-level conf overrides for the native evaluator (None when all off).

    ``max_share`` (homemaker-py-kpu) overrides the evaluator's ``leaf_share_max``
    grain cap for the in-run annealing ramp; ``None`` leaves the config default.
    ``conn_grade`` (homemaker-py-qi6) turns the graded proximity scalar into the
    circulation-connectivity signal (§18). ``collapse_insearch`` (homemaker-py-
    qpk) runs the 94g global cell<->room collapse inside every fitness eval
    instead of once at finish time.
    """
    ov: dict = {}
    if leaf_sharing:
        ov["leaf_sharing"] = True
    if superpose:
        ov["superpose"] = True
    if max_share is not None:
        ov["leaf_share_max"] = int(max_share)
    if conn_grade:
        ov["conn_grade"] = True
    if collapse_insearch:
        ov["collapse_insearch"] = True
    return ov or None


@functools.lru_cache(maxsize=None)
def _fitness_for(programme_dir: str, leaf_sharing: bool = False,
                 superpose: bool = False,
                 max_share: int | None = None,
                 conn_grade: bool = False,
                 collapse_insearch: bool = False) -> "fitness.Fitness":
    """Cached Fitness evaluator per (programme dir, leaf_sharing) (config load is
    the cost).

    Used only to read the graded proximity scalar (§11.4) and the shape-fail
    feasibility proxy off an already-optimised tree in :func:`_evaluate`; the
    inner loop's own NativeEvaluator is untouched. ``leaf_sharing`` (homemaker-py-
    x3b) injects the run-level flag so this off-tree scorer agrees with the
    inner loop instead of reading the on-disk (sharing-free) patterns.config.
    Cached per process — workers fork their own copy.
    """
    overrides = _overrides_for(leaf_sharing, superpose, max_share, conn_grade,
                               collapse_insearch)
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
              leaf_sharing: bool = False,
              superpose: bool = False,
              max_share: int | None = None,
              conn_grade: bool = False,
              collapse_insearch: bool = False) -> tuple[Individual, int]:
    # §12.3 shape-feasibility pre-filter (homemaker-py-9gp.1): if even the best
    # achievable (proportion-aware) geometry of this topology already has at least
    # as many shape fails as the incumbent's TOTAL fails — and exceeds the tunable
    # threshold — it cannot beat the incumbent, so prune it for one feasibility
    # eval instead of spending the full inner-loop budget. The best_n_fails guard
    # makes the proxy safe: a topology whose shape-fail floor is still below the
    # incumbent is never discarded. Pruned individuals are tagged and never admitted.
    overrides = _overrides_for(leaf_sharing, superpose, max_share, conn_grade,
                               collapse_insearch)
    if (feasibility_max_shape_fails is not None and best_n_fails is not None):
        pred = operators.predicted_shape_fails(
            root, _reqs_for(str(programme_dir)),
            _fitness_for(str(programme_dir), leaf_sharing, superpose, max_share,
                         conn_grade, collapse_insearch))
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
        _, _, grade = _fitness_for(
            str(programme_dir), leaf_sharing, superpose, max_share,
            conn_grade, collapse_insearch).score_with_grade(
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
    conn_grade: bool = False,
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
    superpose: bool = False,
    depth_balanced: bool = True,
    interior_outside: bool = True,
    outside_divisor: int = 3,
    max_share: int | None = None,
    seed_pop: list[dom.Node] | None = None,
    collapse_insearch: bool = False,
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

    ``max_share`` (homemaker-py-kpu) overrides the evaluator's ``leaf_share_max``
    grain cap for this phase; ``None`` uses the config default. ``seed_pop`` (also
    kpu) supplies an explicit initial population of decoded roots — evaluated
    under this phase's evaluator instead of bootstrapping or single-seeding — so a
    grain-anneal ramp can hand a whole population from one phase to the next.

    ``collapse_insearch`` (homemaker-py-qpk, EXPERIMENTAL, default off) runs the
    94g global cell<->room collapse inside every fitness eval instead of once at
    finish time, so search optimises the collapsed objective directly. Carries
    the 9o5/xi7 landscape-flattening risk at global scope — do not flip default
    on without a positive A/B (DESIGN.md §17 follow-on).
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
    # homemaker-py-qi6 §18: the connectivity signal rides the same grade channel,
    # so enabling it enables the grade secondary key.
    use_grade = use_grade or conn_grade
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
             mx, best_nf, leaf_sharing, superpose, max_share, conn_grade,
             collapse_insearch)
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
        if seed_pop is not None:
            # homemaker-py-kpu (Schedule B): carry a whole population across a
            # grain-anneal phase change. Each root is re-optimised and re-scored
            # under THIS phase's evaluator (leaf_sharing/max_share) as the initial
            # population, so gross topology/adjacency continuity is preserved while
            # the effective problem is refined — not restarted from a single best.
            _run_batch([(copy.deepcopy(r), None, seed_budget, {},
                         f"anneal-seed/{i}") for i, r in enumerate(seed_pop)])
        elif do_bootstrap:
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
                                       leaf_sharing=leaf_sharing,
                                       superpose=superpose,
                                       max_share=max_share,
                                       conn_grade=conn_grade,
                                       collapse_insearch=collapse_insearch)
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


def polish_finish(
    result: SearchResult,
    programme_dir: str | Path,
    *,
    polish_budget: int,
    pop_size: int = 8,
    child_budget: int = 80,
    p_crossover: float = 0.2,
    seed: int = 0,
    n_workers: int = 1,
    superpose: bool = False,
    collapse_insearch: bool = False,
    rescore_budget: int = 200,
    log=None,
) -> SearchResult:
    """homemaker-py-3l6: convert a leaf-sharing run's dishonest best into a
    canonically-scored, materialised output.

    A sharing run's internal objective credits a shared leaf (``share=k``) as k
    programme rooms with its size target re-centred on ``k*target``, so
    ``result.best`` looks good internally but is k−1 rooms short per shared leaf
    under the canonical (sharing-off) scorer — the divergence this bug is about.
    This:

    1. **Unfolds** every live shared leaf into k distinct sibling rooms
       (:func:`operators.unfold_shared_leaves`), paying down the materialisation
       deficit that otherwise leaves the de-shared genome deep in the missing-room
       fail hole (yaa: naive warm-start without unfold stalls ~60× worse).
    2. **Polishes** the unfolded genome with a warm-started ``leaf_sharing=False``
       search (``polish_budget`` evals) so the freshly materialised children get
       their proportion/width/size cleaned up. yaa proved this unfold-then-polish
       path catches the direct no-sharing route (harbor-house 4.19e-06).

    With ``polish_budget <= 0`` the polish is skipped: the unfolded genome is just
    re-optimised once and canonically scored (honest output, no extra search —
    used on interrupt). Either way the returned result's ``best.fitness`` is the
    canonical score (leaf_sharing off ⇒ internal == canonical), and eval /
    topology / history accounting is stitched onto the sharing run.
    """
    def _log(msg: str) -> None:
        if log:
            log(msg)

    if result.best is None:
        return result

    unfolded = copy.deepcopy(result.best.root)
    n_created = operators.unfold_shared_leaves(unfolded)
    _log(f"[finish] unfold: materialised {n_created} shared-leaf "
         f"{'copy' if n_created == 1 else 'copies'}")

    if polish_budget > 0:
        r2 = search(
            unfolded, programme_dir, budget=polish_budget, pop_size=pop_size,
            child_budget=child_budget, p_crossover=p_crossover, seed=seed,
            n_workers=n_workers, bootstrap=False, leaf_sharing=False,
            superpose=superpose, collapse_insearch=collapse_insearch, log=log,
        )
    else:
        # No polish: re-optimise the unfolded genome's ratios once and score it
        # canonically so the written .dom and reported fitness are honest.
        ind, used = _evaluate(
            unfolded, programme_dir, None, x0=None, budget=rescore_budget,
            inner_kw={}, lineage="unfold", leaf_sharing=False, superpose=superpose,
            collapse_insearch=collapse_insearch)
        r2 = SearchResult(best=ind, population=[ind], n_evals=used, n_topologies=1)
        r2.n_distinct_signatures = 1
        r2.history = [(0, ind.fitness, ind.lineage)]

    # Stitch the polish/rescore onto the sharing run so totals are cumulative and
    # the history shows the phase change (sharing fitness is not comparable to the
    # canonical polish fitness, so the two phases are tagged, not merged linearly).
    r2.history = (
        [(e, f, f"share:{lin}") for e, f, lin in result.history]
        + [(e + result.n_evals, f, f"polish:{lin}") for e, f, lin in r2.history]
    )
    r2.n_evals += result.n_evals
    r2.n_topologies += result.n_topologies
    r2.n_distinct_signatures += result.n_distinct_signatures
    r2.n_restarts += result.n_restarts
    r2.interrupted = r2.interrupted or result.interrupted
    return r2


def collapse_best(
    result: SearchResult,
    programme_dir: str | Path,
    *,
    leaf_sharing: bool = False,
    superpose: bool = False,
    log=None,
    **collapse_kw,
) -> SearchResult:
    """homemaker-py-94g: finish-time global cell→room collapse on the best layout.

    Relabels the best tree's room cells to the programme rooms they fit best via
    one optimal assignment (hard level constraint, adjacency relaxation, and
    public-access pinning — see :meth:`fitness.Fitness.collapse_global`), keeping
    the result only if the fail count does not increase (:meth:`collapse_finish`).
    A strictly monotone finish-time polish that searches only labels, not
    geometry, so it cannot touch shape-intrinsic fails (long-thin cells, etc.).

    Updates ``result.best`` in place with the canonically re-scored relabelling
    when it helps; otherwise leaves the result untouched."""
    if result.best is None:
        return result

    fit = _fitness_for(str(programme_dir), leaf_sharing, superpose)
    tree, base_fails, coll_fails, applied = fit.collapse_finish(
        result.best.root, **collapse_kw
    )
    if log:
        verb = "applied" if applied else "reverted — no improvement"
        log(f"[finish] collapse: {base_fails} → {coll_fails} fails ({verb})")
    if applied:
        score, fails, grade = fit.score_with_grade(copy.deepcopy(tree))
        result.best = Individual(
            root=tree,
            fitness=score,
            n_fails=len(fails),
            ratios=result.best.ratios,
            lineage=result.best.lineage + "+collapse",
            grade=grade,
            sig=result.best.sig,
        )
    return result


def search_annealed(
    seed_root: dom.Node,
    programme_dir: str | Path,
    *,
    budget: int,
    polish_budget: int,
    grain_ladder: tuple[int, ...] = (4, 3, 2),
    pop_size: int = 8,
    child_budget: int = 80,
    seed_budget: int = 200,
    p_crossover: float = 0.2,
    seed: int = 0,
    types: list[str] | None = None,
    inner_kw: dict | None = None,
    n_workers: int = 1,
    superpose: bool = False,
    log=None,
    **search_kw,
) -> SearchResult:
    """homemaker-py-kpu (DESIGN.md §16): in-run leaf-share grain annealing.

    Schedule B from ``homemaker-py-yaa``. Instead of a single hard sharing→off
    transition (§15's unfold+polish finish), ramp the leaf-share grain **down**
    across phases within one continuous run — e.g. ``grain_ladder=(4, 3, 2)`` then
    off — carrying the whole population across each step. This is graduated
    non-convexity: the coarse early grain fixes gross topology/adjacency on a
    small effective problem; each step refines it, so no single fitness cliff has
    to be crossed at once.

    Each grain step lowers the evaluator's ``leaf_share_max`` cap and, *before*
    resuming, unfolds every population leaf whose ``share`` exceeds the new cap
    (:func:`operators.unfold_shared_leaves` with ``above=cap``) so the carried
    population stays materialised — the leaves the lower cap would under-credit
    become real rooms instead of fresh missing fails. The final phase de-shares
    entirely (``leaf_sharing=False``, unfold ``above=1``) and polishes under the
    canonical objective, so the returned ``best.fitness`` is the honest canonical
    score exactly as §15's finish guarantees.

    ``grain_ladder`` is deduped and sorted descending; entries < 2 are dropped
    (no-op grain). ``budget`` is split evenly across the sharing phases (remainder
    to the first); ``polish_budget`` funds the final de-share phase (``<= 0`` or an
    interrupt ⇒ unfold + single rescore only, no search — honest but unpolished).
    Extra keyword args forward to :func:`search`.
    """
    def _log(msg: str) -> None:
        if log:
            log(msg)

    ladder = sorted({int(g) for g in grain_ladder if int(g) >= 2}, reverse=True)
    if not ladder:
        # Degenerate ladder (all grains < 2) ⇒ nothing to anneal: a plain
        # no-sharing search over the full budget, honest by construction.
        return search(
            seed_root, programme_dir, budget=budget + max(0, polish_budget),
            pop_size=pop_size, child_budget=child_budget, seed_budget=seed_budget,
            p_crossover=p_crossover, seed=seed, types=types, inner_kw=inner_kw,
            n_workers=n_workers, leaf_sharing=False, superpose=superpose, log=log,
            **search_kw)

    n_phases = len(ladder)
    base = budget // n_phases
    phase_budgets = [base] * n_phases
    phase_budgets[0] += budget - base * n_phases  # remainder to phase 0

    def _stitch(acc: "SearchResult | None", r: SearchResult, tag: str) -> SearchResult:
        """Concatenate phase ``r`` onto ``acc`` with cumulative accounting and a
        tagged history (objectives differ across grains, so histories are tagged
        and concatenated, never merged linearly — as §15's finish does)."""
        r.history = [(e, f, f"{tag}:{lin}") for e, f, lin in r.history]
        r.diversity_history = list(r.diversity_history)
        if acc is None:
            return r
        prev = acc.n_evals
        r.n_evals += prev
        r.n_topologies += acc.n_topologies
        r.n_distinct_signatures += acc.n_distinct_signatures
        r.n_restarts += acc.n_restarts
        r.interrupted = r.interrupted or acc.interrupted
        r.history = acc.history + [(e + prev, f, lin) for e, f, lin in r.history]
        r.diversity_history = (
            acc.diversity_history
            + [(e + prev, d, c) for e, d, c in r.diversity_history])
        return r

    combined: SearchResult | None = None
    prev_pop: list[Individual] = []

    for i, cap in enumerate(ladder):
        if i == 0:
            _log(f"[anneal] phase 1/{n_phases}: grain {cap}, budget "
                 f"{phase_budgets[0]} (construct population)")
            r = search(
                seed_root, programme_dir, budget=phase_budgets[0], pop_size=pop_size,
                child_budget=child_budget, seed_budget=seed_budget,
                p_crossover=p_crossover, seed=seed, types=types, inner_kw=inner_kw,
                n_workers=n_workers, leaf_sharing=True, leaf_share_factor=cap,
                max_share=cap, superpose=superpose, log=log, **search_kw)
        else:
            roots = [copy.deepcopy(ind.root) for ind in prev_pop]
            created = sum(operators.unfold_shared_leaves(rt, above=cap) for rt in roots)
            _log(f"[anneal] phase {i + 1}/{n_phases}: grain {cap}, budget "
                 f"{phase_budgets[i]} — unfolded {created} leaf-"
                 f"{'copy' if created == 1 else 'copies'} (share>{cap})")
            r = search(
                seed_root, programme_dir, budget=phase_budgets[i], pop_size=pop_size,
                child_budget=child_budget, seed_budget=seed_budget,
                p_crossover=p_crossover, seed=seed, types=types, inner_kw=inner_kw,
                n_workers=n_workers, leaf_sharing=True, leaf_share_factor=cap,
                max_share=cap, superpose=superpose, log=log, seed_pop=roots,
                **search_kw)
        combined = _stitch(combined, r, tag=f"g{cap}")
        prev_pop = r.population
        if r.interrupted:
            break

    if combined is None or combined.best is None:
        return combined or SearchResult(
            best=None, population=[], n_evals=0, n_topologies=0)

    # Final honesty phase: de-share entirely. Unfold ALL remaining shared leaves
    # and polish (or just rescore) under the canonical sharing-off objective, so
    # the returned best is the honest canonical score (§15's guarantee).
    if polish_budget > 0 and not combined.interrupted:
        roots = [copy.deepcopy(ind.root) for ind in prev_pop]
        created = sum(operators.unfold_shared_leaves(rt, above=1) for rt in roots)
        _log(f"[anneal] finish: de-share (grain off), polish {polish_budget} "
             f"evals — unfolded {created} leaf-"
             f"{'copy' if created == 1 else 'copies'}")
        r = search(
            seed_root, programme_dir, budget=polish_budget, pop_size=pop_size,
            child_budget=child_budget, seed_budget=seed_budget,
            p_crossover=p_crossover, seed=seed, types=types, inner_kw=inner_kw,
            n_workers=n_workers, leaf_sharing=False, superpose=superpose, log=log,
            seed_pop=roots, **search_kw)
    else:
        best_root = copy.deepcopy(combined.best.root)
        created = operators.unfold_shared_leaves(best_root, above=1)
        _log(f"[anneal] finish: de-share (grain off), rescore only — unfolded "
             f"{created} leaf-{'copy' if created == 1 else 'copies'}")
        ind, used = _evaluate(
            best_root, programme_dir, None, x0=None, budget=seed_budget,
            inner_kw={}, lineage="unfold", leaf_sharing=False, superpose=superpose)
        r = SearchResult(best=ind, population=[ind], n_evals=used, n_topologies=1)
        r.n_distinct_signatures = 1
        r.history = [(0, ind.fitness, ind.lineage)]
    return _stitch(combined, r, tag="polish")


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
    superpose: bool = False,
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
                      superpose=superpose,
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
            superpose=superpose,
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
        superpose=superpose,
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

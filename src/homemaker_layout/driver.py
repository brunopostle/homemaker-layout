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
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import dom, innerloop, operators, programme

_CHILD_INNER_KW: dict = {}

# storey add/delete are drastic (geometry perturbation 0.25-0.33 and a
# deleted storey stacks missing-space failures) — sample them rarely
_MUTATION_WEIGHTS = {"level_add": 0.2, "level_delete": 0.2}


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


@dataclass
class SearchResult:
    best: Individual
    population: list[Individual]
    n_evals: int
    n_topologies: int
    history: list[tuple[int, float, str]] = field(default_factory=list)
    # (oracle evals consumed, new best fitness, lineage) per improvement
    interrupted: bool = False


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
              lineage: str) -> tuple[Individual, int]:
    r = innerloop.optimise(root, programme_dir, x0=x0, budget=budget,
                           urb_root=urb_root, **inner_kw)
    ind = Individual(root=root, fitness=r.fitness, n_fails=r.n_fails,
                     ratios=innerloop.ratio_map(root), lineage=lineage)
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
    """
    from .oracle import DEFAULT_URB_ROOT

    urb_root = urb_root or DEFAULT_URB_ROOT
    rng = np.random.default_rng(seed)
    inner_kw = dict(_CHILD_INNER_KW, **(inner_kw or {}))
    _key = (lambda ind: (-ind.n_fails, ind.fitness)) if use_lex else (lambda ind: ind.fitness)
    # Always load reqs so bootstrap_n_leaves can be auto-derived from programme.
    reqs = programme.load_programme_dir(programme_dir)
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
    result = SearchResult(best=None, population=[], n_evals=0, n_topologies=0)

    def admit(ind: Individual, pop: list[Individual]) -> None:
        nonlocal n_topologies
        n_topologies += 1
        if result.best is None or _key(ind) > _key(result.best):
            result.best = ind
            result.history.append((n_evals, ind.fitness, ind.lineage))
            _log(f"[{n_evals:6d} evals] best {ind.fitness:.6g} "
                 f"(fails {ind.n_fails}) via {ind.lineage}")
        # reject near-duplicates of existing members (population collapse
        # guard — neutral mutations are common, homemaker-py-8cs)
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

    # Set up optional process pool for parallel child evaluation.
    _pool = None
    if n_workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        _pool = ProcessPoolExecutor(max_workers=n_workers, initializer=_worker_init)

    def _run_batch(
        tasks: list[tuple],  # (root, x0, budget_, inner_kw_, lineage)
    ) -> None:
        """Evaluate a batch of tasks and admit results; parallel when _pool set."""
        nonlocal n_evals
        full = [
            (root, programme_dir, urb_root, x0, budget_, kw_, lin)
            for root, x0, budget_, kw_, lin in tasks
        ]
        if _pool is not None:
            from concurrent.futures import as_completed
            futs = [_pool.submit(_evaluate, *t) for t in full]
            for f in as_completed(futs):
                ind, used = f.result()
                n_evals += used
                admit(ind, pop)
        else:
            for t in full:
                ind, used = _evaluate(*t)
                n_evals += used
                admit(ind, pop)

    interrupted = False
    try:
        if do_bootstrap:
            # Bootstrap: diverse initial population from random topologies.
            # Each individual is a cold start, so use the exploratory sigma
            # schedule (inner_kw={} → cma_search defaults: sigmas=(0.05, 0.15)).
            # Leaf count varied ±1 around the target to increase structural diversity.
            n_target = bootstrap_n_leaves or max(len(reqs), 3)
            tasks = []
            for i in range(pop_size):
                n = int(rng.integers(max(1, n_target - 1), n_target + 2))
                topo = random_topology(seed_root, n, rng, types)
                tasks.append((topo, None, child_budget, {}, f"bootstrap/{i}"))
            _run_batch(tasks)
        else:
            seed_ind, used = _evaluate(copy.deepcopy(seed_root), programme_dir, urb_root,
                                       x0=None, budget=seed_budget,
                                       inner_kw={}, lineage="seed")
            n_evals += used
            admit(seed_ind, pop)

        while n_evals < budget:
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
                    a, b = _tournament(pop, rng, _key), _tournament(pop, rng, _key)
                    child_root, _, desc = operators.crossover(a.root, b.root, rng)
                    ratios = {**b.ratios, **a.ratios}  # primary parent wins
                else:
                    parent = _tournament(pop, rng, _key)
                    child_root, desc = operators.mutate(parent.root, rng, types,
                                                        weights=_MUTATION_WEIGHTS,
                                                        reqs=reqs)
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
            _run_batch(tasks)
    except KeyboardInterrupt:
        interrupted = True
        _log(f"[{n_evals:6d} evals] interrupted — returning best-so-far")
    finally:
        if _pool is not None:
            _pool.shutdown(wait=True)

    result.population = sorted(pop, key=_key, reverse=True)
    result.n_evals = n_evals
    result.n_topologies = n_topologies
    result.interrupted = interrupted
    return result

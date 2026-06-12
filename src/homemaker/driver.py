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
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import dom, innerloop, operators, programme

# children refine a near-optimal inherited geometry: one local CMA phase
# (the exploratory ladder phase exists for brutal cold projections, which
# warm-started children never face)
_CHILD_INNER_KW = {"sigmas": (0.05,)}

# storey add/delete are drastic (geometry perturbation 0.25-0.33 and a
# deleted storey stacks missing-space failures) — sample them rarely
_MUTATION_WEIGHTS = {"level_add": 0.2, "level_delete": 0.2}


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


def _evaluate(root: dom.Node, programme_dir, urb_root, x0, budget, inner_kw,
              lineage: str) -> tuple[Individual, int]:
    r = innerloop.optimise(root, programme_dir, x0=x0, budget=budget,
                           urb_root=urb_root, **inner_kw)
    ind = Individual(root=root, fitness=r.fitness, n_fails=r.n_fails,
                     ratios=innerloop.ratio_map(root), lineage=lineage)
    return ind, r.n_evals


def _tournament(pop: list[Individual], rng: np.random.Generator, k: int = 2) -> Individual:
    picks = rng.integers(len(pop), size=k)
    return max((pop[int(i)] for i in picks), key=lambda ind: ind.fitness)


def search(
    seed_root: dom.Node,
    programme_dir: str | Path,
    budget: int = 2000,
    pop_size: int = 8,
    child_budget: int = 80,
    seed_budget: int = 200,
    p_crossover: float = 0.2,
    seed: int = 0,
    types: list[str] | None = None,
    inner_kw: dict | None = None,
    urb_root=None,
    log=None,
) -> SearchResult:
    """Run the memetic loop from ``seed_root`` until ``budget`` oracle
    evaluations are consumed. Returns the best individual found; its ``root``
    carries the optimised geometry and dumps to a valid ``.dom``."""
    from .oracle import DEFAULT_URB_ROOT

    urb_root = urb_root or DEFAULT_URB_ROOT
    rng = np.random.default_rng(seed)
    inner_kw = dict(_CHILD_INNER_KW, **(inner_kw or {}))
    if types is None:
        reqs = programme.load_programme(str(Path(programme_dir) / "patterns.config"))
        types = sorted(reqs) + ["c", "o"]

    def _log(msg: str) -> None:
        if log:
            log(msg)

    n_evals = 0
    n_topologies = 0
    result = SearchResult(best=None, population=[], n_evals=0, n_topologies=0)

    def admit(ind: Individual, pop: list[Individual]) -> None:
        nonlocal n_topologies
        n_topologies += 1
        if result.best is None or ind.fitness > result.best.fitness:
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
        worst = min(range(len(pop)), key=lambda i: pop[i].fitness)
        if ind.fitness > pop[worst].fitness:
            pop[worst] = ind

    pop: list[Individual] = []
    seed_ind, used = _evaluate(copy.deepcopy(seed_root), programme_dir, urb_root,
                               x0=None, budget=seed_budget,
                               inner_kw={}, lineage="seed")
    n_evals += used
    admit(seed_ind, pop)

    while n_evals < budget:
        if len(pop) >= 2 and rng.random() < p_crossover:
            a, b = _tournament(pop, rng), _tournament(pop, rng)
            child_root, _, desc = operators.crossover(a.root, b.root, rng)
            ratios = {**b.ratios, **a.ratios}  # primary parent wins
        else:
            parent = _tournament(pop, rng)
            child_root, desc = operators.mutate(parent.root, rng, types,
                                                weights=_MUTATION_WEIGHTS)
            ratios = parent.ratios
        x0 = innerloop.warm_x0(child_root, ratios)
        child, used = _evaluate(child_root, programme_dir, urb_root,
                                x0=x0, budget=child_budget,
                                inner_kw=inner_kw, lineage=desc)
        n_evals += used
        admit(child, pop)

    result.population = sorted(pop, key=lambda i: -i.fitness)
    result.n_evals = n_evals
    result.n_topologies = n_topologies
    return result

"""Geometry inner loop: full-objective equal-offset ratio optimisation.

The memetic architecture (DESIGN.md §5) delegates geometry to this module: for
a *frozen* slicing topology, optimise the equal-offset division ratios of the
free branches (one DOF per cut, ``solver.free_branches`` — lowest-storey cut
ownership) against the FULL fitness. Never a proxy objective — §4.2 falsified
that; the full objective's ``0.5^n`` failure cliff is what protects the inner
loop from trading into new failures (§4.5).

Fitness comes from the Perl oracle for now. The optimiser is a batched compass
(pattern) search: each iteration proposes ``2 × DOF`` candidate points and
scores them in ONE ``oracle.score_batch`` call, so the Perl startup amortises
across the population (§4.6). Warm-starting from a parent's optimised ratios is
just ``x0=`` (§5 decision 6, Lamarckian inheritance).

Budgets are counted in oracle evaluations (scored ``.dom`` files), the only
currency that matters while the oracle is the bottleneck.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import dom, oracle, solver

_EPS = 0.02  # keep cuts off the edges; matches solver/_experiments convention


def free_with_keys(root: dom.Node) -> list[tuple[tuple[int, str], dom.Node]]:
    """``solver.free_branches`` order, with (level_index, id-path) keys that
    survive deepcopy and structural mutation — the currency of Lamarckian
    ratio inheritance (cuts that survive a topology move keep their values)."""
    out = []
    for li, lvl in enumerate(dom.levels(root)):
        for b in solver._branches(lvl):
            if b.below is None or not b.below.divided:
                out.append(((li, b.id), b))
    return out


def ratio_map(root: dom.Node) -> dict[tuple[int, str], float]:
    return {k: b.division[0] for k, b in free_with_keys(root)}


def warm_x0(root: dom.Node, ratios: dict[tuple[int, str], float]) -> np.ndarray:
    """Warm-start vector for ``root``: surviving cuts inherit, new cuts 0.5."""
    return np.array([ratios.get(k, 0.5) for k, _ in free_with_keys(root)])


@dataclass
class Result:
    x: np.ndarray  # best equal-offset ratios, aligned with solver.free_branches(root)
    fitness: float
    n_fails: int
    fail_lines: tuple[str, ...]
    x0_fitness: float
    x0_n_fails: int
    n_evals: int  # oracle evaluations consumed (scored .dom files)
    n_oracle_calls: int  # perl invocations


class OracleEvaluator:
    """Scores ratio vectors for a frozen topology via the batched oracle.

    Owns a scratch directory seeded with the programme config (and occlusion
    field, if any) so ``urb-fitness.pl`` finds them in its working directory.
    Use as a context manager, or call ``close()``.
    """

    _CONFIGS = ("patterns.config", "costs.config", "occlusion.field")

    def __init__(
        self,
        root: dom.Node,
        programme_dir: str | Path,
        urb_root: str | Path = oracle.DEFAULT_URB_ROOT,
    ):
        self.root = root
        self.free = solver.free_branches(root)
        self.urb_root = Path(urb_root)
        self._dir = Path(tempfile.mkdtemp(prefix="innerloop_"))
        for name in self._CONFIGS:
            src = Path(programme_dir) / name
            if src.exists():
                shutil.copy(src, self._dir)
        self.n_evals = 0
        self.n_oracle_calls = 0

    def __enter__(self) -> "OracleEvaluator":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    @property
    def x_current(self) -> np.ndarray:
        # Midpoint projection: legacy designs carry slightly unequal offsets
        # (a != b); (a+b)/2 is the least-damaging equal-offset start.
        return np.array([(b.division[0] + b.division[1]) / 2 for b in self.free], dtype=float)

    def apply(self, x: np.ndarray) -> None:
        xc = np.clip(x, _EPS, 1 - _EPS)
        for j, b in enumerate(self.free):
            b.division = [float(xc[j]), float(xc[j])]

    def evaluate(self, xs: list[np.ndarray]) -> list[oracle.Score]:
        """Score a population of ratio vectors in one oracle invocation."""
        paths = []
        for i, x in enumerate(xs):
            self.apply(x)
            p = self._dir / f"member_{i:04d}.dom"
            dom.dump(self.root, str(p))
            paths.append(p)
        scores = oracle.score_batch(paths, self.urb_root)
        self.n_evals += len(xs)
        self.n_oracle_calls += 1
        return scores


def compass_search(
    ev: OracleEvaluator,
    x0: np.ndarray,
    budget: int = 200,
    step0: float = 0.25,
    step_tol: float = 1e-3,
    n_random: int | None = None,
    seed: int = 0,
) -> Result:
    """Batched compass search with pattern-move and random augmentation.

    Each iteration proposes ±step along every axis, Hooke-Jeeves *pattern
    moves* (1x and 2x extrapolations of the last successful displacement),
    and ``n_random`` random unit directions (default DOF of them) — all
    scored in ONE oracle call — moves greedily to the best improver, and
    halves the step when none improves. The augmentations matter: the
    ``0.5^n`` failure cliff creates diagonal ridges where every single-axis
    move adds a failure but coordinated moves do not; pure compass search
    stalls there, and with only ~budget/(3·DOF) moves available each move
    must be able to cover ground along a ridge.
    """
    rng = np.random.default_rng(seed)
    x = np.clip(np.asarray(x0, dtype=float), _EPS, 1 - _EPS)
    n = len(x)
    if n_random is None:
        n_random = n
    s = ev.evaluate([x])[0]
    best = Result(
        x=x.copy(), fitness=s.fitness, n_fails=s.n_fails, fail_lines=s.fail_lines,
        x0_fitness=s.fitness, x0_n_fails=s.n_fails,
        n_evals=0, n_oracle_calls=0,
    )

    step = step0
    momentum: np.ndarray | None = None
    while step >= step_tol and ev.n_evals < budget:
        cands = []
        for i in range(n):
            for sign in (1.0, -1.0):
                c = best.x.copy()
                c[i] = np.clip(c[i] + sign * step, _EPS, 1 - _EPS)
                if abs(c[i] - best.x[i]) > 1e-12:
                    cands.append(c)
        if momentum is not None:
            for scale in (1.0, 2.0):
                c = np.clip(best.x + scale * momentum, _EPS, 1 - _EPS)
                if np.max(np.abs(c - best.x)) > 1e-12:
                    cands.append(c)
        for _ in range(n_random):
            d = rng.standard_normal(n)
            d /= np.linalg.norm(d)
            c = np.clip(best.x + step * d, _EPS, 1 - _EPS)
            if np.max(np.abs(c - best.x)) > 1e-12:
                cands.append(c)
        if not cands:
            break
        scores = ev.evaluate(cands)
        i_best = max(range(len(cands)), key=lambda i: scores[i].fitness)
        s = scores[i_best]
        if s.fitness > best.fitness:
            momentum = cands[i_best] - best.x
            best.x = cands[i_best]
            best.fitness = s.fitness
            best.n_fails = s.n_fails
            best.fail_lines = s.fail_lines
        else:
            momentum = None
            step *= 0.5

    best.n_evals = ev.n_evals
    best.n_oracle_calls = ev.n_oracle_calls
    return best


def cma_search(
    ev: OracleEvaluator,
    x0: np.ndarray,
    budget: int = 200,
    sigmas: tuple[float, ...] = (0.05, 0.15),
    popsize: int | None = None,
    seed: int = 0,
) -> Result:
    """Multi-start CMA-ES over the ratio box, one batched oracle call per
    generation.

    Covariance adaptation handles the diagonal ridges of the ``0.5^n``
    landscape that stall axis-aligned pattern search; the ask/tell population
    maps one-to-one onto ``OracleEvaluator.evaluate``.

    One sigma does not fit all warm starts (measured at budget 200):
    2f45907 needs a *local* phase — at sigma 0.15 the search wanders out of
    the narrow low-failure region near the start and the ``0.5^n`` cliff never
    lets it back in (0.0084/3 fails vs 0.0164/2 fails at 0.05) — while
    candidate-002's best basin is further out and needs sigma 0.15
    (0.0160 vs 0.0117 at 0.05). So the budget is split across restart phases
    from the same ``x0``, one per entry of ``sigmas``, tracking the global
    best across phases. Later phases double the population (IPOP-style):
    exploratory phases are otherwise seed-lucky — at default popsize,
    candidate-002's sigma-0.15 phase scored 0.0160 or 0.0123 depending only
    on the seed.
    """
    import cma

    x = np.clip(np.asarray(x0, dtype=float), _EPS, 1 - _EPS)
    n = len(x)
    s = ev.evaluate([x])[0]
    best = Result(
        x=x.copy(), fitness=s.fitness, n_fails=s.n_fails, fail_lines=s.fail_lines,
        x0_fitness=s.fitness, x0_n_fails=s.n_fails,
        n_evals=0, n_oracle_calls=0,
    )

    base_popsize = popsize if popsize is not None else 4 + int(3 * np.log(n))
    for phase, sigma0 in enumerate(sigmas):
        phase_budget = (budget - ev.n_evals) // (len(sigmas) - phase)
        phase_end = ev.n_evals + max(phase_budget, 0)
        opts = {
            "bounds": [_EPS, 1 - _EPS],
            # pycma treats seed 0 (and None) as "seed from clock"; offset so
            # the default seed=0 is still deterministic
            "seed": seed + phase + 1,
            "verbose": -9,
            "popsize": base_popsize * 2**phase,
        }
        es = cma.CMAEvolutionStrategy(x, sigma0, opts)
        while not es.stop() and ev.n_evals < phase_end:
            xs = es.ask()
            scores = ev.evaluate([np.asarray(xi) for xi in xs])
            es.tell(xs, [-sc.fitness for sc in scores])
            i = max(range(len(xs)), key=lambda j: scores[j].fitness)
            if scores[i].fitness > best.fitness:
                best.x = np.asarray(xs[i]).copy()
                best.fitness = scores[i].fitness
                best.n_fails = scores[i].n_fails
                best.fail_lines = scores[i].fail_lines

    best.n_evals = ev.n_evals
    best.n_oracle_calls = ev.n_oracle_calls
    return best


_METHODS = {"cma": cma_search, "compass": compass_search}


def optimise(
    root: dom.Node,
    programme_dir: str | Path,
    x0: np.ndarray | None = None,
    budget: int = 200,
    method: str = "cma",
    urb_root: str | Path = oracle.DEFAULT_URB_ROOT,
    **search_kw,
) -> Result:
    """Optimise the free division ratios of ``root`` in place; return the best.

    ``x0=None`` starts from the topology's current ratios (cold start); pass a
    parent's optimised ratios for a Lamarckian warm start. On return ``root``
    carries the best ratios found.
    """
    with OracleEvaluator(root, programme_dir, urb_root) as ev:
        if x0 is None:
            x0 = ev.x_current
        if len(x0) == 0:  # undivided topology (e.g. a bare plot): nothing to optimise
            s = ev.evaluate([np.empty(0)])[0]
            return Result(x=np.empty(0), fitness=s.fitness, n_fails=s.n_fails,
                          fail_lines=s.fail_lines, x0_fitness=s.fitness,
                          x0_n_fails=s.n_fails, n_evals=1, n_oracle_calls=1)
        result = _METHODS[method](ev, x0, budget=budget, **search_kw)
        ev.apply(result.x)  # leave the tree at the optimum (Lamarckian write-back)
    return result

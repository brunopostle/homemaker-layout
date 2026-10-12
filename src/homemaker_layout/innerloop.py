"""Geometry inner loop: full-objective equal-offset ratio optimisation.

The memetic architecture (DESIGN.md §5) delegates geometry to this module: for
a *frozen* slicing topology, optimise the equal-offset division ratios of the
free branches (one DOF per cut, ``solver.free_branches`` — lowest-storey cut
ownership) against the FULL fitness. Never a proxy objective — §4.2 falsified
that; the full objective's ``0.5^n`` failure cliff is what protects the inner
loop from trading into new failures (§4.5).

Fitness is the native Python evaluator. The Perl oracle it was ported from is
gone (DESIGN.md §39.21) -- "oracle call" below means one batched evaluation.
Warm-starting from a parent's optimised ratios is ``x0=`` (§5 decision 6,
Lamarckian inheritance).
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import dom, solver

_EPS = 0.02  # keep cuts off the edges; matches solver/_experiments convention

# Storey heights as inner-loop variables (owner's ruling, 2026-10-08/09,
# DESIGN.md §39.125, §39.128; `homemaker-py-y4p4.2`). "4.86 m depth is only a
# limit for low ceilings, the solver should be able to raise the ceiling
# height of a storey and allow deeper rooms"; "2.7 can be a minimum height,
# but we should leave the maximum open". The scorer has always read a storey's
# height -- lit wall, wall cost, the risers a stair needs -- and `.dom` has
# always stored it; nothing ever moved it.
#
# One variable per storey, appended to the ratio vector, so every search
# method takes it as it takes a cut. It lives on the same (_EPS, 1 - _EPS)
# interval as a ratio and maps to metres through a curve with a floor and no
# practical ceiling: 2.7 m at the low end, 3.0 m at 0.25, 3.66 m at 0.5, and
# some fifty metres at the high end. What keeps a storey low is the cost of
# its walls, which the objective already charges.
HEIGHT_MIN = 2.7
HEIGHT_SCALE = 1.0


def height_to_u(h: float) -> float:
    t = max(float(h) - HEIGHT_MIN, 0.0) / HEIGHT_SCALE
    return (t + _EPS) / (1.0 + t)


def u_to_height(u: float) -> float:
    u = min(max(float(u), _EPS), 1 - _EPS)
    return HEIGHT_MIN + HEIGHT_SCALE * (u - _EPS) / (1.0 - u)


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


def probe_heights(ev: "NativeEvaluator", x: np.ndarray,
                  steps: "tuple[float, ...]" = (0.3, 0.6, 0.9, -0.3)) -> np.ndarray:
    """A coarse look up and down each storey's height before the fine search.

    A storey's height has a valley in it that a local method does not cross:
    raising a ceiling costs wall at once and pays only when a room's daylight
    passes, which may be half a metre away. Measured on the owner's hand-drawn
    harbor-house (§39.128): every storey at 3.6 m clears five fails, and 4,000
    evaluations of Nelder-Mead from 3.0 m moved no storey by more than a
    centimetre. So try each storey, then all of them together, a few steps
    away, and keep what scores better. ``(storeys + 1) * len(steps)``
    evaluations, counted against the budget like any other.
    """
    n = len(ev.free)
    best_x = np.asarray(x, dtype=float).copy()
    best = ev.evaluate([best_x])[0].fitness
    k = ev.n_heights
    groups = [[i] for i in range(k)] + ([list(range(k))] if k > 1 else [])
    for group in groups:
        base, found = best_x.copy(), None
        for d in steps:
            y = base.copy()
            for i in group:
                y[n + i] = height_to_u(u_to_height(base[n + i]) + d)
            f = ev.evaluate([y])[0].fitness
            if f > best:
                best, found = f, y
        if found is not None:
            best_x = found
    return best_x


@dataclass
class Result:
    # best equal-offset ratios, aligned with solver.free_branches(root) -- and,
    # when storey heights were tuned, one more entry per storey after them
    # (`height_to_u`); `NativeEvaluator.apply` is what reads both
    x: np.ndarray
    fitness: float
    n_fails: int
    fail_lines: tuple[str, ...]
    x0_fitness: float
    x0_n_fails: int
    n_evals: int  # oracle evaluations consumed (scored .dom files)
    n_oracle_calls: int  # perl invocations



def compass_search(
    ev: NativeEvaluator,
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
    ev: NativeEvaluator,
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
    maps one-to-one onto ``NativeEvaluator.evaluate``.

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


class _BudgetExhausted(Exception):
    pass


def nm_search(
    ev: "NativeEvaluator",
    x0: np.ndarray,
    budget: int = 200,
    seed: int = 0,
) -> Result:
    """Multi-start Nelder-Mead: x0 first, random restarts until budget spent.

    Sequential — one evaluation per oracle call.  Outperforms CMA-ES across
    all DOF sizes at native-fitness speed (bakeoff homemaker-py-d6d): wins
    early (budget 80) for programme-house (6-7 DOF) and decisively for
    harbor-house scale (35-40 DOF) where CMA exhausts its convergence
    detector in ~3 generations and stops.
    """
    from scipy.optimize import minimize

    rng = np.random.default_rng(seed)
    n = len(x0)
    n_h = getattr(ev, "n_heights", 0) if n > len(getattr(ev, "free", ())) else 0
    x = np.clip(np.asarray(x0, dtype=float), _EPS, 1 - _EPS)
    s = ev.evaluate([x])[0]
    best = Result(
        x=x.copy(), fitness=s.fitness, n_fails=s.n_fails, fail_lines=s.fail_lines,
        x0_fitness=s.fitness, x0_n_fails=s.n_fails, n_evals=0, n_oracle_calls=0,
    )

    def _f(xi):
        if ev.n_evals >= budget:
            raise _BudgetExhausted
        sc = ev.evaluate([np.asarray(xi, dtype=float)])[0]
        if sc.fitness > best.fitness:
            best.x = np.asarray(xi, dtype=float).copy()
            best.fitness = sc.fitness
            best.n_fails = sc.n_fails
            best.fail_lines = sc.fail_lines
        return -sc.fitness

    start = x.copy()
    while ev.n_evals < budget:
        try:
            minimize(
                _f, start, method="Nelder-Mead",
                bounds=[(_EPS, 1 - _EPS)] * n,
                options={"maxfev": budget - ev.n_evals, "xatol": 1e-3, "fatol": 1e-10},
            )
        except _BudgetExhausted:
            break
        start = rng.uniform(0.1, 0.9, n)
        if n_h:
            # a restart scatters the walls; a storey 2.8 m or 11 m high at
            # random is not a restart, so the heights carry on from the best
            start[-n_h:] = best.x[-n_h:]

    best.n_evals = ev.n_evals
    best.n_oracle_calls = ev.n_oracle_calls
    return best


_METHODS = {"nm": nm_search, "cma": cma_search, "compass": compass_search}


from dataclasses import dataclass as _dc


@_dc
class _NativeScore:
    """Scalar + failure set for one ratio vector."""

    fitness: float
    fail_lines: tuple

    @property
    def n_fails(self) -> int:
        return len(self.fail_lines)


class NativeEvaluator:
    """Scores ratio vectors for a frozen topology via the native Python fitness.

    Each ``evaluate`` call runs ``Fitness.score_with_fails``
    serially over the batch (all in-process, no parallelism needed at this
    scale).
    """

    def __init__(self, root: dom.Node, programme_dir: str | Path,
                 conf_overrides: dict | None = None, heights: bool = False):
        from . import fitness as fit_mod

        self.root = root
        self.free = solver.free_branches(root)
        # the storeys whose height is a variable: all of them, or none
        self.storeys = dom.levels(root) if heights else []
        self.n_heights = len(self.storeys)
        conf, cost = fit_mod.load_config(programme_dir, overrides=conf_overrides)
        self._fit = fit_mod.Fitness(conf, cost)
        self.n_evals = 0
        self.n_oracle_calls = 0  # legacy name: batches, not Perl calls

    def __enter__(self) -> "NativeEvaluator":
        return self

    def __exit__(self, *exc) -> None:
        pass

    @property
    def x_current(self) -> np.ndarray:
        return np.array(
            [(b.division[0] + b.division[1]) / 2 for b in self.free], dtype=float
        )

    @property
    def x_heights(self) -> np.ndarray:
        return np.array([height_to_u(lvl.height if lvl.height else 3.0)
                         for lvl in self.storeys], dtype=float)

    def apply(self, x: np.ndarray) -> None:
        """Write a vector to the tree: the ratios, and the storey heights too
        if the vector carries them (it need not -- a vector of ratios alone
        leaves the heights where they are)."""
        xc = np.clip(x, _EPS, 1 - _EPS)
        for j, b in enumerate(self.free):
            b.division = [float(xc[j]), float(xc[j])]
        if self.storeys and len(xc) == len(self.free) + len(self.storeys):
            for lvl, u in zip(self.storeys, xc[len(self.free):]):
                lvl.height = u_to_height(u)

    def evaluate(self, xs: list[np.ndarray]) -> "list[_NativeScore]":
        """Score a batch of ratio vectors; returns objects with .fitness /
        .n_fails / .fail_lines."""
        import copy

        results = []
        for x in xs:
            self.apply(x)
            root_copy = copy.deepcopy(self.root)
            score, fails = self._fit.score_with_fails(root_copy)
            results.append(_NativeScore(fitness=score, fail_lines=fails))
        self.n_evals += len(xs)
        self.n_oracle_calls += 1
        return results


def optimise(
    root: dom.Node,
    programme_dir: str | Path,
    x0: np.ndarray | None = None,
    budget: int = 200,
    method: str = "nm",

    conf_overrides: dict | None = None,
    heights: bool = False,
    height_probe: bool = False,
    **search_kw,
) -> Result:
    """Optimise the free division ratios of ``root`` in place; return the best.

    ``x0=None`` starts from the topology's current ratios (cold start); pass a
    parent's optimised ratios for a Lamarckian warm start. On return ``root``
    carries the best ratios found.

    ``heights`` adds one variable per storey, its floor-to-floor height
    (never below ``HEIGHT_MIN``, no ceiling), to the same search; ``x0`` is
    still the RATIOS, and the heights start where the tree has them, so a
    child inherits its parent's. ``Result.x`` then carries both.
    ``height_probe`` spends a few evaluations first on :func:`probe_heights`;
    for tuning ONE design (a search has `operators.mutate_storey_height` to
    make the same jumps across its population, at no cost per child).

    evaluate with the native Python fitness.
    """
    ev_cls = NativeEvaluator
    ev_args = (root, programme_dir, conf_overrides, heights)
    with ev_cls(*ev_args) as ev:
        if x0 is None:
            x0 = ev.x_current
        if ev.n_heights and len(x0) == len(ev.free):
            x0 = np.concatenate([np.asarray(x0, dtype=float), ev.x_heights])
            if height_probe:
                x0 = probe_heights(ev, x0)
        if len(x0) == 0:  # undivided topology (e.g. a bare plot): nothing to optimise
            s = ev.evaluate([np.empty(0)])[0]
            return Result(x=np.empty(0), fitness=s.fitness, n_fails=s.n_fails,
                          fail_lines=s.fail_lines, x0_fitness=s.fitness,
                          x0_n_fails=s.n_fails, n_evals=1, n_oracle_calls=1)
        result = _METHODS[method](ev, x0, budget=budget, **search_kw)
        ev.apply(result.x)  # leave the tree at the optimum (Lamarckian write-back)
    return result

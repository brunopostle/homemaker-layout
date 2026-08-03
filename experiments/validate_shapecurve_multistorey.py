"""Multi-storey validation harness for shapecurve.py (homemaker-py-koo).

Same protocol as validate_shapecurve.py (DP feasibility vs NM search that
directly MINIMISES shape-fail count, shape-fail-count-only comparison -- see
that module's docstring for why), but for genuinely multi-storey topologies:
each trial starts from a 2-storey seed (``operators.mutate_level_add`` once on
a bare single-leaf plot) and grows leaves across BOTH storeys via
``driver.random_topology``'s ``mutate_divide`` loop (which picks candidate
leaves from every level uniformly, see ``operators._leaves``), so a trial
topology naturally contains a mix of below-inherited-fixed spines and
below-fixed-box/free-split fringe nodes on the upper storey -- exactly the
scenario homemaker-py-koo generalised the DP for.

Usage: python experiments/validate_shapecurve_multistorey.py [n_topologies] [nm_budget] [grid_n] [programme_dir]
"""

from __future__ import annotations

import copy
import sys
import time

import numpy as np

from homemaker_layout import dom, driver, fitness as fit_mod, geometry, innerloop, operators, solver
from homemaker_layout import shapecurve as sc

PROGRAMME_DIR = "examples/harbor-house"
_SHAPE_SUFFIXES = (" size", " width", " proportion")


class ShapeFailEvaluator(innerloop.NativeEvaluator):
    """Duplicated from validate_shapecurve.py (kept standalone-runnable, like
    that script, rather than depending on package-relative imports): scores
    -n_shape_fails (ties broken by the real fitness) so nm_search's greedy
    hill-climb directly minimises shape-fail count instead of the full
    aggregate objective -- see that module's docstring for why this is the
    correct apples-to-apples comparison against what the DP claims to solve."""

    def evaluate(self, xs):
        results = []
        for x in xs:
            self.apply(x)
            root_copy = copy.deepcopy(self.root)
            score, fails = self._fit.score_with_fails(root_copy)
            n_shape = sum(1 for f in fails if f.endswith(_SHAPE_SUFFIXES))
            proxy_fitness = -n_shape + min(score, 0.999)
            results.append(innerloop._NativeScore(fitness=proxy_fitness, fail_lines=fails))
        self.n_evals += len(xs)
        self.n_oracle_calls += 1
        return results


def _two_storey_seed(programme_dir: str, rng: np.random.Generator, types: list[str]) -> dom.Node:
    base = dom.load(f"{programme_dir}/init.dom")
    two_storey, _ = operators.mutate_level_add(base, rng, types)
    return two_storey


def main(n_topologies: int = 100, nm_budget: int = 100, grid_n: int = 150,
         programme_dir: str = PROGRAMME_DIR) -> None:
    conf, cost = fit_mod.load_config(programme_dir)
    fit = fit_mod.Fitness(conf, cost)
    types = sorted(fit.spaces.keys())

    rng = np.random.default_rng(12345)
    n_agree = 0
    n_dp_feasible = 0
    n_nm_feasible = 0
    false_positive = 0  # DP says feasible, NM finds a shape fail
    false_negative = 0  # DP says infeasible, NM reaches 0 shape fails anyway
    dp_time_total = 0.0
    nm_time_total = 0.0
    rows = []

    i = 0
    attempts = 0
    while i < n_topologies:
        attempts += 1
        n_leaves = int(rng.integers(3, 20))
        seed = int(rng.integers(0, 2**31 - 1))
        trng = np.random.default_rng(seed)
        seed_root = _two_storey_seed(programme_dir, trng, types)
        topo = driver.random_topology(seed_root, n_leaves, trng, types)
        dom.link(topo)
        if len(dom.levels(topo)) < 2:
            continue
        if len(solver.free_branches(topo)) < 2:
            continue  # not enough freedom for a meaningful multi-storey check
        i += 1

        t0 = time.time()
        try:
            dp_ok, info = sc.solve(topo, fit, grid_n=grid_n)
        except Exception as exc:  # noqa: BLE001 -- record and keep going
            dp_ok, info = None, {"error": repr(exc)}
        dp_time = time.time() - t0
        dp_time_total += dp_time

        t0 = time.time()
        topo_nm = copy.deepcopy(topo)
        geometry.clear_cache()
        with ShapeFailEvaluator(topo_nm, programme_dir) as ev:
            x0 = ev.x_current
            if len(x0) == 0:
                nm_shape_fails: list[str] = []
            else:
                r = innerloop.nm_search(ev, x0, budget=nm_budget)
                nm_shape_fails = [f for f in r.fail_lines if f.endswith(_SHAPE_SUFFIXES)]
        nm_time = time.time() - t0
        nm_time_total += nm_time
        nm_ok = len(nm_shape_fails) == 0

        if dp_ok is None:
            rows.append((i, n_leaves, seed, "ERROR", nm_ok, dp_time, nm_time, info.get("error")))
            continue

        if dp_ok:
            n_dp_feasible += 1
        if nm_ok:
            n_nm_feasible += 1
        agree = dp_ok == nm_ok
        if agree:
            n_agree += 1
        else:
            if dp_ok and not nm_ok:
                false_positive += 1
            else:
                false_negative += 1
        rows.append((i, n_leaves, seed, dp_ok, nm_ok, dp_time, nm_time, len(nm_shape_fails)))

    print(f"topologies: {n_topologies} (attempts {attempts})")
    print(f"agreement: {n_agree}/{n_topologies} = {100*n_agree/n_topologies:.1f}%")
    print(f"  false positive (DP feasible, NM shape-fails): {false_positive}")
    print(f"  false negative (DP infeasible, NM 0 shape-fails): {false_negative}")
    print(f"DP feasible: {n_dp_feasible}/{n_topologies}   NM 0-shape-fail: {n_nm_feasible}/{n_topologies}")
    print(f"DP total time: {dp_time_total:.2f}s  ({dp_time_total/n_topologies*1000:.1f} ms/topology)")
    print(f"NM total time: {nm_time_total:.2f}s  ({nm_time_total/n_topologies*1000:.1f} ms/topology)")
    print(f"speedup: {nm_time_total/dp_time_total:.1f}x")

    print("\nmismatches:")
    for row in rows:
        if row[3] != row[4] and row[3] != "ERROR":
            print(" ", row)
    print("\nerrors:")
    for row in rows:
        if row[3] == "ERROR":
            print(" ", row)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    budget = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    grid_n = int(sys.argv[3]) if len(sys.argv) > 3 else 150
    prog_dir = sys.argv[4] if len(sys.argv) > 4 else PROGRAMME_DIR
    main(n, budget, grid_n, prog_dir)

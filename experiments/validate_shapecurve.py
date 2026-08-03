"""Validation harness for shapecurve_spike.py (homemaker-py-2g7.4).

For N random harbor-house-l0 topologies: run the DP feasibility check and an
NM search that directly MINIMISES the shape-fail count (size/width/
proportion FAIL_THRESHOLD family only -- crinkliness/adjacency/level/etc are
out of scope for this DP, see shapecurve_spike.py's module docstring), and
compare verdicts.

NB: the first version of this harness polished against innerloop.optimise's
FULL aggregate fitness (missing-space/adjacency/etc fails included) and found
many "false positives" -- but a directed check showed the DP's own realised
ratios genuinely score 0 shape fails in those cases; NM's full-objective
search had simply wandered away from that point, because on a topology
missing most of its programme (a `random_topology`-grown tree rarely places
all 10 codes), the 0.5^n missing-space penalty swamps the objective and NM
has no gradient pressure to preserve shape-feasibility specifically. Scoring
by shape-fail-count ALONE is the correct apples-to-apples comparison against
what the DP claims to solve.

Usage: python experiments/validate_shapecurve.py [n_topologies] [nm_budget]
"""

from __future__ import annotations

import copy
import math
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import yaml

from homemaker_layout import dom, driver, fitness as fit_mod, geometry, innerloop
from homemaker_layout import shapecurve as sc

PROGRAMME_DIR = "examples/harbor-house-l0"
_SHAPE_SUFFIXES = (" size", " width", " proportion")


def rotated_plot_dir(src_dir: str, degrees: float) -> Path:
    """A scratch copy of ``src_dir`` with the plot's ``node:`` corners rotated
    ``degrees`` about their centroid -- for testing that the DP's feasibility
    verdict doesn't depend on the plot's orientation relative to the survey/
    CRS x/y axes it happens to be recorded in (see DESIGN.md §37.2,
    "Correction 1"). The programme (patterns.config) is untouched -- rotation
    changes nothing about which spaces are required or their targets, only
    the plot's physical orientation.
    """
    src = Path(src_dir)
    dst = Path(tempfile.mkdtemp(prefix="shapecurve_rot_"))
    d = yaml.safe_load((src / "init.dom").read_text())
    pts = d["node"]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    theta = math.radians(degrees)
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    def _rot(p):
        x, y = p[0] - cx, p[1] - cy
        return [x * cos_t - y * sin_t + cx, x * sin_t + y * cos_t + cy]

    d["node"] = [_rot(p) for p in pts]
    (dst / "init.dom").write_text(yaml.safe_dump(d, default_flow_style=False))
    shutil.copy(src / "patterns.config", dst / "patterns.config")
    return dst


class ShapeFailEvaluator(innerloop.NativeEvaluator):
    """Like NativeEvaluator, but ``evaluate`` scores -n_shape_fails (ties
    broken by the real fitness) so nm_search's greedy hill-climb directly
    minimises the shape-fail count instead of the full aggregate objective."""

    def evaluate(self, xs):
        results = []
        for x in xs:
            self.apply(x)
            root_copy = copy.deepcopy(self.root)
            score, fails = self._fit.score_with_fails(root_copy)
            n_shape = sum(1 for f in fails if f.endswith(_SHAPE_SUFFIXES))
            proxy_fitness = -n_shape + min(score, 0.999)  # tie-break, sub-1 so it never crosses a fail-count boundary
            results.append(innerloop._NativeScore(fitness=proxy_fitness, fail_lines=fails))
        self.n_evals += len(xs)
        self.n_oracle_calls += 1
        return results


def main(n_topologies: int = 200, nm_budget: int = 100, grid_n: int = 150,
         programme_dir: str = PROGRAMME_DIR) -> None:
    seed_root = dom.load(f"{programme_dir}/init.dom")
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
        n_leaves = int(rng.integers(2, 15))
        seed = int(rng.integers(0, 2**31 - 1))
        trng = np.random.default_rng(seed)
        topo = driver.random_topology(seed_root, n_leaves, trng, types)
        dom.link(topo)
        lvl = dom.levels(topo)[0]
        if len(lvl.leaves()) < 2:
            continue  # undivided, nothing for the DP to do
        i += 1

        t0 = time.time()
        try:
            dp_ok, info = sc.solve(lvl, fit, grid_n=grid_n)
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
    # Usage: validate_shapecurve.py [n_topologies] [nm_budget] [grid_n] [rotate_deg] [programme_dir]
    # rotate_deg (optional, default 0): test on a scratch copy of the plot
    # rotated this many degrees about its centroid -- DESIGN.md §37.2's
    # rotation-invariance check (0 => plot unmodified).
    # programme_dir (optional, default examples/harbor-house-l0): homemaker-py-wkh
    # (DESIGN.md §37.5) uses this to sweep a genuinely non-rectangular plot
    # (e.g. examples/programme-house's skewed parallelogram) rather than only a
    # rotated copy of harbor-house-l0's near-rectangular one.
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    budget = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    grid_n = int(sys.argv[3]) if len(sys.argv) > 3 else 150
    rotate_deg = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
    base_dir = sys.argv[5] if len(sys.argv) > 5 else PROGRAMME_DIR
    prog_dir = str(rotated_plot_dir(base_dir, rotate_deg)) if rotate_deg else base_dir
    if rotate_deg:
        print(f"(testing on {base_dir}'s plot rotated {rotate_deg} deg -> {prog_dir})")
    main(n, budget, grid_n, prog_dir)

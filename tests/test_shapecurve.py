"""Tests for the shape-curve DP (homemaker-py-6xh, promoted from
experiments/shapecurve_spike.py; see DESIGN.md §37.2/§37.4 for the full
200-topology validation this unit scale is a fast smoke check of)."""

from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, driver, fitness as fit_mod, shapecurve, solver

HARBOR_L0 = Path(__file__).parent.parent / "examples" / "harbor-house-l0"

pytestmark = pytest.mark.skipif(not HARBOR_L0.is_dir(), reason="harbor-house-l0 not available")


def _fit():
    conf, cost = fit_mod.load_config(str(HARBOR_L0))
    return fit_mod.Fitness(conf, cost)


def _small_feasible_topology():
    """A tiny 2-leaf (C/O only, no size/adjacency constraints to speak of)
    topology on harbor-house-l0's plot -- deterministically shape-feasible
    (verified: driver.random_topology(seed, 2, rng(0), ['C', 'O']))."""
    seed = dom.load(str(HARBOR_L0 / "init.dom"))
    rng = np.random.default_rng(0)
    return driver.random_topology(seed, 2, rng, ["C", "O"])


def test_eligible_guards_multistorey_and_sharing():
    root = dom.load(str(HARBOR_L0 / "generated.dom"))
    assert len(dom.levels(root)) == 1
    assert shapecurve.eligible(root)
    assert not shapecurve.eligible(root, leaf_sharing=True)
    assert not shapecurve.eligible(root, superpose=True)
    assert not shapecurve.eligible(root, max_share=3)
    assert not shapecurve.eligible(root, multi_use=True)

    seed = dom.load(str(HARBOR_L0 / "init.dom"))
    seed.above = dom.Node(rotation=0)  # fake a second storey
    assert len(dom.levels(seed)) == 2
    assert not shapecurve.eligible(seed)


def test_solve_feasible_root_realises_zero_shape_fails(tmp_path):
    """A small, obviously-feasible topology's DP-realised ratios round-trip
    through dom.dumps/dom.load and independently verify as zero shape fails
    under the real Fitness scorer."""
    root = _small_feasible_topology()
    fit = _fit()

    feasible, info = shapecurve.solve(root, fit)
    assert feasible is True
    assert info["w_plot"] > 0 and info["h_plot"] > 0

    out_path = tmp_path / "realised.dom"
    out_path.write_text(dom.dumps(root))
    reloaded = dom.load(str(out_path))

    _, fails = fit.score_with_fails(reloaded)
    shape_fails = [f for f in fails if f.endswith((" size", " width", " proportion"))]
    assert shape_fails == []


def test_solve_infeasible_topology_leaves_tree_untouched():
    """A topology with far more leaves than harbor-house-l0's plot can fit
    (each needing its own min width/area) is infeasible; solve() must not
    write partial/bogus ratios in that case."""
    seed = dom.load(str(HARBOR_L0 / "init.dom"))
    rng = np.random.default_rng(0)
    root = driver.random_topology(seed, 60, rng, ["k1", "l1", "b1", "C", "O"])
    fit = _fit()

    feasible, info = shapecurve.solve(root, fit)
    assert feasible is False
    # infeasible: no realised point to check, but the call must not raise
    # and must report the same plot dims as the feasible case's mechanism
    assert info["w_plot"] > 0 and info["h_plot"] > 0


def test_solve_is_deterministic():
    root = _small_feasible_topology()
    fit = _fit()
    f1, _ = shapecurve.solve(root, fit)
    divisions_1 = [tuple(b.division) for b in solver.free_branches(root)]
    f2, _ = shapecurve.solve(root, fit)
    divisions_2 = [tuple(b.division) for b in solver.free_branches(root)]
    assert f1 == f2 is True
    assert divisions_1 == pytest.approx(divisions_2)

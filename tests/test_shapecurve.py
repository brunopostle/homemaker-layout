"""Tests for the shape-curve DP (homemaker-py-6xh, promoted from
experiments/shapecurve_spike.py; see DESIGN.md §37.2/§37.4 for the full
200-topology validation this unit scale is a fast smoke check of)."""

import copy
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


def _two_storey_feasible_topology():
    """Level 0: the whole plot as one undivided 'O' room (trivially
    feasible, below is always None at level 0). Level 1: an independent
    fresh 2-leaf 'C'/'O' topology whose root inherits the *whole plot* as
    its fixed box (its below -- level 0's root -- exists but is undivided,
    so the root itself is a free-region-root per ``shapecurve._region_roots``,
    pinned to the same box ``_small_feasible_topology`` already validates as
    shape-feasible for a single storey)."""
    base_seed = dom.load(str(HARBOR_L0 / "init.dom"))
    level0 = copy.deepcopy(base_seed)
    level0.type = "O"
    rng = np.random.default_rng(0)
    level1 = driver.random_topology(dom.load(str(HARBOR_L0 / "init.dom")), 2, rng, ["C", "O"])
    level0.above = level1
    dom.link(level0)
    return level0


def _two_storey_mixed_topology(child_types=("O", "O")):
    """Level 0: the same 2-leaf 'C'/'O' topology ``_small_feasible_topology``
    validates. Level 1: an exact structural copy (so its root and both
    leaves start out below-inherited/FIXED, wall-stacked on level 0), with
    one of its leaves (``target``, id 'l') further divided into two brand
    new leaves of ``child_types`` -- a genuine below-fixed-box/free-split
    (case B) fringe node nested under a below-fixed-divided (case A) root,
    the mixed scenario ``homemaker-py-koo`` adds support for. Returns
    ``(root, target)``."""
    seed = dom.load(str(HARBOR_L0 / "init.dom"))
    rng = np.random.default_rng(0)
    level0 = driver.random_topology(seed, 2, rng, ["C", "O"])
    level1 = copy.deepcopy(level0)
    level0.above = level1
    dom.link(level0)

    target = level1.left
    target.division = [0.5, 0.5]
    target.rotation = 0
    target.left = dom.Node(rotation=0, type=child_types[0])
    target.right = dom.Node(rotation=0, type=child_types[1])
    dom.link(level0)
    return level0, target


def test_eligible_guards_superpose_not_storey_count_or_sharing():
    """`eligible` guards only what `leaf_constraints` cannot model.

    homemaker-py-koo removed the storey-count guard (below-inherited fixed
    splits, §37.6). homemaker-py-tym removed the leaf_sharing/max_share/
    multi_use guards by MODELLING them: `leaf_constraints` now mirrors
    `quality_size`'s k-scaling and co_type adjustment, reading the evaluator's
    own Fitness so it cannot drift.

    `superpose` remains excluded, for a different reason than the others: it
    does not rescale a target, it changes WHICH TYPE the leaf is scored as, and
    that collapse happens after the DP has read `leaf.type`.
    """
    root = dom.load(str(HARBOR_L0 / "generated.dom"))
    assert len(dom.levels(root)) == 1
    assert shapecurve.eligible(root)
    assert shapecurve.eligible(root, leaf_sharing=True)
    assert shapecurve.eligible(root, max_share=3)
    assert shapecurve.eligible(root, multi_use=True)
    assert not shapecurve.eligible(root, superpose=True)

    seed = dom.load(str(HARBOR_L0 / "init.dom"))
    seed.above = dom.Node(rotation=0)  # fake a second storey
    assert len(dom.levels(seed)) == 2
    assert shapecurve.eligible(seed)
    assert shapecurve.eligible(seed, leaf_sharing=True)
    assert not shapecurve.eligible(seed, superpose=True)


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


def test_is_feasible_agrees_with_solve_but_never_writes(monkeypatch):
    """homemaker-py-wkh: the hard-prune caller needs the boolean verdict
    without solve()'s tree mutation, so ``is_feasible`` must (a) agree with
    ``solve``'s own verdict and (b) never write ``division`` -- verified on
    both the feasible and infeasible fixtures already exercised above."""
    fit = _fit()

    feasible_root = _small_feasible_topology()
    before = [tuple(b.division) for b in solver.free_branches(feasible_root)]
    assert shapecurve.is_feasible(feasible_root, fit) is True
    after = [tuple(b.division) for b in solver.free_branches(feasible_root)]
    assert before == after

    seed = dom.load(str(HARBOR_L0 / "init.dom"))
    rng = np.random.default_rng(0)
    infeasible_root = driver.random_topology(seed, 60, rng, ["k1", "l1", "b1", "C", "O"])
    before = [tuple(b.division) for b in solver.free_branches(infeasible_root)]
    assert shapecurve.is_feasible(infeasible_root, fit) is False
    after = [tuple(b.division) for b in solver.free_branches(infeasible_root)]
    assert before == after


# --------------------------------------------------------------------------- #
# Multi-storey (homemaker-py-koo, DESIGN.md §37.6)
# --------------------------------------------------------------------------- #


def test_solve_multistorey_feasible_realises_zero_shape_fails(tmp_path):
    """A 2-storey topology whose upper storey is a fresh, independently-free
    2-leaf split (pinned to the whole plot, since the ground storey below it
    is a single undivided room) round-trips to zero size/width/proportion
    fails at every level, exactly like the single-storey case."""
    root = _two_storey_feasible_topology()
    fit = _fit()

    feasible, info = shapecurve.solve(root, fit)
    assert feasible is True
    assert info["w_plot"] > 0 and info["h_plot"] > 0
    assert info["n_levels"] == 2

    out_path = tmp_path / "realised.dom"
    out_path.write_text(dom.dumps(root))
    reloaded = dom.load(str(out_path))

    _, fails = fit.score_with_fails(reloaded)
    shape_fails = [f for f in fails if f.endswith((" size", " width", " proportion"))]
    assert shape_fails == []


def test_solve_multistorey_matches_free_branches(tmp_path):
    """Mixed fixture: level 1 is a structural copy of level 0 (so its root
    and both original leaves are below-fixed) with one leaf further divided
    into two brand new 'O' leaves (a below-fixed-box/free-split fringe node
    nested under a below-fixed-divided root). ``solve`` must write ratios on
    exactly ``solver.free_branches`` -- the pre-existing single-storey
    invariant this generalises -- and leave every below-fixed node's own
    ``division`` byte-identical, even though it sits on a realised subtree."""
    root, target = _two_storey_mixed_topology(child_types=("O", "O"))
    level1 = root.above
    fit = _fit()

    all_nodes_before = [(n, list(n.division))
                        for lvl in dom.levels(root) for n in shapecurve._divided_nodes(lvl)]
    free_before = [b for b in solver.free_branches(root)]

    feasible, _ = shapecurve.solve(root, fit)
    assert feasible is True

    # level 1's own root is below-fixed (its below, level 0's root, is
    # divided) so it must never appear as a free branch, and 'target' (a
    # fresh split introduced only at level 1) must.
    assert any(b is target for b in solver.free_branches(root))
    assert not any(b is level1 for b in solver.free_branches(root))

    for node, before in all_nodes_before:
        if any(node is b for b in free_before):
            continue
        assert node.division == before, "below-fixed node's division must never be written"

    out_path = tmp_path / "realised.dom"
    out_path.write_text(dom.dumps(root))
    reloaded = dom.load(str(out_path))
    _, fails = fit.score_with_fails(reloaded)
    shape_fails = [f for f in fails if f.endswith((" size", " width", " proportion"))]
    assert shape_fails == []


def test_solve_multistorey_infeasible_restores_every_level():
    """When an upper-storey free split is infeasible (a 'C' leaf forced into
    a below-fixed box too tall for its proportion/size bounds -- verified by
    inspection, not tuned to just barely fail), ``solve`` must roll back
    ALL levels, including the ground storey it already realised earlier in
    the same call -- not just the storey where infeasibility was detected."""
    root, target = _two_storey_mixed_topology(child_types=("C", "O"))
    level1 = root.above
    fit = _fit()

    before = {
        id(n): list(n.division)
        for lvl in dom.levels(root) for n in shapecurve._divided_nodes(lvl)
    }

    feasible, _ = shapecurve.solve(root, fit)
    assert feasible is False

    after = {
        id(n): list(n.division)
        for lvl in dom.levels(root) for n in shapecurve._divided_nodes(lvl)
    }
    assert after == before, "an infeasible upper storey must not leave the ground storey mutated"


def test_is_feasible_multistorey_never_writes():
    fit = _fit()

    feasible_root = _two_storey_feasible_topology()
    before = [tuple(b.division) for b in solver.free_branches(feasible_root)]
    assert shapecurve.is_feasible(feasible_root, fit) is True
    after = [tuple(b.division) for b in solver.free_branches(feasible_root)]
    assert before == after

    infeasible_root, _ = _two_storey_mixed_topology(child_types=("C", "O"))
    before = [tuple(b.division) for b in solver.free_branches(infeasible_root)]
    assert shapecurve.is_feasible(infeasible_root, fit) is False
    after = [tuple(b.division) for b in solver.free_branches(infeasible_root)]
    assert before == after


# --------------------------------------------------------------------------- #
# homemaker-py-tym / DESIGN.md §38.23 — leaf_sharing / co_type target modelling
# --------------------------------------------------------------------------- #
def _shared_seed():
    """A real harbor-house constructed seed, which stamps share>1 leaves."""
    from homemaker_layout import geometry, operators, programme

    d = "examples/harbor-house"
    reqs = programme.load_programme_dir(d)
    conf, cost = fit_mod.load_config(d, overrides={"leaf_sharing": True})
    fit = fit_mod.Fitness(conf, cost)
    root = operators.constructive_topology(
        dom.load(f"{d}/init.dom"), reqs, np.random.default_rng(0),
        sorted(reqs) + ["C", "O"], min_storeys=programme.storey_minimum(d),
        adjacency_aware=True, proportion_aware=True, circ_divisor=3,
        leaf_sharing=True, leaf_share_factor=3, depth_balanced=True,
        interior_outside=True, outside_divisor=3)
    geometry.clear_cache()
    dom.canonicalize_shares(root)
    return fit, root


@pytest.mark.skipif(not Path("examples/harbor-house").is_dir(),
                    reason="harbor-house not available")
def test_leaf_constraints_inverts_quality_size_for_shared_leaves():
    """The DP's (amin, amax) must be the exact FAIL_THRESHOLD inversion of
    quality_size -- INCLUDING its k-scaling for a shared leaf.

    quality_size centres the gaussian on k*target with sigma*k for a leaf
    holding k same-code rooms. leaf_constraints ignored that, which is why
    `eligible` excluded leaf_sharing outright -- and leaf_sharing defaults True
    in driver.search, so the DP never fired on a real run.
    """
    from homemaker_layout import geometry

    fit, root = _shared_seed()
    shared = [lf for lf in root.leaves() if (getattr(lf, "share", 1) or 1) > 1]
    assert shared, "seed carries no shared leaves -- test would be vacuous"

    orig_area = geometry.area
    try:
        for lf in shared:
            b = shapecurve.leaf_constraints(fit, lf)
            for bound in (b.amin, b.amax):
                geometry.area = lambda _n, _a=bound: _a
                assert fit.quality_size(lf) == pytest.approx(
                    fit_mod.FAIL_THRESHOLD, abs=1e-9), (
                    f"leaf {lf.id} (share={lf.share}): DP bound {bound} is not "
                    f"on the fail threshold of quality_size")
    finally:
        geometry.area = orig_area


@pytest.mark.skipif(not Path("examples/harbor-house").is_dir(),
                    reason="harbor-house not available")
def test_unscaled_bounds_would_reject_every_shared_leaf():
    """Guard the reason `eligible` could not simply be relaxed.

    Without the k-scaling, a shared leaf's real area sits far outside the
    single-room bounds, so the DP would call a feasible topology infeasible --
    a false negative that prunes good topologies and misdirects the NM
    warm-start. Measured: 100% of shared leaves, 6 seeds.
    """
    from homemaker_layout import geometry

    fit, root = _shared_seed()
    K = shapecurve._K
    checked = would_reject = 0
    for lf in root.leaves():
        if (getattr(lf, "share", 1) or 1) <= 1 or lf.type not in (fit._programme or {}):
            continue
        checked += 1
        area = geometry.area(lf)
        t, sg = fit.get_space_params(lf.type, "size")[:2]
        b = shapecurve.leaf_constraints(fit, lf)
        assert b.amin <= area <= b.amax, "scaled bounds should accept the real area"
        if not (max(0.0, t - K * sg) <= area <= t + K * sg):
            would_reject += 1
    assert checked, "no shared leaves -- test would be vacuous"
    assert would_reject == checked, (
        f"expected the unscaled bounds to reject every shared leaf; "
        f"{would_reject}/{checked}")


def test_eligible_admits_sharing_but_still_excludes_superpose():
    """superpose is excluded for a DIFFERENT reason than the others: it does
    not rescale a target, it changes which TYPE is scored, and the collapse
    happens after the DP has read leaf.type."""
    assert shapecurve.eligible(None, leaf_sharing=True)
    assert shapecurve.eligible(None, max_share=3)
    assert shapecurve.eligible(None, multi_use=True)
    assert shapecurve.eligible(None, leaf_sharing=True, max_share=4, multi_use=True)
    assert not shapecurve.eligible(None, superpose=True)
    assert not shapecurve.eligible(None, leaf_sharing=True, superpose=True)

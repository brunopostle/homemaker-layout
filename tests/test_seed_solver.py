"""`--seed-solver`: constructed seeds sized by the ratio solver before their
first evaluation (`homemaker-py-8b2u.21`, DESIGN.md §39.118).

Default OFF, so the first thing held is that off is off. Then the part the
container measurement did not cover and the search needs: a SHARED leaf stands
for several rooms, and the solver must aim it at that many rooms' area.
"""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, driver, evolve, geometry, operators, programme, solver

REPO = Path(__file__).resolve().parent.parent
HARBOR = REPO / "examples" / "harbor-house"

pytestmark = pytest.mark.skipif(not HARBOR.is_dir(), reason="examples absent")


@pytest.fixture(autouse=True)
def orthogonal(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def test_the_switch_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv("HOMEMAKER_SEED_SOLVER", raising=False)
    assert evolve._parse_args(["init.dom"]).seed_solver is False
    assert evolve._parse_args(["init.dom", "--seed-solver"]).seed_solver is True
    monkeypatch.setenv("HOMEMAKER_SEED_SOLVER", "1")
    assert evolve._parse_args(["init.dom"]).seed_solver is True


def _strip(width, *cells):
    """A plot `width` x 10 cut into strips left to right, one per `(type,
    share)`; every cut starts at 0.5 of what is left."""
    def build(rest):
        (t, k), tail = rest[0], rest[1:]
        leaf = dom.Node(type=t, share=k, share_type=t if k > 1 else None)
        if not tail:
            return leaf
        return dom.Node(division=[0.5, 0.5], left=leaf, right=build(tail))
    root = build(list(cells))
    root.node = [[0.0, 0.0], [float(width), 0.0], [float(width), 10.0], [0.0, 10.0]]
    root.node_file = [list(p) for p in root.node]
    root.height, root.elevation, root.wall_inner, root.wall_outer = 3.0, 0.0, 0.08, 0.0
    root.perimeter = {}
    dom.link(root)
    return root


def _areas(root):
    geometry.clear_cache()
    return [geometry.area(lf) for lf in root.leaves()]


def test_a_shared_leaf_is_owed_as_many_rooms_as_it_stands_for():
    """Three `r` rooms of 10 m2 in one shared cell, beside one `r` on its own,
    on a plot of exactly 40 m2: the shared cell is owed three times the
    other's area."""
    reqs = programme.load_programme_dir(str(HARBOR))
    assert reqs["r"].size == 10.0
    root = _strip(4, ("r", 3), ("r", 1))
    solver.solve_ratios(root, reqs, strip=False, weight_width=0.0,
                        weight_proportion=0.0, max_nfev=200)
    big, small = _areas(root)
    assert big / small == pytest.approx(3.0, rel=0.02)


def test_control_a_share_that_is_not_live_counts_as_one_room():
    """The same tree with the share stamped for a type the leaf no longer has
    -- a stale share, which the scorer ignores too -- is two equal rooms. If
    this were 3:1 the test above would be passing for the wrong reason."""
    reqs = programme.load_programme_dir(str(HARBOR))
    root = _strip(4, ("r", 3), ("r", 1))
    root.left.share_type = "n"
    solver.solve_ratios(root, reqs, strip=False, weight_width=0.0,
                        weight_proportion=0.0, max_nfev=200)
    big, small = _areas(root)
    assert big / small == pytest.approx(1.0, rel=0.02)


def _seed(rng_seed=0):
    reqs = programme.load_programme_dir(str(HARBOR))
    topo = operators.constructive_topology(
        dom.load(str(HARBOR / "init.dom")), reqs, np.random.default_rng(rng_seed),
        sorted(reqs) + ["C", "O"], min_storeys=2, leaf_sharing=True, leaf_share_factor=3)
    dom.link(topo)
    return topo, reqs


def test_solve_seed_moves_a_real_seed_towards_its_areas_and_keeps_its_tree():
    from homemaker_layout import genome

    topo, reqs = _seed()
    conf = driver._fitness_for(str(HARBOR), True, False, None, False, True, False)._conf

    def miss(root):
        """Mean relative miss of each room cell from the area it is owed."""
        geometry.clear_cache()
        out = []
        for lvl in dom.levels(root):
            for lf in lvl.leaves():
                if lf.type in reqs:
                    k = lf.share if lf.share > 1 and lf.share_type == lf.type else 1
                    want = reqs[lf.type].size * k
                    out.append(abs(geometry.area(lf) - want) / want)
        return sum(out) / len(out)

    before, sig = miss(topo), genome.signature(topo)
    assert any(lf.share > 1 for lvl in dom.levels(topo) for lf in lvl.leaves()), \
        "the seed has no shared leaf: this test is not testing what it says"
    solved = driver.solve_seed(copy.deepcopy(topo), reqs, conf)
    assert genome.signature(solved) == sig          # ratios only
    assert miss(solved) < 0.8 * before


def test_a_seed_the_solver_refuses_is_returned_as_built(monkeypatch):
    topo, reqs = _seed()
    from homemaker_layout import innerloop

    before = innerloop.ratio_map(topo)

    def boom(root, *a, **k):
        for b in solver.free_branches(root):       # half-done work, then failure
            b.division = [0.9, 0.9]
        raise RuntimeError("singular")

    monkeypatch.setattr(solver, "solve_ratios", boom)
    driver.solve_seed(topo, reqs, {})
    assert innerloop.ratio_map(topo) == before

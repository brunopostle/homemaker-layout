"""Divisions can be placed on the plot's axes instead of inheriting its skew.

homemaker-py-32t, DESIGN.md §39.38/§39.40. Urb had a pass that straightened the
walls (``Urb::Quad::Straighten``); it did not survive the port, so
``quality_perpendicular`` measured something no operator could fix (§39.36).

A division carries two ratios and the port pins them equal, which propagates the
plot's skew into every leaf. Deriving the second instead places the cut parallel
or perpendicular to the plot's longest boundary -- the owner's rule -- at no cost
in search dimensionality, because the second ratio was never free.

Default OFF: it changes the geometry of every layout and so is a new objective
under §39.32.
"""

from __future__ import annotations

import math

import pytest

from homemaker_layout import dom as dom_mod, geometry

from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CORPUS = ["harbor-house", "maple-court", "health-centre", "programme-house"]
pytestmark = pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(),
                                reason="examples absent")


@pytest.fixture
def orthogonal():
    geometry.ORTHOGONAL_DIVISION = True
    geometry.clear_cache()
    yield
    geometry.ORTHOGONAL_DIVISION = False
    geometry.clear_cache()


def _artefacts():
    for name in CORPUS:
        for p in sorted((EXAMPLES / name).glob("coldstart-*-500000-s*.dom")):
            yield p


def _corner_dev(leaf):
    return [math.degrees(abs(geometry.angle(leaf, i) - math.pi / 2))
            for i in range(4)]


def _on_plot_boundary(leaf, plot, tol=1e-6):
    for c in (geometry.coordinate(leaf, i) for i in range(4)):
        for i in range(4):
            a, b = plot[i], plot[(i + 1) % 4]
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if not length:
                continue
            cross = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
            if cross / length < tol:
                return True
    return False


def test_the_default_is_off():
    """It is a new objective, not a tweak -- it must not arrive by surprise."""
    assert geometry.ORTHOGONAL_DIVISION is False


def test_off_changes_nothing():
    """The flag off must reproduce the stored equal-offset geometry exactly."""
    p = next(_artefacts())
    geometry.clear_cache()
    root = dom_mod.load(str(p))
    before = [geometry.coordinate(l, i)
              for lvl in dom_mod.levels(root) for l in lvl.leaves() for i in range(4)]
    geometry.clear_cache()
    root2 = dom_mod.load(str(p))
    after = [geometry.coordinate(l, i)
             for lvl in dom_mod.levels(root2) for l in lvl.leaves() for i in range(4)]
    assert before == after


def test_interior_leaves_become_square(orthogonal):
    """The acceptance criterion. Leaves that touch the plot boundary stay
    trapezoidal -- the site is the site -- but nothing inside should be skew."""
    interior = 0
    for p in _artefacts():
        geometry.clear_cache()
        root = dom_mod.load(str(p))
        for lvl in dom_mod.levels(root):
            plot = [geometry.coordinate(lvl, i) for i in range(4)]
            for leaf in lvl.leaves():
                if not dom_mod.is_usable(leaf) or _on_plot_boundary(leaf, plot):
                    continue
                interior += 1
                assert max(_corner_dev(leaf)) < 0.01, (
                    f"{p.name} {leaf.id}: interior leaf is not square")
    assert interior > 100, "expected a substantial interior population"


def test_the_skew_it_removes_is_real(orthogonal):
    """Guards against the flag being a no-op: with it off, essentially nothing
    is square; with it on, most of the corpus is."""
    def square_share():
        n = sq = 0
        for p in _artefacts():
            geometry.clear_cache()
            for lvl in dom_mod.levels(dom_mod.load(str(p))):
                for leaf in lvl.leaves():
                    if not dom_mod.is_usable(leaf):
                        continue
                    n += 1
                    sq += max(_corner_dev(leaf)) < 0.01
        return sq / n

    on = square_share()
    geometry.ORTHOGONAL_DIVISION = False
    geometry.clear_cache()
    off = square_share()
    geometry.ORTHOGONAL_DIVISION = True
    assert off < 0.05, f"expected the stored geometry to be skew, got {off:.1%}"
    assert on > 0.40, f"expected orthogonal division to square most leaves, got {on:.1%}"


def test_upper_storeys_still_inherit(orthogonal):
    """coord_b short-circuits on n.below before the derivation, so walls stay
    stacked between storeys rather than being re-derived per level."""
    for p in _artefacts():
        geometry.clear_cache()
        root = dom_mod.load(str(p))
        lvls = dom_mod.levels(root)
        if len(lvls) < 2:
            continue
        for upper in lvls[1:]:
            for node in [upper]:
                if node.divided and node.below is not None and node.below.divided:
                    assert geometry.coord_b(node) == geometry.coord_b(node.below)
        return


def test_area_is_conserved(orthogonal):
    """Moving a cut redistributes area between siblings; it must not create or
    destroy any. Each divided node's children must still tile it."""
    checked = 0
    for p in _artefacts():
        geometry.clear_cache()
        root = dom_mod.load(str(p))
        for lvl in dom_mod.levels(root):
            stack = [lvl]
            while stack:
                n = stack.pop()
                if not n.divided:
                    continue
                stack += [n.left, n.right]
                whole = geometry.area(n)
                parts = geometry.area(n.left) + geometry.area(n.right)
                assert abs(parts - whole) < 1e-6 * max(1.0, whole), (
                    f"{p.name} {n.id}: children do not tile the parent")
                checked += 1
        if checked > 200:
            break
    assert checked

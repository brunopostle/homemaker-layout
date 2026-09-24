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


# --------------------------------------------------------------------------- #
# The scoring term the geometry is meant to replace (§39.41)
# --------------------------------------------------------------------------- #

def _conf(**overrides):
    from homemaker_layout.fitness import Fitness, load_config
    conf, cost = load_config(EXAMPLES / "harbor-house", overrides=overrides)
    return Fitness(conf, cost)


def _a_room():
    root = dom_mod.load(str(next(_artefacts())))
    return next(l for lvl in dom_mod.levels(root) for l in lvl.leaves()
                if l.type not in ("C", "O", "S"))


def test_perpendicular_is_retired_by_default():
    """Inverted at §39.50. It WAS scored by default while the exemption was
    opt-in; the factor is now retired in CONF_DEFAULTS, because the reason is
    general -- ORTHOGONAL_DIVISION supplies right angles by construction for
    any plot -- so a new programme must not silently inherit the question."""
    fit, room = _conf(), _a_room()
    assert not fit.factor_is_asked("perpendicular", room)
    assert fit.quality_perpendicular(room) == 1.0


def test_a_programme_can_still_ask_for_perpendicular():
    """Retired, not deleted. The key and the Gaussian remain, so a plot whose
    geometry does not supply right angles can put the question back."""
    fit = _conf(perpendicular_inside=0.3, perpendicular_outside=10.0)
    room = _a_room()
    assert fit.factor_is_asked("perpendicular", room)
    assert fit.quality_perpendicular(room) < 1.0


def test_a_null_sigma_exempts_the_factor():
    """`None` means "no requirement", the §39.22/§39.23 idiom -- set when the
    geometry supplies orthogonality by construction, so the objective does not
    also score it."""
    fit = _conf(perpendicular_inside=None, perpendicular_outside=None)
    room = _a_room()
    assert not fit.factor_is_asked("perpendicular", room)
    assert fit.quality_perpendicular(room) == 1.0


def test_the_exemption_is_read_with_a_null_aware_lookup():
    """`conf()` cannot tell an ABSENT key from one present and null, so reading
    the sigma with it would fall through to CONF_DEFAULTS and score the leaf
    anyway -- the §39.22 trap. `_generic_param` distinguishes them, and this
    asserts the distinction rather than the mechanism."""
    # Since §39.50 the DEFAULT is null, so the pair runs the other way round:
    # a sigma present in the config against the null default.
    asked = _conf(perpendicular_inside=0.3)
    nulled = _conf(perpendicular_inside=None)
    assert nulled.conf("perpendicular_inside") == _conf().conf("perpendicular_inside"), (
        "conf() is expected to be blind to absent-vs-null -- if it stops being, "
        "this test's premise is gone but the behaviour below is what matters")
    room = _a_room()
    assert asked.factor_is_asked("perpendicular", room)
    assert not nulled.factor_is_asked("perpendicular", room)


# --------------------------------------------------------------------------- #
# The cut must land INSIDE edge(3,2) (homemaker-py-w49, DESIGN.md §39.44)
# --------------------------------------------------------------------------- #

# A quad whose orthogonal cut leaves it. At a division of exactly 0.5 the
# intersection parameter is 1.0 -- the cut lands ON corner 2 -- and at 0.8 it is
# 1.6, well past it. Found by search, then pinned: the old code clamped both to
# 1.0 and returned c2 exactly, collapsing the child cell.
ESCAPING_QUAD = [[0.0, 0.0], [10.0, 0.0], [40.0, 4.0], [35.0, 4.0]]


def _level_root(corners, ratio):
    root = dom_mod.Node(rotation=0, division=[ratio, ratio],
                        node=[list(c) for c in corners], height=3.0,
                        elevation=0.0, wall_inner=0.0, wall_outer=0.0)
    root.left = dom_mod.Node(type="a", parent=root, position="l")
    root.right = dom_mod.Node(type="a", parent=root, position="r")
    return root


@pytest.mark.parametrize("ratio", [0.5, 0.8, 0.95])
def test_the_cut_never_lands_on_a_corner(orthogonal, ratio):
    """`_interp(c3, c2, 1.0)` IS c2. A cut placed there gives the child quad two
    coincident corners and a zero-length edge, which is what killed harbor-house
    seed 0 in the bootstrap (5 of 21092 cuts, §39.44)."""
    root = _level_root(ESCAPING_QUAD, ratio)
    geometry.clear_cache()
    b = geometry.coord_b(root)
    c2, c3 = geometry.coordinate(root, 2), geometry.coordinate(root, 3)
    assert b != c2 and b != c3, (
        f"the cut landed on a corner at division {ratio}: {b}")


def test_an_escaping_cut_falls_back_to_the_stored_ratio(orthogonal):
    """When the axis cannot be honoured inside the quad the answer is the one
    the parallel-edge branch above already gives -- keep the stored offset
    rather than invent one. Clamping instead mapped the whole half-line onto
    the single worst point in the range."""
    ratio = 0.8
    root = _level_root(ESCAPING_QUAD, ratio)
    geometry.clear_cache()
    b = geometry.coord_b(root)
    c2, c3 = geometry.coordinate(root, 2), geometry.coordinate(root, 3)
    want = [c3[0] * (1 - ratio) + c2[0] * ratio, c3[1] * (1 - ratio) + c2[1] * ratio]
    assert b == pytest.approx(want)


def test_the_escaping_quad_is_scorable_at_all(orthogonal):
    """The regression in one line: this used to raise ZeroDivisionError out of
    `quality_perpendicular` -> `geometry.angle`, and took the whole run down."""
    root = _level_root(ESCAPING_QUAD, 0.5)
    geometry.clear_cache()
    for leaf in root.leaves():
        for i in range(4):
            geometry.angle(leaf, i)  # must not raise


def test_angle_reports_no_angle_rather_than_raising():
    """Defence in depth: `_orthogonal_b` no longer manufactures a degenerate
    quad, but a pure-geometry primitive should not raise on a valid Node.

    0.0 and not pi/2: every caller is scoring closeness to a right angle, so
    pi/2 would give a collapsed cell a PERFECT score and invite the search to
    make more of them."""
    flat = dom_mod.Node(rotation=0, type="a",
                        node=[[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [10.0, 5.0]],
                        height=3.0, elevation=0.0, wall_inner=0.0, wall_outer=0.0)
    geometry.clear_cache()
    assert geometry.edge_length(flat, 2) == 0.0, "the fixture is not degenerate"
    assert geometry.angle(flat, 2) == 0.0
    assert geometry.angle(flat, 3) == 0.0


def test_a_healthy_quad_is_untouched_by_the_guard(orthogonal):
    """The fallback must be rare and the normal path unchanged: on the whole
    committed corpus not one cut leaves its quad."""
    escaped = 0
    for p in _artefacts():
        root = dom_mod.load(str(p))
        geometry.clear_cache()
        for n in [root] + [d for d in _divided(root)]:
            if n.divided:
                b = geometry.coord_b(n)
                c2, c3 = geometry.coordinate(n, 2), geometry.coordinate(n, 3)
                if b == c2 or b == c3:
                    escaped += 1
    assert escaped == 0, f"{escaped} corpus cuts land on a corner"


def _divided(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        for child in (n.left, n.right, n.above):
            if child is not None:
                stack.append(child)

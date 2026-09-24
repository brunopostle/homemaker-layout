"""A room's width is fixed by its area and aspect, so it is not scored (§39.37).

Owner's ruling on homemaker-py-2f1. For any leaf, area = width^2 * aspect, so
two of the three fix the third; scoring all three was three Gaussians on two
degrees of freedom. Size is the client's brief and proportion is A Pattern
Language 191; width had no independent provenance on rooms, and
``get_space_params`` already derives an undeclared one as
``(size/proportion)**0.5``.

Rooms only -- circulation and outside keep theirs, because for those classes
size and proportion are deliberately absent (§39.22/§39.23) or inert, leaving
width as the only shape control.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from homemaker_layout import dom as dom_mod, geometry, shapecurve
from homemaker_layout.fitness import CONF_DEFAULTS, Fitness, load_config

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CORPUS = ["harbor-house", "maple-court", "health-centre", "programme-house"]
pytestmark = pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(),
                                reason="examples absent")


def _leaves(root):
    return [l for lvl in dom_mod.levels(root) for l in lvl.leaves()]


def _klass(leaf):
    if leaf.type in dom_mod.GENERIC_OUTSIDE:
        return "outside"
    return "circulation" if leaf.type == "C" else "room"


def test_the_default_is_no_room_width_requirement():
    assert CONF_DEFAULTS["width_inside"] is None


@pytest.mark.parametrize("name", CORPUS)
def test_rooms_are_width_exempt_but_circulation_and_outside_are_not(name):
    d = EXAMPLES / name
    conf, cost = load_config(d)
    fit = Fitness(conf, cost)
    seen = set()
    for p in sorted(d.glob("coldstart-*-500000-s*.dom")):
        for leaf in _leaves(dom_mod.load(str(p))):
            k = _klass(leaf)
            seen.add(k)
            if k == "room":
                assert fit.quality_width(leaf) == 1.0, (
                    f"{p.name} {leaf.id}: a room's width must not be scored")
    assert "room" in seen


@pytest.mark.parametrize("name", CORPUS)
def test_the_shape_curve_does_not_filter_on_a_width_it_no_longer_scores(name):
    """leaf_constraints exists to predict the objective; a stricter DP bound
    than the scorer's is the drift its own docstring warns about."""
    d = EXAMPLES / name
    conf, cost = load_config(d)
    fit = Fitness(conf, cost)
    checked = 0
    for p in sorted(d.glob("coldstart-*-500000-s*.dom")):
        for leaf in _leaves(dom_mod.load(str(p))):
            wmin = shapecurve.leaf_constraints(fit, leaf).wmin
            if _klass(leaf) == "room":
                assert wmin == 0.0, f"{p.name} {leaf.id}: DP still bounds width"
                checked += 1
    assert checked


def test_area_is_determined_by_width_and_aspect():
    """The empirical basis for the ruling, on the corpus rather than in theory."""
    worst = 0.0
    n = 0
    for name in CORPUS:
        d = EXAMPLES / name
        for p in sorted(d.glob("coldstart-*-500000-s*.dom")):
            for leaf in _leaves(dom_mod.load(str(p))):
                if not dom_mod.is_usable(leaf):
                    continue
                a = geometry.area(leaf)
                w = geometry.length_narrowest(leaf)
                r = geometry.aspect(leaf)
                if min(a, w, r) <= 0:
                    continue
                worst = max(worst, abs((w * w * r) / a - 1.0))
                n += 1
    assert n > 400, "expected the whole corpus"
    assert worst < 0.10, (
        f"area = width^2 * aspect should hold to ~5%; worst was {worst:.3%}")


@pytest.mark.parametrize("name", CORPUS)
def test_restoring_the_parameter_restores_the_old_behaviour(name):
    """The ruling is a config value, not a deletion: it must be revertable, and
    turning it back on must only ever ADD width fails, never change anything
    else."""
    d = EXAMPLES / name
    conf_off, cost = load_config(d)
    conf_on, _ = load_config(d, overrides={"width_inside": [4.0, 1.0]})
    for p in sorted(d.glob("coldstart-*-500000-s*.dom")):
        root = dom_mod.load(str(p))
        _, f_off = Fitness(conf_off, cost).score_with_fails(copy.deepcopy(root))
        _, f_on = Fitness(conf_on, cost).score_with_fails(copy.deepcopy(root))
        gained = set(f_on) - set(f_off)
        assert not (set(f_off) - set(f_on)), (
            f"{p.name}: restoring the width requirement removed a failure")
        # Two shapes, both of them a width fail. A leaf that is too narrow says
        # "<id> width"; a MISSING required room says "missing <code>: would need
        # width check", because the cascade bills a missing room exactly the
        # checks a present one faces (§38.12, homemaker-py-s34 -- the test
        # below pins that rule). Accepting only the first shape was fine until
        # the corpus first contained a missing required room, which the
        # 1138ff1+orth sweep supplied in maple-court s1.
        def is_width_fail(f: str) -> bool:
            return f.endswith(" width") or f.endswith(": would need width check")

        assert all(is_width_fail(f) for f in gained), (
            f"{p.name}: restoring it changed something other than width: "
            f"{sorted(f for f in gained if not is_width_fail(f))}")


def test_the_missing_room_cascade_bills_only_checks_a_present_room_faces():
    """§38.12: missing and present rooms must be penalised on the same terms.
    Before homemaker-py-s34 the cascade hardcoded ("size","width","proportion"),
    so once §39.37 stopped asking rooms for a width a missing room was still
    billed for one -- exactly the asymmetry §38.12 exists to prevent."""
    d = EXAMPLES / "harbor-house"
    conf, cost = load_config(d)
    fit = Fitness(conf, cost)
    probe = dom_mod.Node(type="__room_probe__")
    asked = {c for c in ("size", "width", "proportion")
             if fit.factor_is_asked(c, probe)}
    assert asked == {"size", "proportion"}, asked

    # a layout with a missing room, so the cascade actually fires
    root = dom_mod.load(str(next(d.glob("coldstart-*-500000-s0.dom"))))
    for leaf in _leaves(root):
        if _klass(leaf) == "room":
            leaf.type = "C"          # wipe the rooms out
            leaf.share, leaf.share_type, leaf.co_type = 1, None, None
    _, fails = Fitness(conf, cost).score_with_fails(root)
    placeholders = [f for f in fails if "would need" in f]
    assert placeholders, "expected the missing-room cascade to fire"
    assert not [f for f in placeholders if "width check" in f], (
        "a missing room is billed for a width check a present room never faces")


def test_the_collapse_counts_only_factors_it_actually_asks():
    """homemaker-py-s34: an exempt factor returns 1.0, indistinguishable from a
    perfect answer. Counting it adds _COLLAPSE_FAIL_W to every candidate for a
    check the scorer does not perform, so the collapse would optimise a relation
    the objective does not contain."""
    from homemaker_layout.fitness import FAIL_THRESHOLD

    d = EXAMPLES / "harbor-house"
    conf, cost = load_config(d)
    fit = Fitness(conf, cost)
    root = dom_mod.load(str(next(d.glob("coldstart-*-500000-s0.dom"))))
    prog = fit.programme() if hasattr(fit, "programme") else None
    room = next(l for l in _leaves(root) if _klass(l) == "room")
    # width is 1.0 for a room and therefore "passes" trivially; the collapse
    # must not bank that as an avoided fail
    assert fit.quality_width(room) == 1.0
    assert not fit.factor_is_asked("width", room)
    # and it must still be banked for circulation, where width IS asked
    circ = next((l for l in _leaves(root) if _klass(l) == "circulation"), None)
    if circ is not None:
        assert fit.factor_is_asked("width", circ)

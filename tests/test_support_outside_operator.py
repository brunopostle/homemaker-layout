"""``operators.mutate_support_outside`` (homemaker-py-e4r, DESIGN.md §39.53).

§39.53's A/B settled that ``level N no outside space`` is decided by what sits
UNDERNEATH a level's outdoor space, not by how many storeys there are, and that
no operator aimed at that relation. This is that operator, so what is asserted
here is the relation itself -- a level gains USABLE outdoor space, or a
stranded terrace becomes supported -- rather than any particular edit.

Two guards get their own tests because both trade one fail for another and
neither is visible in a descriptor: building under a terrace must not strip the
last outdoor space from the level below, and no move may retype a level's only
circulation leaf.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, genome, geometry, operators
from homemaker_layout.dom import Node

CORPUS = Path(__file__).resolve().parent.parent / "examples" / "programme-house"
TYPES = ["k1", "l1", "b1", "b2", "t1", "C", "O"]
SEEDS = range(24)


def _link(ground: Node) -> Node:
    dom.link(ground)
    geometry.clear_cache()
    return ground


def _corners():
    return [[0, 0], [12, 0], [12, 8], [0, 8]]


def _level(elevation: float, left: Node, right: Node) -> Node:
    return Node(node=_corners(), height=3.0, elevation=elevation,
                division=[0.5, 0.5], rotation=0, left=left, right=right)


def _levels_without_outdoor(root: Node) -> list[int]:
    return [li for li, _ in operators._levels_without_outdoor(root)]


def _run(root: Node, seeds=SEEDS) -> list[tuple[Node, str]]:
    return [operators.mutate_support_outside(root, np.random.default_rng(s), TYPES)
            for s in seeds]


def _of_kind(results, kind):
    return [(c, d) for c, d in results if d.startswith(f"support_outside {kind}")]


# --------------------------------------------------------------------------- #
# place: the dominant case in the artefacts (7 of 9 §39.53 runs carrying the
# fail have a level with no outside leaf at all)
# --------------------------------------------------------------------------- #
def _no_outdoor_upstairs() -> Node:
    """Ground is ``k1`` | ``O``; upstairs is ``b1`` (over ``k1``, so supported)
    | ``C`` (over the yard). Only ``b1`` can carry a usable terrace."""
    ground = _level(0.0, Node(type="k1"), Node(type="O"))
    ground.above = _level(3.0, Node(type="b1"), Node(type="C"))
    return _link(ground)


def test_place_gives_an_outdoor_less_upper_level_usable_outdoor_space():
    root = _no_outdoor_upstairs()
    assert _levels_without_outdoor(root) == [1]

    results = _run(root)
    placed = _of_kind(results, "place")
    assert placed, "no place move was ever drawn"
    for child, _ in placed:
        assert _levels_without_outdoor(child) == []


def test_place_on_the_ground_floor_needs_no_support():
    """xhw armB seed 5 fails ``level 0 no outside space``. At level 0 every
    outside leaf is usable, so support is not a criterion there -- but a
    ``is_supported`` gate applied blindly would find no candidate at all,
    since nothing sits below the ground floor."""
    ground = _level(0.0, Node(type="k1"), Node(type="C"))
    ground.above = _level(3.0, Node(type="b1"), Node(type="O"))
    root = _link(ground)
    assert _levels_without_outdoor(root) == [0]

    placed = _of_kind(_run(root), "place")
    assert placed
    for child, _ in placed:
        assert _levels_without_outdoor(child) == []


def test_place_above_ground_only_lands_on_a_supported_leaf():
    """A terrace placed over the void below is a second stranded terrace, not
    a repair -- the whole point of §39.53."""
    ground = _level(0.0, Node(type="O"), Node(type="k1"))
    ground.above = _level(3.0, Node(type="b1"), Node(type="b2"))
    root = _link(ground)
    assert _levels_without_outdoor(root) == [1]

    placed = _of_kind(_run(root), "place")
    assert placed
    for child, desc in placed:
        upper = dom.levels(child)[1]
        new = [lf for lf in upper.leaves() if dom.is_outside(lf)]
        assert new, desc
        assert all(dom.is_usable(lf) for lf in new), desc


# --------------------------------------------------------------------------- #
# swap / underbuild: rescuing a terrace already stranded over a void
# --------------------------------------------------------------------------- #
def _stranded_over_void() -> Node:
    """Ground is ``O`` | ``k1``; upper is ``O`` (over the void) | ``b1``."""
    ground = _level(0.0, Node(type="O"), Node(type="k1"))
    ground.above = _level(3.0, Node(type="O"), Node(type="b1"))
    return _link(ground)


def test_the_fixture_really_is_stranded():
    root = _stranded_over_void()
    terrace = next(lf for lf in dom.levels(root)[1].leaves() if dom.is_outside(lf))
    assert not dom.is_supported(terrace)
    assert not dom.is_usable(terrace)
    assert operators._stranded_outside(root) == [(1, terrace)]


def test_swap_moves_the_terrace_onto_solid_floor():
    root = _stranded_over_void()
    swapped = _of_kind(_run(root), "swap")
    assert swapped, "no swap move was ever drawn"
    for child, desc in swapped:
        upper = dom.levels(child)[1]
        outs = [lf for lf in upper.leaves() if dom.is_outside(lf)]
        assert len(outs) == 1, desc
        assert dom.is_usable(outs[0]), desc
        # the room it exchanged with is still on the level, just relocated
        assert sorted(lf.type for lf in upper.leaves()) == ["O", "b1"]


def test_underbuild_encloses_the_void_under_the_terrace():
    """Ground keeps a second outdoor leaf, so the guard lets the move run."""
    ground = Node(node=_corners(), height=3.0, elevation=0.0,
                  division=[0.5, 0.5], rotation=0,
                  left=Node(type="O"),
                  right=Node(division=[0.5, 0.5], rotation=0,
                             left=Node(type="k1"), right=Node(type="O")))
    ground.above = _level(3.0, Node(type="O"), Node(type="b1"))
    root = _link(ground)

    built = _of_kind(_run(root), "underbuild")
    assert built, "no underbuild move was ever drawn"
    for child, desc in built:
        terrace = next(lf for lf in dom.levels(child)[1].leaves()
                       if dom.is_outside(lf))
        assert dom.is_supported(terrace), desc
        assert _levels_without_outdoor(child) == [], desc


def test_underbuild_refuses_to_strip_the_last_outdoor_space_below():
    """The ground floor's only courtyard IS the terrace's void. Enclosing it
    would move ``no outside space`` down one storey, not clear it."""
    root = _stranded_over_void()
    assert not _of_kind(_run(root), "underbuild")


# --------------------------------------------------------------------------- #
# invariants that hold whichever move is drawn
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("build", [_stranded_over_void, _no_outdoor_upstairs],
                         ids=["stranded", "no-outdoor-upstairs"])
def test_never_increases_the_number_of_levels_without_outdoor_space(build):
    root = build()
    before = len(_levels_without_outdoor(root))
    for child, desc in _run(root):
        assert len(_levels_without_outdoor(child)) <= before, desc


def test_never_retypes_a_levels_only_circulation_leaf():
    ground = _level(0.0, Node(type="C"), Node(type="k1"))
    ground.above = _level(3.0, Node(type="C"), Node(type="b1"))
    root = _link(ground)
    for child, desc in _run(root):
        for li, lvl in enumerate(dom.levels(child)):
            n_circ = sum(1 for lf in lvl.leaves() if dom.is_circulation(lf))
            assert n_circ >= 1, f"level {li} lost its last circulation: {desc}"


def test_noop_when_every_level_already_has_usable_outdoor_space():
    ground = _level(0.0, Node(type="k1"), Node(type="O"))
    ground.above = _level(3.0, Node(type="O"), Node(type="b1"))
    root = _link(ground)
    # upper `O` sits over `k1` -- supported, so nothing is stranded
    assert operators._stranded_outside(root) == []
    for _, desc in _run(root):
        assert desc == "support_outside noop"


def test_parent_is_never_mutated_in_place():
    root = _stranded_over_void()
    before = genome.encode(root)
    _run(root)
    assert genome.encode(root) == before


# --------------------------------------------------------------------------- #
# the committed artefacts the bead was written from
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not CORPUS.is_dir(), reason="corpus absent")
@pytest.mark.parametrize("name", [
    "coldstart-c836457+orth-500000-s0.dom",   # level 1 has no outside leaf
    "coldstart-c836457+orth-500000-s2.dom",   # level 1 has one, stranded
])
def test_clears_no_outside_space_on_a_committed_artefact(name):
    path = CORPUS / name
    if not path.is_file():
        pytest.skip(f"{name} absent")
    root = genome.decode(genome.encode(dom.load(str(path))))
    assert _levels_without_outdoor(root), f"{name} no longer reproduces the fail"

    cleared = [d for c, d in _run(root) if not _levels_without_outdoor(c)]
    assert cleared, f"{name}: no draw in {len(SEEDS)} cleared the level"

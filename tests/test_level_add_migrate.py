"""`mutate_level_add_migrate`'s contract (homemaker-py-v2k, DESIGN.md §39.71).

`mutate_level_add` duplicates the top storey EMPTY; this operator adds a storey
and moves rooms into it in one move. What it must not do is break any of the
vertical relations the objective checks while doing so, because each of them is a
HARD fail and each of them broke on the way to the version being tested:

* the stair: `graph.stack_corners_in_use` follows the EXACT id path and wants a
  leaf typed `"C"` on every level, so a new storey that types that address
  anything else costs the building its staircase (`too few stairs`);
* `covered outside above ground`: no indoor leaf may sit over a terrace;
* `force_roof_garden`: every level needs outdoor space it can actually use;
* the programme: no room may be lost in the move.
"""

from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, genome, geometry, operators, programme

CORPUS = Path(__file__).parent.parent / "examples" / "programme-house"
# the artefact `homemaker-py-xhw` was raised on: 2 storeys, and its one fail is
# `level 1 no outside space`
ARTEFACT = "coldstart-1138ff1+orth-500000-s0.dom"

pytestmark = pytest.mark.skipif(not (CORPUS / ARTEFACT).is_file(),
                                reason="Corpus not available")


def _parent():
    root = genome.decode(genome.encode(dom.load(str(CORPUS / ARTEFACT))))
    geometry.clear_cache()
    return root


def _reqs():
    return programme.load_programme_dir(str(CORPUS))


def _rooms(root):
    return sorted(lf.type for lvl in dom.levels(root) for lf in lvl.leaves()
                  if lf.type and not dom.is_generic(lf.type))


def _children(n=6):
    root, reqs = _parent(), _reqs()
    types = sorted(reqs) + ["C", "O"]
    out = []
    for seed in range(n):
        child, desc = operators.mutate_level_add_migrate(
            root, np.random.default_rng(seed), types, reqs=reqs)
        geometry.clear_cache()
        out.append((child, desc))
    return root, out


def test_adds_a_storey_and_keeps_every_room():
    root, children = _children()
    before = _rooms(root)
    for child, desc in children:
        assert "noop" not in desc, desc
        assert len(dom.levels(child)) == len(dom.levels(root)) + 1
        assert _rooms(child) == before, desc
        # and the rooms did not all stay downstairs
        top = dom.levels(child)[-1]
        assert any(lf.type and not dom.is_generic(lf.type) for lf in top.leaves())


def test_the_stair_still_reaches_the_top():
    _root, children = _children()
    for child, desc in children:
        lvls = dom.levels(child)
        path = operators._stair_path(lvls)
        assert path is not None, desc
        for lvl in lvls:
            node = lvl.by_id(path)
            assert node is not None and node.type == "C", f"{desc}: {path}"


def test_no_indoor_leaf_is_left_over_a_terrace():
    _root, children = _children()
    for child, desc in children:
        for lvl in dom.levels(child):
            for leaf in lvl.leaves():
                if dom.is_outside(leaf) and dom.is_usable(leaf):
                    assert not dom.is_covered(leaf), f"{desc}: {leaf.id}"


def test_every_level_keeps_usable_outdoor_space():
    _root, children = _children()
    for child, desc in children:
        for li, lvl in enumerate(dom.levels(child)):
            assert any(dom.is_outside(lf) and dom.is_usable(lf)
                       for lf in lvl.leaves()), f"{desc}: level {li}"


def test_noop_without_the_programme():
    root = _parent()
    child, desc = operators.mutate_level_add_migrate(
        root, np.random.default_rng(0), ["C", "O"])
    assert "noop" in desc
    assert len(dom.levels(child)) == len(dom.levels(root))


def test_it_clears_the_fail_the_hand_design_was_built_to_show():
    """The point of the operator, on the artefact the owner was reading.

    §39.70: the hand-built 3-storey layout scores 0.416206 with zero fails where
    this parent scores 0.206215 with `level 1 no outside space`. One draw of this
    operator has to reach a fail-free 3-storey layout, or the valley is still
    there.
    """
    from homemaker_layout.fitness import Fitness
    from homemaker_layout.fitness_cmd import load_config

    geometry.ORTHOGONAL_DIVISION = True     # the artefact's own geometry
    try:
        conf, cost = load_config(CORPUS)
        fit = Fitness(conf, cost)
        root, children = _children()
        geometry.clear_cache()
        p_score, p_fails = fit.score_with_fails(root)
        assert p_fails  # the parent is not clean
        best = None
        for child, _desc in children:
            geometry.clear_cache()
            score, fails = fit.score_with_fails(child)
            if not fails and (best is None or score > best):
                best = score
        assert best is not None, "no draw reached a fail-free layout"
        assert best > p_score
    finally:
        geometry.ORTHOGONAL_DIVISION = False
        geometry.clear_cache()

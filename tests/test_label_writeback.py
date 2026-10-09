"""The scorer's room labels, written back to the design it scored
(`homemaker-py-urzf.1`, DESIGN.md §39.120 finding 6, §39.130).

The search's scorer relabels cells to rooms before it counts anything, on its
own copy. An operator that reads labels was reading the labels a child was
bred with. `driver.LABEL_WRITEBACK` writes the scored labels back.
"""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, driver, geometry, graph, innerloop, operators

REPO = Path(__file__).resolve().parent.parent
PH = REPO / "examples" / "programme-house"
DESIGN = PH / "coldstart-1a24b6a+orth-500000-s0.dom"

pytestmark = pytest.mark.skipif(not DESIGN.exists(), reason="examples absent")


@pytest.fixture
def orth():
    was = geometry.ORTHOGONAL_DIVISION
    geometry.ORTHOGONAL_DIVISION = True
    geometry.clear_cache()
    yield
    geometry.ORTHOGONAL_DIVISION = was
    geometry.clear_cache()


def _mislabelled():
    """A finished design with one required room's label given away to another:
    by its stored labels a room is missing, and the scorer puts it back."""
    root = dom.load(str(DESIGN))
    dom.link(root)
    reqs = driver._reqs_for(str(PH))
    rooms = [lf for lf in dom.levels(root)[0].leaves() if lf.type in reqs]
    a, b = next((x, y) for x in rooms for y in rooms if x.type != y.type)
    a.type = b.type
    geometry.clear_cache()
    assert graph.check_space_counts(copy.deepcopy(root), reqs)[1]
    return root, reqs


def _evaluate(root, flag: bool, monkeypatch):
    monkeypatch.setattr(driver, "LABEL_WRITEBACK", flag)
    tree = copy.deepcopy(root)
    dom.link(tree)
    geometry.clear_cache()
    ind, _ = driver._evaluate(tree, str(PH), None, 30, {}, "t")
    return ind


def test_unasked_a_child_keeps_the_labels_it_was_bred_with(orth, monkeypatch):
    root, reqs = _mislabelled()
    ind = _evaluate(root, False, monkeypatch)
    assert graph.check_space_counts(copy.deepcopy(ind.root), reqs)[1], (
        "the stored tree no longer shows the room missing: the fixture is not the case")
    assert not any("missing" in f for f in ind.fails)        # ...and the scorer saw it present
    # which is the state in which place_missing cuts a cell nobody asked for
    _c, desc = operators.mutate_place_missing(ind.root, np.random.default_rng(0),
                                              sorted(reqs), reqs=reqs)
    assert "noop" not in desc


def test_asked_the_stored_labels_are_the_scored_ones_and_the_score_is_the_same(orth, monkeypatch):
    root, reqs = _mislabelled()
    bred = _evaluate(root, False, monkeypatch)
    scored = _evaluate(root, True, monkeypatch)
    assert scored.fitness == bred.fitness and scored.fails == bred.fails
    assert not graph.check_space_counts(copy.deepcopy(scored.root), reqs)[1]
    # a fixed point: relabelling what was written back changes nothing
    fit = driver._fitness_for(str(PH))
    assert driver.write_labels_back(copy.deepcopy(scored.root), fit) == 0
    # and place_missing now declines, as its weight assumes it does
    _c, desc = operators.mutate_place_missing(scored.root, np.random.default_rng(0),
                                              sorted(reqs), reqs=reqs)
    assert "noop" in desc
    # the ratios are untouched by it
    assert innerloop.ratio_map(scored.root) == innerloop.ratio_map(bred.root)

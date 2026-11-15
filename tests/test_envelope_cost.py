"""Roof, slab and corners in the cost, and the enclosed-outdoor fail (owner's
rulings, DESIGN.md §39.229-§39.231, `homemaker-py-5fje.20`, `5fje.21`).

A corner of a storey's indoor outline costs one metre of exterior wall over
the storey's height; indoor area with nothing indoor above it costs a roof;
the ground storey's indoor area costs a slab. A ground-floor outdoor cell with
building over it, no outdoor neighbour and no open plot side is "not an
outside space" and fails. Each test carries the case that must NOT fire.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from homemaker_layout import dom, fitness, geometry

REPO = Path(__file__).resolve().parent.parent
CLEAN9 = REPO / "experiments/results/halving-maple-clean/final-clean-9.dom"


def _rect(x0, y0, x1, y1):
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _corners(g):
    return sum(fitness._ring_corners(r.coords)
               for p in getattr(g, "geoms", [g]) for r in (p.exterior, *p.interiors))


def test_seams_are_not_corners_and_an_l_has_six():
    two = fitness.union_cells([_rect(0, 0, 5, 10), _rect(5, 0, 10, 10)])
    assert _corners(two) == 4                     # the seam at x = 5 is no corner
    ell = fitness.union_cells([_rect(0, 0, 4, 10), _rect(4, 0, 10, 4)])
    assert _corners(ell) == 6                     # control: a real jog is two corners


def test_a_court_counts_its_own_corners():
    ring = fitness.union_cells([_rect(0, 0, 12, 4), _rect(0, 8, 12, 12),
                                _rect(0, 4, 4, 8), _rect(8, 4, 12, 8)])
    assert ring.area == pytest.approx(128.0)
    assert _corners(ring) == 8


def test_cells_a_hair_apart_on_a_skew_wall_are_one_outline():
    """Two cells whose shared skew wall is 1e-7 m apart: one piece, four
    corners, and the area the cells add up to."""
    a = Polygon([(0, 0), (10, 1), (9, 6), (-1, 5)])
    b = Polygon([(10, 1 + 1e-7), (20, 2), (19, 7), (9, 6 + 1e-7)])
    u = fitness.union_cells([a, b])
    assert u.geom_type == "Polygon"
    assert u.area == pytest.approx(a.area + b.area, abs=1e-4)
    assert _corners(u) == 4


@pytest.fixture(scope="module")
def maple():
    if not CLEAN9.is_file():
        pytest.skip("no CLEAN9")
    sys.path.insert(0, str(REPO / "experiments"))
    spec = importlib.util.spec_from_file_location(
        "diag_roof", REPO / "experiments" / "diag_5fje20_roof_corners.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _score(maple, edit=None):
    prog, fit, _ = maple.rc.Programmes()(CLEAN9, "maple-court")
    root = dom.load(str(CLEAN9))
    dom.link(root)
    if edit is not None:
        edit(root)
        dom.link(root)
    geometry.clear_cache()
    return fit.score_with_fails(root)


def test_enclosed_outdoor_cell_fails(maple):
    _, base = _score(maple)
    assert not any("enclosed outside" in f for f in base)        # control
    _, walled = _score(maple, maple._ground_cover)
    assert sum("enclosed outside" in f for f in walled) == 1


def test_a_covered_yard_open_to_another_yard_does_not_fail(maple):
    """A room over a yard cell with its other sides still open is a loggia,
    not a carriage arch."""
    _, f = _score(maple, maple._top_room_over_yard)
    assert not any("enclosed outside" in x for x in f)


def test_zero_rates_reproduce_the_old_cost(maple, monkeypatch):
    """The three terms are all the change: priced at zero, the envelope adds
    nothing, and priced at the defaults it adds what envelope_cost says."""
    prog, fit, _ = maple.rc.Programmes()(CLEAN9, "maple-court")
    root = dom.load(str(CLEAN9))
    dom.link(root)
    geometry.clear_cache()
    fit.score_with_fails(root)
    lvls = dom.levels(root)
    assert fit.envelope_cost(lvls) > 0
    for k in ("roof", "slab", "corner"):
        monkeypatch.setitem(fitness.COST_DEFAULTS, k, 0.0)
    assert fit.envelope_cost(lvls) == 0.0

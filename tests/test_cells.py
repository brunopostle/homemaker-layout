"""Native rectangle-frame geometry (`homemaker-py-8b2u.4`, the core).

Two halves. On everything the present geometry CAN draw -- every tracked
orthogonal design -- `cells.build` must draw the same cells; that is the gate
for moving the scorer onto it. On what the present geometry cannot draw --
polygon plots, status vertices, a frame of the file's own, empty and odd
cells -- it is checked against shapes worked out by hand.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest
import yaml

from homemaker_layout import cells, dom, geometry

REPO = Path(__file__).resolve().parent.parent
DIAG = REPO / "experiments" / "diag_8b2u2_roundtrip.py"


def _doc(plot, tree, **over) -> dict:
    d = {"format": "homemaker-dom", "version": 2, "frame": {"u": [1.0, 0.0]},
         "plot": plot, "wall_outer": 0.0,
         "storeys": [{"elevation": 0.0, "height": 3.0, "tree": tree}]}
    d.update(over)
    return d


def _bbox(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return tuple(round(x, 9) for x in (min(xs), max(xs), min(ys), max(ys)))


SQUARE = [[0, 0], [10, 0], [10, 10], [0, 10]]
HALVES = {"cut": "v", "at": 0.5, "low": {"cell": "a"}, "high": {"cell": "b"}}


# --------------------------------------------------------------------------- #
# what the v1 tree cannot hold
# --------------------------------------------------------------------------- #
def test_a_cut_is_a_line_across_the_frame_rectangle():
    lay = cells.build(_doc(SQUARE, {
        "cut": "v", "at": 0.3, "low": {"cell": "a"},
        "high": {"cut": "u", "at": 0.6, "low": {"cell": "b"}, "high": {"cell": "c"}}}))
    got = {c.type: (_bbox(c.polygon), c.path) for c in lay.cells()}
    assert got == {"a": ((0, 3, 0, 10), "l"), "b": ((3, 10, 0, 6), "hl"),
                   "c": ((3, 10, 6, 10), "hh")}
    assert sum(c.area for c in lay.cells()) == pytest.approx(100.0)


def test_the_wall_inset_moves_every_side_and_keeps_a_status_vertex():
    """A side that is street for 6 m and party wall after is two plot edges
    with a collinear vertex between them. It has to survive the inset, and the
    cell cropped against it has to carry it -- with a shape score of 1."""
    plot = [[0, 0], [6, 0], [10, 0], [10, 10], [0, 10]]
    lay = cells.build(_doc(plot, {"cell": "a"}, wall_outer=0.25,
                           perimeter=["street", "party", None, None, None]))
    assert [[round(c, 9) for c in p] for p in lay.inner] == [
        [0.25, 0.25], [6.0, 0.25], [9.75, 0.25], [9.75, 9.75], [0.25, 9.75]]
    (cell,) = lay.cells()
    assert len(cell.polygon) == 5 and len(cells.corners(cell.polygon)) == 4
    assert cells.usable_fraction(cell.polygon, lay.u, lay.v) == pytest.approx(1.0)
    sides = cells.edge_sides(cell, lay)
    assert sorted(s for s in sides) == [0, 1, 2, 3, 4]
    assert [lay.perimeter[s] for s in sides].count("street") == 1


def test_a_cell_outside_the_plot_is_empty_and_one_across_its_edge_is_odd():
    """A plot whose left side leans in. Above the first cut, the left of the
    frame is outside the plot altogether, and the next cell along is a
    triangle-cornered quad."""
    leaning = [[0, 0], [20, 0], [20, 10], [12, 10]]
    lay = cells.build(_doc(leaning, {
        "cut": "u", "at": 0.5, "low": {"cell": "ground"},
        "high": {"cut": "v", "at": 0.25, "low": {"cell": "gone"},
                 "high": {"cut": "v", "at": 0.5,
                          "low": {"cell": "wedge"}, "high": {"cell": "room"}}}}))
    by = {c.type: c for c in lay.cells()}
    assert by["gone"].empty and by["gone"].polygon == []
    assert not by["wedge"].empty and len(by["wedge"].polygon) in (3, 4, 5)
    assert cells.usable_fraction(by["wedge"].polygon) < 0.85
    assert cells.usable_fraction(by["room"].polygon) == pytest.approx(1.0)
    assert sum(c.area for c in lay.cells()) == pytest.approx(cells.area(leaning))


def test_an_l_shaped_plot_leaves_its_notch_empty():
    ell = [[0, 0], [10, 0], [10, 4], [4, 4], [4, 10], [0, 10]]
    lay = cells.build(_doc(ell, {
        "cut": "v", "at": 0.4,
        "low": {"cell": "stem"},
        "high": {"cut": "u", "at": 0.4, "low": {"cell": "foot"}, "high": {"cell": "notch"}}}))
    by = {c.type: c for c in lay.cells()}
    assert by["notch"].empty
    assert by["stem"].area == pytest.approx(40.0) and by["foot"].area == pytest.approx(24.0)
    inner = cells.inset(ell, 0.25)
    assert cells.area(inner) == pytest.approx(64.0 - 0.25 * 40 + 4 * 0.0625)


def test_the_frame_is_the_files_own():
    """A square plot standing on its corner, with the frame along its sides:
    the cells are the same halves, turned. Today's reader would refuse any
    frame but the one it derives."""
    r = math.sqrt(0.5)
    diamond = [[0, 0], [10 * r, 10 * r], [0, 20 * r], [-10 * r, 10 * r]]
    lay = cells.build(_doc(diamond, HALVES, frame={"u": [r, r]}))
    assert [c.area for c in lay.cells()] == pytest.approx([50.0, 50.0])
    assert all(cells.usable_fraction(c.polygon, lay.u, lay.v) == pytest.approx(1.0)
               for c in lay.cells())
    square_frame = cells.build(_doc(diamond, HALVES))        # frame along x
    assert all(cells.usable_fraction(c.polygon) < 0.6 for c in square_frame.cells())


def test_an_upper_storey_inherits_cuts_by_path_and_may_add_its_own():
    doc = _doc(SQUARE, HALVES)
    doc["storeys"].append({"elevation": 3.0, "height": 3.0, "tree": {
        "low": {"cut": "u", "at": 0.5, "low": {"cell": "c"}, "high": {"cell": "d"}},
        "high": {"cell": "e"}}})
    up = {c.type: _bbox(c.polygon) for c in cells.build(doc).storeys[1]}
    assert up == {"c": (0, 5, 0, 5), "d": (0, 5, 5, 10), "e": (5, 10, 0, 10)}
    doc["storeys"][1]["tree"]["cut"] = "v"
    with pytest.raises(cells.CellsError, match="inherits"):
        cells.build(doc)


@pytest.mark.parametrize("over, says", [
    ({"plot": [[0, 0], [0, 10], [10, 10], [10, 0]]}, "anticlockwise"),
    ({"frame": {}}, "frame.u"),
    ({"version": 3}, "version 2"),
    ({"blocks": []}, "blocks"),
    ({"perimeter": [None]}, "one entry per plot edge"),
])
def test_what_it_cannot_draw_it_refuses(over, says):
    doc = _doc(SQUARE, HALVES)
    doc.update(over)
    with pytest.raises(cells.CellsError, match=says):
        cells.build(doc)


# --------------------------------------------------------------------------- #
# the shape score (DESIGN.md §39.90's table, and the owner's thresholds)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name, poly, want", [
    ("rectangle", [[0, 0], [4, 0], [4, 3], [0, 3]], 1.00),
    ("rectangle + status vertex", [[0, 0], [2, 0], [4, 0], [4, 3], [0, 3]], 1.00),
    ("0.3 m clipped corner", [[0, 0], [4, 0], [4, 2.7], [3.7, 3], [0, 3]], 0.93),
    ("2 m clipped corner", [[0, 0], [4, 0], [4, 1], [2, 3], [0, 3]], 0.62),
    ("right triangle", [[0, 0], [4, 0], [0, 3]], 0.50),
])
def test_usable_fraction_ranks_shapes_as_the_owner_described(name, poly, want):
    assert cells.usable_fraction(poly) == pytest.approx(want, abs=0.02), name


def test_shape_quality_thresholds_are_the_ruling():
    assert cells.shape_quality(1.0) == cells.shape_quality(0.85) == 1.0
    assert cells.shape_quality(0.70) == pytest.approx(0.1)        # the fail line
    assert 0.1 < cells.shape_quality(0.78) < 1.0
    assert cells.shape_quality(0.50) < 1e-4


# --------------------------------------------------------------------------- #
# the gate: today's geometry, cell for cell
# --------------------------------------------------------------------------- #
def _diag():
    spec = importlib.util.spec_from_file_location("_rt", DIAG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _unmatched(root, lay, tol=1e-6) -> int:
    """Leaves of the v1 tree with no cell of the same storey, type and
    corners, plus cells left over."""
    rest = [(c.storey, c.type, cells.corners(c.polygon)) for c in lay.cells()]
    bad = 0
    for li, lvl in enumerate(dom.levels(root)):
        for leaf in lvl.leaves():
            quad = [geometry.coordinate(leaf, i) for i in range(4)]
            hit = next((x for x in rest if x[0] == li and x[1] == leaf.type
                        and len(x[2]) == 4
                        and all(min(math.dist(p, q) for q in quad) <= tol for p in x[2])
                        and all(min(math.dist(p, q) for q in x[2]) <= tol for p in quad)),
                       None)
            if hit is None:
                bad += 1
            else:
                rest.remove(hit)
    return bad + len(rest)


@pytest.mark.skipif(not (REPO / "examples" / "maple-court").is_dir(),
                    reason="examples absent")
def test_every_orthogonal_artefact_is_drawn_as_todays_geometry_draws_it(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    rt = _diag()
    n = 0
    docked: dict = {}
    for p, _ in rt.corpus():
        root = dom.load(str(p))
        lay = cells.build(yaml.safe_load(dom.dumps(root, version=2)))
        assert _unmatched(root, lay) == 0, p
        for c in lay.cells():
            n += 1
            assert not c.empty
            if cells.usable_fraction(c.polygon, lay.u, lay.v) < cells.SHAPE_FULL:
                key = p.name.split("-500000")[0] if "coldstart" in p.name else p.parent.name
                docked[key] = docked.get(key, 0) + 1
        geometry.clear_cache()
    assert n > 3500
    # §39.90 calibrated the shape score so that "every committed cell" keeps
    # full credit. That was measured on one corpus. Over all of them six cells
    # of 3,879 fall short (§39.99), none in the three newest coldstart corpora
    # -- so the shape score is NOT score-neutral on c836457+orth or on two e4r
    # artefacts, and stage 1b's gate has to say which corpora it means.
    assert docked == {"coldstart-c836457+orth": 4, "e4r": 1, "e4r-tiers": 1}


@pytest.mark.skipif(not (REPO / "examples" / "maple-court").is_dir(),
                    reason="examples absent")
def test_control_a_moved_cut_is_not_todays_geometry(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    p, _ = _diag().corpus()[0]
    root = dom.load(str(p))
    doc = yaml.safe_load(dom.dumps(root, version=2))
    doc["storeys"][0]["tree"]["at"] += 1e-4
    assert _unmatched(root, cells.build(doc)) > 0


# --------------------------------------------------------------------------- #
# shared walls: the adjacency graph, natively
# --------------------------------------------------------------------------- #
def test_cells_that_only_meet_end_to_end_share_no_wall():
    """`homemaker-py-khgi` as geometry: two cells along one line, touching at a
    point, share nothing; two side by side share their common stretch."""
    a = [[0, 0], [4, 0], [4, 3], [0, 3]]
    assert cells.shared_wall(a, [[4, 3], [8, 3], [8, 6], [4, 6]])[0] == 0.0     # corner
    width, seg = cells.shared_wall(a, [[4, 1], [8, 1], [8, 5], [4, 5]])
    assert width == pytest.approx(2.0)
    assert sorted(seg) == [[4.0, 1.0], [4.0, 3.0]]


def test_a_wall_narrower_than_a_door_is_not_an_adjacency():
    lay = cells.build(_doc(SQUARE, {
        "cut": "v", "at": 0.5,
        "low": {"cut": "u", "at": 0.9, "low": {"cell": "a"}, "high": {"cell": "b"}},
        "high": {"cut": "u", "at": 0.05, "low": {"cell": "c"}, "high": {"cell": "d"}}}))
    names = [c.type for c in lay.storeys[0]]
    pairs = {frozenset((names[i], names[j])): round(w, 6)
             for i, j, w, _ in cells.adjacency(lay.storeys[0])}
    assert pairs == {frozenset("ab"): 5.0, frozenset("cd"): 5.0,
                     frozenset("ad"): 8.5}          # a|c share 0.5 m, b|d 1.0 m


@pytest.mark.skipif(not (REPO / "examples" / "maple-court").is_dir(),
                    reason="examples absent")
def test_the_native_adjacency_graph_is_todays_graph(monkeypatch):
    """The second half of the gate: every wall `geometry.leaf_graph` finds
    between two leaves, the native cells find between the same two, the same
    width -- and no others. 6,517 of them (DESIGN.md §39.101)."""
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    spec = importlib.util.spec_from_file_location(
        "_m", REPO / "experiments" / "diag_8b2u4_measures.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    walls = 0
    for p, _ in _diag().corpus():
        root = dom.load(str(p))
        lay = cells.build(yaml.safe_load(dom.dumps(root, version=2)))
        pair = m.match(root, lay)
        index = {id(c): i for s in lay.storeys for i, c in enumerate(s)}
        for li, lvl in enumerate(dom.levels(root)):
            today = {frozenset((index[id(pair[a])], index[id(pair[b])])): d["width"]
                     for a, b, d in geometry.leaf_graph(lvl).edges(data=True)}
            native = {frozenset((i, j)): w
                      for i, j, w, _ in cells.adjacency(lay.storeys[li])}
            assert set(today) == set(native), p
            assert all(abs(today[k] - native[k]) < 1e-6 for k in today), p
            walls += len(today)
        geometry.clear_cache()
    assert walls > 6000


def test_usable_rectangle_gives_a_width_and_a_proportion_to_any_cell():
    assert cells.usable_rectangle([[0, 0], [4, 0], [4, 3], [0, 3]]) == pytest.approx((4, 3))
    # a 30 cm clipped corner: the shortest EDGE is 0.42 m, the room is still ~3 m wide
    du, dv = cells.usable_rectangle([[0, 0], [4, 0], [4, 2.7], [3.7, 3], [0, 3]])
    assert min(du, dv) > 2.6
    assert cells.usable_rectangle([]) == (0.0, 0.0)


# --------------------------------------------------------------------------- #
# the fitted rectangle is what the scorer calls width and proportion (§39.102)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("a, b, h", [(3.8, 4.0, 3.0), (2.5, 4.0, 3.0), (1.0, 4.0, 3.0),
                                     (0.2, 6.0, 2.0)])
def test_the_closed_form_for_a_boundary_cell_is_the_general_answer(a, b, h):
    """A rectangle cropped by one skew line takes a shortcut; the same cell
    with a redundant vertex on one side takes the general path. They must
    agree -- including when it tapers so far that the best rectangle lies
    under the slope rather than against the short side."""
    quad = [[0, 0], [b, 0], [a, h], [0, h]]
    general = cells.usable_rectangle([[0, 0], [b / 2, 0]] + quad[1:], grid=960)
    fast = cells.usable_rectangle(quad)
    assert fast[0] * fast[1] == pytest.approx(general[0] * general[1], rel=1e-4)
    if a >= b / 2:
        assert fast == pytest.approx((a, h))


def test_the_scorer_reads_width_and_proportion_from_the_fitted_rectangle(tmp_path, monkeypatch):
    from homemaker_layout import dom_v2

    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    # a plot whose right side leans: the right-hand cell is 3 m wide at the
    # bottom and 2 m at the top, 8 m deep
    doc = _doc([[0, 0], [10, 0], [9, 8], [0, 8]], {
        "cut": "v", "at": 0.7, "low": {"cell": "a"}, "high": {"cell": "b"}})
    root = dom_v2.from_document(doc)
    b = next(lf for lf in root.leaves() if lf.type == "b")
    assert geometry.usable_rectangle(b) == pytest.approx((2.0, 8.0))
    assert geometry.usable_width(b) == pytest.approx(2.0)
    assert geometry.usable_aspect(b) == pytest.approx(4.0)
    # today's quad formulas, kept for the search's heuristics, say otherwise
    assert geometry.aspect(b) == pytest.approx((8 + math.hypot(1, 8)) / 5, rel=1e-6)
    geometry.clear_cache()


def test_an_l_shaped_cell_is_not_given_its_bounding_box():
    """A cell wrapped round the inner corner of an L-shaped plot is an L. The
    convex routine would read its top and bottom and call it a full
    rectangle; its largest real rectangle is one arm."""
    ell = [[0, 0], [6, 0], [6, 2], [2, 2], [2, 5], [0, 5]]
    assert cells.area(ell) == pytest.approx(18.0)
    du, dv = cells.usable_rectangle(ell)
    assert du * dv == pytest.approx(12.0)                 # the 6 x 2 arm
    assert (du, dv) == pytest.approx((6.0, 2.0))
    assert cells.usable_fraction(ell) == pytest.approx(12 / 18)
    assert cells.shape_quality(cells.usable_fraction(ell)) < 0.1      # it fails
    # and a convex cell still takes the convex path to the same answer
    assert cells.usable_rectangle([[0, 0], [4, 0], [3, 2], [1, 2]]) == pytest.approx((2, 2))

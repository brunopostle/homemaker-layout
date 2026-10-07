"""`.dom` format version 2 (docs/dom-format-v2.md), stage 1a: `homemaker-py-8b2u.2`.

The file changes and the in-memory tree does not, so the tests are of three
kinds: the header is detected and anything unknown refused; a v2 document
builds the cells it describes; and every tracked orthogonal design survives
v1 -> v2 -> memory with its cells, and -- once two scorer behaviours that are
not geometry are neutralised (DESIGN.md §39.94) -- its score.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest
import yaml

from homemaker_layout import dom, dom_v2, geometry
from homemaker_layout.dom_v2 import DomFormatError

REPO = Path(__file__).resolve().parent.parent
DIAG = REPO / "experiments" / "diag_8b2u2_roundtrip.py"


@pytest.fixture(autouse=True)
def orthogonal(monkeypatch):
    """v2 IS the orthogonal convention; the suite's default has it off."""
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _doc(**over) -> dict:
    """A 10 x 8 m plot, two storeys. With the 0.25 m wall inset the frame is
    9.5 x 7.5: the ground floor is cut in half across u, and upstairs inherits
    that cut and divides its high half again."""
    d = {
        "format": "homemaker-dom", "version": 2,
        "frame": {"u": [1.0, 0.0]},
        "plot": [[0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [0.0, 8.0]],
        "perimeter": ["private", None, "street", None],
        "wall_inner": 0.08, "wall_outer": 0.25,
        "storeys": [
            {"elevation": 0.0, "height": 3.0,
             "tree": {"cut": "v", "at": 0.5,
                      "low": {"cell": "l1"}, "high": {"cell": "C"}}},
            {"elevation": 3.0, "height": 2.7,
             "tree": {"low": {"cell": "b1"},
                      "high": {"cut": "u", "at": 0.4,
                               "low": {"cell": "C"}, "high": {"cell": "t1", "share": 2}}}},
        ],
        "meta": {"seed": 7},
    }
    d.update(over)
    return d


_LEANING = [[0, 0], [20, 0], [20, 10], [12, 10]]


def _load(tmp_path, doc) -> dom.Node:
    p = tmp_path / "x.dom"
    p.write_text(yaml.safe_dump(doc, sort_keys=False))
    return dom.load(str(p))


def _bbox(leaf):
    c = [geometry.coordinate(leaf, i) for i in range(4)]
    xs, ys = [p[0] for p in c], [p[1] for p in c]
    return tuple(round(v, 9) for v in (min(xs), max(xs), min(ys), max(ys)))


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #
def test_a_v2_document_builds_the_cells_it_describes(tmp_path):
    root = _load(tmp_path, _doc())
    ground, upper = dom.levels(root)
    cells = {lf.type: _bbox(lf) for lf in ground.leaves()}
    assert cells == {"l1": (0.25, 5.0, 0.25, 7.75), "C": (5.0, 9.75, 0.25, 7.75)}
    up = {lf.type: _bbox(lf) for lf in upper.leaves()}
    assert up == {"b1": (0.25, 5.0, 0.25, 7.75),      # the inherited cut
                  "C": (5.0, 9.75, 0.25, 3.25),       # 0.4 of the frame's 7.5
                  "t1": (5.0, 9.75, 3.25, 7.75)}
    assert root.perimeter == {"a": "private", "b": None, "c": "street", "d": None}
    assert (ground.height, upper.height, upper.elevation) == (3.0, 2.7, 3.0)
    assert root.meta == {"seed": 7}
    t1 = next(lf for lf in upper.leaves() if lf.type == "t1")
    assert (t1.share, t1.share_type) == (2, "t1")


def test_dump_then_load_then_dump_is_the_same_text(tmp_path):
    root = _load(tmp_path, _doc())
    text = dom.dumps(root, version=2)
    assert list(yaml.safe_load(text))[:2] == ["format", "version"]
    again = _load(tmp_path, yaml.safe_load(text))
    assert dom.dumps(again, version=2) == text


def test_v1_is_still_the_default_and_carries_no_format_key(tmp_path):
    root = _load(tmp_path, _doc())
    v1 = yaml.safe_load(dom.dumps(root))
    assert "format" not in v1 and "node" in v1 and "above" in v1
    p = tmp_path / "v1.dom"
    p.write_text(dom.dumps(root))
    back = dom.load(str(p))
    assert sorted(_bbox(lf) for lvl in dom.levels(back) for lf in lvl.leaves()) == \
        sorted(_bbox(lf) for lvl in dom.levels(root) for lf in lvl.leaves())
    with pytest.raises(ValueError, match="version 3"):
        dom.dumps(root, version=3)


# --------------------------------------------------------------------------- #
# refusing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("over, says", [
    ({"version": 3}, "version 3"),
    ({"version": "2"}, "version '2'"),
    ({"format": "something-else"}, "something-else"),
    ({"blocks": [{"rect": [0, 1, 0, 1], "type": "C"}]}, "blocks"),
    ({"plot": [[0, 0], [10, 0], [10, 8], [5, 9], [0, 8]],
      "perimeter": [None] * 5}, "5 vertices"),
    ({"frame": {"u": [0.0, 1.0]}}, "frame.u"),
    ({"storeys": []}, "no storeys"),
])
def test_what_the_reader_does_not_know_it_refuses(tmp_path, over, says):
    with pytest.raises(DomFormatError, match=says):
        _load(tmp_path, _doc(**over))


def test_v2_is_refused_while_orthogonal_division_is_off(tmp_path, monkeypatch):
    """A v2 file means one building; with the switch off the v1 tree it is read
    into would draw another. Refuse, and do not flip the switch on the quiet."""
    root = _load(tmp_path, _doc())
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", False)
    with pytest.raises(DomFormatError, match="HOMEMAKER_ORTHOGONAL_DIVISION"):
        _load(tmp_path, _doc())
    with pytest.raises(DomFormatError, match="HOMEMAKER_ORTHOGONAL_DIVISION"):
        dom.dumps(root, version=2)
    assert geometry.ORTHOGONAL_DIVISION is False


def test_an_inherited_cut_may_not_be_restated(tmp_path):
    doc = _doc()
    doc["storeys"][1]["tree"].update(cut="v", at=0.3)
    with pytest.raises(DomFormatError, match="inherits that cut"):
        _load(tmp_path, doc)


def test_a_cut_that_misses_its_cropped_cell_is_refused(tmp_path):
    """A plot whose left side leans in: 20 m along the bottom, 8 m along the
    top. The frame is the bounding box, so above the first cut a line at 0.1 of
    the frame's width exists in the frame and lies wholly outside the plot --
    an EMPTY cell, which the v1 tree cannot hold."""
    doc = _doc(plot=_LEANING, storeys=[
        {"elevation": 0.0, "height": 3.0, "tree": {
            "cut": "u", "at": 0.5, "low": {"cell": "l1"},
            "high": {"cut": "v", "at": 0.1,
                     "low": {"cell": "k1"}, "high": {"cell": "b1"}}}}])
    with pytest.raises(DomFormatError, match="misses this cell"):
        _load(tmp_path, doc)


def test_an_upper_cut_against_a_fixed_orientation_is_refused(tmp_path):
    """`geometry` reads a cell's rotation from the lowest storey that has it.
    Ground floor cut one way, first floor left whole, second floor cut the
    OTHER way across the same cell: the v1 tree cannot hold it, because the
    ground floor's cut has already fixed which edges a cut there joins."""
    def doc(top_axis):
        return _doc(storeys=[
            {"elevation": 0.0, "height": 3.0, "tree": {
                "cut": "v", "at": 0.5, "low": {"cell": "l1"}, "high": {"cell": "C"}}},
            {"elevation": 3.0, "height": 3.0, "tree": {"cell": "C"}},
            {"elevation": 6.0, "height": 3.0, "tree": {
                "cut": top_axis, "at": 0.3, "low": {"cell": "b1"}, "high": {"cell": "C"}}}])
    top = dom.levels(_load(tmp_path, doc("v")))[2]
    assert sorted(_bbox(lf) for lf in top.leaves()) == [
        (0.25, 3.1, 0.25, 7.75), (3.1, 9.75, 0.25, 7.75)]
    with pytest.raises(DomFormatError, match="orientation"):
        _load(tmp_path, doc("u"))


def test_a_skew_design_cannot_be_written_as_v2(tmp_path):
    """The same leaning plot, cut upwards from a point on its long bottom edge
    that its short top edge does not reach across to: `_orthogonal_b` falls
    back to the stored offset, the cut is skew, and v2 has no way to say so."""
    root = _load(tmp_path, _doc(plot=_LEANING, storeys=[
        {"elevation": 0.0, "height": 3.0, "tree": {"cell": "l1"}}]))
    root.rotation, root.division = 0, [0.3, 0.3]
    root.left, root.right, root.type = dom.Node(type="l1"), dom.Node(type="k1"), None
    dom.link(root)
    geometry.clear_cache()
    with pytest.raises(DomFormatError, match="not parallel to a plot axis"):
        dom.dumps(root, version=2)


# --------------------------------------------------------------------------- #
# the corpus: every tracked orthogonal design
# --------------------------------------------------------------------------- #
def _diag():
    spec = importlib.util.spec_from_file_location("_rt", DIAG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


needs_corpus = pytest.mark.skipif(
    not (REPO / "examples" / "maple-court").is_dir(), reason="examples absent")


@needs_corpus
def test_every_orthogonal_artefact_keeps_every_cell():
    """§39.88's experiment 1, as the reader and writer rather than a script:
    v1 -> v2 -> memory, every cell the same polygon, and writing the result
    again reproduces the v2 text."""
    rt = _diag()
    rf = rt._frame_diag()
    paths = rt.corpus()
    assert len(paths) >= 192
    n_cells = 0
    for p, _ in paths:
        a = dom.load(str(p))
        text = dom.dumps(a, version=2)
        b = dom_v2.from_document(yaml.safe_load(text))
        ok, bad = rt.same_cells(rt.cells(a, rf), rt.cells(b, rf), rf)
        assert bad == 0, p
        assert dom.dumps(b, version=2) == text, p
        n_cells += ok
    assert n_cells > 3500


@needs_corpus
def test_the_cell_comparison_can_fail():
    """Negative control (CLAUDE.md: a null is worth nothing until its check has
    been shown to fire): one cut moved by 1e-4 of its range is a different
    building, and the comparison above must say so."""
    assert _diag().mode_cells(self_test=True) == 0


def _one_per_corpus(rt):
    seen, out = set(), []
    for p, prog in rt.corpus():
        key = (prog.name, p.parent.name)
        if key not in seen:
            seen.add(key)
            out.append((p, prog))
    assert len(out) >= 6
    return out


@needs_corpus
def test_a_round_trip_keeps_the_score():
    """Cells identical was not score identical when this format was written:
    75 of 192 scores moved on a round trip (DESIGN.md §39.94). A round trip
    moves every cut by a few ulps and turns every leaf's corner numbering, and
    the scorer was reading both -- since fixed (§39.95), and this is the test
    that they stay fixed: the STRICT score survives.

    v2 does not write an inherited node's own stored ratio either, and since
    §39.96 `merge_divided` no longer revives one. One programme per corpus
    keeps this quick;
    `diag_8b2u2_roundtrip.py --scores` is the full 192.
    """
    rt = _diag()
    for p, prog in _one_per_corpus(rt):
        a = dom.load(str(p))
        b = rt.round_trip(a)
        sa, fa = rt.score(a, prog)
        sb, fb = rt.score(b, prog)
        assert math.isclose(sa, sb, rel_tol=1e-6), p
        assert len(fa) == len(fb), p

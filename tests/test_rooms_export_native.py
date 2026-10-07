"""The rooms export reads a format-v2 design as the native tree it describes
(`homemaker-py-6e5u` follow-on, DESIGN.md §39.119).

Until this a cell was written from four corners, so a v2 design -- which is
what `homemaker-evolve --native` writes -- could only be exported if it
happened to fit Urb's quad tree. Two halves: every design both trees can hold
must export THE SAME rooms from either, and what only a native tree can hold
must export at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from homemaker_layout import dom, dom_v2, geometry, rooms_export

REPO = Path(__file__).resolve().parent.parent
PH = REPO / "examples" / "programme-house"

pytestmark = pytest.mark.skipif(not PH.is_dir(), reason="examples absent")


@pytest.fixture(autouse=True)
def restore(monkeypatch):
    was = geometry.ORTHOGONAL_DIVISION
    yield
    geometry.ORTHOGONAL_DIVISION = was
    geometry.clear_cache()


def _walls(room) -> set:
    """Each wall as (its two ends, its style), however the ring is started."""
    v = [(round(x, 4), round(y, 4)) for x, y in room["vertices"]]
    return {(frozenset((v[i], v[(i + 1) % len(v)])), room["face_styles"][i + 2])
            for i in range(len(v))}


def _essence(doc) -> list:
    return sorted((r["usage"], r["code"], r["elevation"], r["height"], r["roofed"],
                   sorted(map(repr, _walls(r)))) for r in doc["rooms"])


def _both(path, prog, tmp_path, nudge=0.0):
    geometry.ORTHOGONAL_DIVISION = True
    geometry.clear_cache()
    quad = rooms_export.document(path, prog)
    as_v2 = dom_v2.to_document(dom.load(str(path)))
    if nudge:
        as_v2["storeys"][0]["tree"]["at"] += nudge
    v2 = tmp_path / (Path(path).stem + ".v2.dom")
    import yaml
    v2.write_text(yaml.safe_dump(as_v2, sort_keys=False))
    geometry.ORTHOGONAL_DIVISION = False        # a v2 file needs no switch
    geometry.clear_cache()
    return quad, rooms_export.document(v2, prog)


@pytest.mark.parametrize("programme", ["programme-house", "harbor-house", "maple-court"])
def test_a_design_exports_the_same_rooms_and_roof_from_either_tree(programme, tmp_path):
    prog = REPO / "examples" / programme
    for path in sorted(prog.glob("coldstart-1a24b6a+orth-500000-s*.dom")):
        quad, native = _both(path, prog, tmp_path)
        assert _essence(native) == _essence(quad), path.name
        assert len(native.get("faces", [])) == len(quad.get("faces", [])), path.name
        assert json.dumps(native["widgets"]) == json.dumps(quad["widgets"]), path.name


def test_control_a_native_design_with_one_wall_moved_exports_different_rooms(tmp_path):
    path = sorted(PH.glob("coldstart-1a24b6a+orth-500000-s*.dom"))[0]
    quad, native = _both(path, PH, tmp_path, nudge=0.02)
    assert _essence(native) != _essence(quad)


LEANING = [[0, 0], [20, 0], [20, 10], [12, 10]]       # the left side leans in


def _write(tmp_path, tree, plot=LEANING, **over):
    import yaml

    doc = {"format": "homemaker-dom", "version": 2, "frame": {"u": [1.0, 0.0]},
           "plot": plot, "wall_outer": 0.0, "wall_inner": 0.08,
           "storeys": [{"elevation": 0.0, "height": 3.0, "tree": tree}]}
    doc.update(over)
    for f in PH.glob("*.config"):
        (tmp_path / f.name).write_text(f.read_text())
    path = tmp_path / "native.dom"
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return path


def test_a_cell_the_plot_crops_is_exported_with_the_corners_it_has(tmp_path):
    """A leaning plot side cuts one room to a triangle and another to five
    corners; both are rooms, and the wall along the leaning side is the
    party wall it is declared to be."""
    tree = {"cut": "u", "at": 0.5, "low": {"cell": "l1"},
            "high": {"cut": "v", "at": 0.5, "low": {"cell": "b1"}, "high": {"cell": "b2"}}}
    path = _write(tmp_path, tree, perimeter=[None, None, None, "private"])
    doc = rooms_export.document(path, tmp_path)
    corners = {r["code"]: len(r["vertices"]) for r in doc["rooms"]}
    assert corners == {"l1": 4, "b1": 3, "b2": 5}
    for r in doc["rooms"]:
        assert len(r["face_styles"]) == 2 + len(r["vertices"])
        assert rooms_export._convex(r["vertices"])
    # the leaning side runs from (12, 10) to (0, 0): every wall on it is blank,
    # and no other wall is
    def on_side(a, b):
        return all(abs(p[1] - p[0] * 10 / 12) < 1e-6 for p in (a, b))
    seen = 0
    for r in doc["rooms"]:
        v = r["vertices"]
        for i in range(len(v)):
            blank = r["face_styles"][i + 2] == "blank"
            assert blank == on_side(v[i], v[(i + 1) % len(v)]), (r["code"], i)
            seen += blank
    assert seen >= 2
    # and the roof over three rooms of 4, 3 and 5 corners closes on one outline
    assert doc["faces"] and len(doc["widgets"]) == 1


def test_a_cell_off_the_plot_is_not_a_room(tmp_path):
    tree = {"cut": "u", "at": 0.5, "low": {"cell": "l1"},
            "high": {"cut": "v", "at": 0.25, "low": {"cell": "b1"}, "high": {"cell": "b2"}}}
    doc = rooms_export.document(_write(tmp_path, tree), tmp_path)
    assert sorted(r["code"] for r in doc["rooms"]) == ["b2", "l1"]

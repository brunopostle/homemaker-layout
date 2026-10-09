"""`homemaker-rooms`: a layout as a homemaker-addon rooms document.

docs/rooms-format.md is the contract. These pin the parts that are easy to get
quietly wrong: which walls are party walls, polygon orientation and its effect
on the wall order, the usage mapping and its refusals, and the merge the
scorer applies before it reads a room.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from homemaker_layout import dom, geometry, rooms_export
from homemaker_layout.programme import SpaceReq

REPO = Path(__file__).resolve().parent.parent
PROG = REPO / "examples" / "programme-house"
DOM = PROG / "coldstart-1a24b6a+orth-500000-s0.dom"
pytestmark = pytest.mark.skipif(not DOM.is_file(), reason="artefact absent")


@pytest.fixture
def doc(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    return rooms_export.document(DOM, PROG)


def _on_line(a, b, p, tol=1e-3):
    cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    return abs(cross) / ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 < tol


def test_header_and_tracing_keys(doc):
    assert doc["format"] == "homemaker-rooms" and doc["version"] == 1
    for r in doc["rooms"]:
        assert set(r) >= {"vertices", "elevation", "height", "face_styles",
                          "stylename", "usage", "dom_id", "code"}
        assert len(r["face_styles"]) == len(r["vertices"]) + 2
    json.dumps(doc)                       # plain JSON, as the web editor needs


def test_rooms_are_convex_and_counter_clockwise(doc):
    for r in doc["rooms"]:
        v = r["vertices"]
        n = len(v)
        crosses = [(v[(i + 1) % n][0] - v[i][0]) * (v[(i + 2) % n][1] - v[(i + 1) % n][1])
                   - (v[(i + 1) % n][1] - v[i][1]) * (v[(i + 2) % n][0] - v[(i + 1) % n][0])
                   for i in range(n)]
        assert all(c > -1e-9 for c in crosses), r["dom_id"]


def test_blank_walls_are_exactly_the_walls_on_a_private_plot_edge(doc, monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    root = dom.load(str(DOM))
    dom.link(root)
    geometry.clear_cache()
    u, v = geometry._reference_axes(root)
    plot = [[x * u[0] + y * u[1], x * v[0] + y * v[1]]       # the document is in the frame
            for x, y in (geometry.coordinate(root, i) for i in range(4))]
    edges = {geometry.boundary_id(root, i): (plot[i], plot[(i + 1) % 4]) for i in range(4)}
    private = [k for k, s in (root.perimeter or {}).items() if s == "private"]
    assert private, "fixture must have a party wall to test"
    blank = 0
    for r in doc["rooms"]:
        v = r["vertices"]
        for i, style in enumerate(r["face_styles"][2:]):
            on = any(_on_line(*edges[k], v[i]) and _on_line(*edges[k], v[(i + 1) % len(v)])
                     for k in private)
            assert (style == "blank") == on, (r["dom_id"], i, style)
            blank += style == "blank"
    assert blank > 0


def test_usage_mapping(doc):
    usages = {(r["code"], r["usage"]) for r in doc["rooms"]}
    assert ("b1", "bedroom") in usages and ("t1", "toilet") in usages
    assert ("E", "stair") in usages      # programme-house has a shaft; the addon's stair usage is "stair"
    assert all(u == "outside" for c, u in usages if c == "O")
    assert set(rooms_export.USAGE_MAP) >= {"bedroom", "kitchen", "living", "toilet",
                                           "none", "utility"}
    assert rooms_export.USAGE_MAP["none"] == "void"      # owner, 2026-10-05


def test_an_uncovered_outdoor_cell_is_not_a_room(doc, monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    root = dom.load(str(DOM))
    dom.link(root)
    open_air = [f"{li}/{lf.id}" for li, lvl in enumerate(dom.levels(root))
                for lf in lvl.leaves() if dom.is_outside(lf) and not dom.is_covered(lf)]
    exported = {r["dom_id"] for r in doc["rooms"]}
    assert not exported & set(open_air)


def test_an_unmapped_usage_is_refused_not_defaulted(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    real = rooms_export.load_programme_dir

    def with_garage(path):
        reqs = dict(real(path))
        code = next(c for c, r in reqs.items() if r.usage == "bedroom")
        reqs[code] = SpaceReq(**{**reqs[code].__dict__, "usage": "garage"})
        return reqs
    monkeypatch.setattr(rooms_export, "load_programme_dir", with_garage)
    with pytest.raises(rooms_export.ExportError, match="garage"):
        rooms_export.document(DOM, PROG)


def _split(root, code, a, b):
    leaf = next(lf for lf in dom.levels(root)[0].leaves() if lf.type == code)
    leaf.division, leaf.rotation = [0.5, 0.5], 0
    leaf.left, leaf.right, leaf.type = dom.Node(type=a), dom.Node(type=b), None
    dom.link(root)


def test_rooms_follow_the_scorers_merge_and_count(monkeypatch):
    """`dom.merge_divided` fuses adjacent OUTDOOR siblings and nothing else, and
    the scorer counts room instances per leaf. The export must agree with both:
    two room leaves of one code are two rooms (the scorer would charge 'too many
    spaces'), two outdoor siblings are one."""
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    root = dom.load(str(DOM))
    dom.link(root)
    _split(root, "l1", "l1", "l1")
    assert sum(r["code"] == "l1" for r in rooms_export.rooms(root, PROG)) == 2
    root = dom.load(str(DOM))
    dom.link(root)
    before = len(rooms_export.rooms(root, PROG))
    covered_o = [r for r in rooms_export.rooms(root, PROG) if r["code"] == "O"]
    if covered_o:
        _split(root, "O", "O", "O")
        assert len(rooms_export.rooms(root, PROG)) == before


def test_rooms_are_in_the_frame_so_interior_walls_are_axial(doc, monkeypatch):
    """homemaker-addon snaps vertices to 1 mm. In world coordinates on a skew plot
    that knocked T-junction corners off their walls and the build never finished
    (12 cells from 11 rooms); in the frame every wall NOT on the plot boundary is
    exactly axial, so snapping cannot move a point off one."""
    import math
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    fu = doc["meta"]["frame"]["u"]
    assert doc["meta"]["frame"]["angle_degrees"] == pytest.approx(
        math.degrees(math.atan2(fu[1], fu[0])))
    root = dom.load(str(DOM))
    dom.link(root)
    geometry.clear_cache()
    u, v = geometry._reference_axes(root)
    plot = [[x * u[0] + y * u[1], x * v[0] + y * v[1]]
            for x, y in (geometry.coordinate(root, i) for i in range(4))]
    skew = 0
    for r in doc["rooms"]:
        vs = r["vertices"]
        for i in range(len(vs)):
            a, b = vs[i], vs[(i + 1) % len(vs)]
            if abs(a[0] - b[0]) < 2e-4 or abs(a[1] - b[1]) < 2e-4:
                continue
            skew += 1
            assert any(_on_line(plot[k], plot[(k + 1) % 4], a) and
                       _on_line(plot[k], plot[(k + 1) % 4], b) for k in range(4)), \
                (r["dom_id"], i, "a skew wall that is not on the plot boundary")
    assert skew > 0, "fixture plot is skew to its own frame on some edge"

"""Pitched roofs for the rooms export (`homemaker-py-6e5u`, DESIGN.md §39.119).

A roof here is geometry handed to another program, so the tests are about
whether the geometry is right and whether it closes:

* the surface is the straight-skeleton roof -- held to TWO independent
  measures, because the obvious one (a straight-skeleton library) turned out
  to be wrong on exactly the outlines an orthogonal plan makes;
* the faces are flat, tile the outline, and meet their neighbours corner for
  corner, so that the cell they enclose with the ceilings below is closed;
* a gable is made only where a roof ends at a party wall.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from pathlib import Path

import pytest
from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from homemaker_layout import roofs

REPO = Path(__file__).resolve().parent.parent
RECT = Polygon([(0, 0), (8, 0), (8, 5), (0, 5)])
ELL = Polygon([(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)])


# --------------------------------------------------------------------------- #
# shapes whose roof can be written down
# --------------------------------------------------------------------------- #
def test_a_rectangle_gets_two_slopes_two_hips_and_a_ridge():
    made = roofs.roof(RECT, 45.0, eave=3.0)
    assert sorted(len(f) for f in made["faces"]) == [3, 3, 4, 4]
    assert made["apex"][2] == pytest.approx(5.5)             # half the 5 m span, at 45 degrees
    ridge = {tuple(p) for f in made["faces"] for p in f if p[2] == pytest.approx(5.5)}
    assert ridge == {(2.5, 2.5, 5.5), (5.5, 2.5, 5.5)}


def test_the_pitch_sets_the_height():
    for pitch in (20.0, 35.0, 60.0):
        made = roofs.roof(RECT, pitch)
        assert made["apex"][2] == pytest.approx(2.5 * math.tan(math.radians(pitch)))


def test_an_l_shape_has_a_valley_from_its_inside_corner():
    rise = roofs.surface(ELL, 45.0)
    assert rise(2, 2) == pytest.approx(2.0)                  # where the two ridges meet
    assert rise(3, 3) == pytest.approx(1.0)                  # on the valley, half-way down
    assert rise(4, 4) == pytest.approx(0.0, abs=1e-6)        # the inside corner is an eave
    assert rise(7, 2) == pytest.approx(2.0) and rise(2, 7) == pytest.approx(2.0)


# --------------------------------------------------------------------------- #
# the surface, against two independent measures
# --------------------------------------------------------------------------- #
def _orthogonal_outline(rng) -> "Polygon | None":
    rects = [box(0, 0, rng.uniform(6, 14), rng.uniform(5, 12))]
    for _ in range(rng.randint(1, 4)):
        x, y = rng.uniform(-4, 10), rng.uniform(-4, 10)
        rects.append(box(x, y, x + rng.uniform(3, 9), y + rng.uniform(3, 9)))
    u = unary_union(rects)
    if u.geom_type != "Polygon":
        return None
    if rng.random() < 0.4:
        cx, cy = u.representative_point().coords[0]
        hole = box(cx - 0.8, cy - 0.8, cx + 0.8, cy + 0.8)
        if u.buffer(-1.5).contains(hole):
            u = u.difference(hole)
    return u if u.geom_type == "Polygon" else None


def _samples(poly, rng, n=20):
    inner, out, tries = poly.buffer(-0.05), [], 0
    minx, miny, maxx, maxy = poly.bounds
    while len(out) < n and tries < 2000:
        tries += 1
        p = (rng.uniform(minx, maxx), rng.uniform(miny, maxy))
        if inner.contains(Point(p)):
            out.append(p)
    return out


def _largest_centred_square(poly, x, y) -> float:
    """Half the side of the largest axis-aligned square centred on (x, y)
    inside ``poly``. On an outline whose sides are all axial this IS the rise
    of a 45-degree roof: the straight skeleton of such a polygon is its
    medial axis in the L-infinity metric (Aichholzer et al.)."""
    lo, hi = 0.0, 50.0
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if poly.contains(box(x - mid, y - mid, x + mid, y + mid)) else (lo, mid)
    return lo


def _orthogonal_disagreements(surface_for) -> "tuple[int, int, int]":
    rng = random.Random(3)
    outlines = holes = points = wrong = 0
    while outlines < 30:
        poly = _orthogonal_outline(rng)
        if poly is None:
            continue
        outlines += 1
        holes += bool(poly.interiors)
        rise = surface_for(poly)
        for x, y in _samples(poly, rng):
            points += 1
            wrong += abs(rise(x, y) - _largest_centred_square(poly, x, y)) > 1e-3
    assert outlines == 30 and holes >= 5 and points > 500
    return outlines, points, wrong


def test_on_orthogonal_outlines_the_roof_is_the_largest_square_that_fits():
    """Thirty random outlines made of overlapping rectangles, a third of them
    with a courtyard: the many-events-at-once case an orthogonal plan makes."""
    assert _orthogonal_disagreements(lambda poly: roofs.surface(poly, 45.0))[2] == 0


def test_control_that_measure_tells_a_wrong_roof_from_a_right_one():
    """The same comparison with a roof a tenth of a degree too steep."""
    assert _orthogonal_disagreements(lambda poly: roofs.surface(poly, 45.1))[2] > 100


def test_on_outlines_in_general_position_it_is_the_straight_skeleton():
    """Random star-shaped outlines with reflex corners at any angle, against
    `bpypolyskel`. That library is the oracle HERE and not above: on
    orthogonal outlines it disagrees with the largest-square measure, and the
    measure is right (20 points of 20, when this was written)."""
    np = pytest.importorskip("numpy")
    bp = pytest.importorskip("bpypolyskel.bpypolyskel")
    mathutils = pytest.importorskip("mathutils")

    def oracle(poly):
        verts = [mathutils.Vector((x, y, 0.0)) for x, y in orient(poly, 1.0).exterior.coords[:-1]]
        n = len(verts)
        planes = []
        for face in bp.polygonize(verts, 0, n, None, 0.0, 1.0):
            vs = [verts[i] for i in face]
            a = np.array([[v.x, v.y, 1.0] for v in vs])
            coef, *_ = np.linalg.lstsq(a, np.array([v.z for v in vs]), rcond=None)
            planes.append((Polygon([(v.x, v.y) for v in vs]), coef))

        def rise(x, y):
            hits = [float(c[0] * x + c[1] * y + c[2]) for pg, c in planes
                    if pg.is_valid and pg.distance(Point(x, y)) < 1e-6]
            return min(hits) if hits else None
        return rise

    rng = random.Random(11)
    outlines = reflex = points = wrong = 0
    for _ in range(60):
        k = rng.randint(5, 11)
        angles = sorted(rng.uniform(0, 2 * math.pi) for _ in range(k))
        poly = Polygon([(rng.uniform(3, 10) * math.cos(a), rng.uniform(3, 10) * math.sin(a))
                        for a in angles])
        if not poly.is_valid or poly.area < 10:
            continue
        poly = orient(poly, 1.0)
        c = list(poly.exterior.coords)[:-1]
        reflex += sum(
            (c[i][0] - c[i - 1][0]) * (c[(i + 1) % len(c)][1] - c[i][1])
            - (c[i][1] - c[i - 1][1]) * (c[(i + 1) % len(c)][0] - c[i][0]) < 0
            for i in range(len(c)))
        try:
            want = oracle(poly)
        except Exception:               # the library gives up on some outlines
            continue
        rise = roofs.surface(poly, 45.0)
        outlines += 1
        for x, y in _samples(poly, rng):
            w = want(x, y)
            if w is None:
                continue
            points += 1
            wrong += abs(rise(x, y) - w) > 0.05
    assert outlines > 30 and reflex > 60 and points > 600
    assert wrong == 0


# --------------------------------------------------------------------------- #
# the faces close
# --------------------------------------------------------------------------- #
def _plane_error(face) -> float:
    """How far the face's corners stand off its plane -- the plane through
    the three of them that span the largest triangle, so that a nearly
    straight run of corners is not what the plane is taken from."""
    best, normal, origin = 0.0, None, None
    n = len(face)
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                u = [face[j][c] - face[i][c] for c in range(3)]
                v = [face[k][c] - face[i][c] for c in range(3)]
                w = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2],
                     u[0] * v[1] - u[1] * v[0]]
                size = math.sqrt(sum(x * x for x in w))
                if size > best:
                    best, normal, origin = size, [x / size for x in w], face[i]
    assert normal is not None, "a face with all its corners in a line"
    return max(abs(sum((p[c] - origin[c]) * normal[c] for c in range(3))) for p in face)


def _closure(made, outline, eave=0.0):
    """(edges used by one face only that are NOT on the eave, worst planarity,
    plan area covered by the sloping faces)."""
    seen: list = []

    def key(p):
        # the same corner as listed by two faces: equal to within 20 microns,
        # which is far inside what homemaker-addon merges. (Rounding instead
        # splits a corner whose height falls either side of a rounding step.)
        for q in seen:
            if all(abs(p[c] - q[c]) < 2e-5 for c in range(3)):
                return q
        seen.append(tuple(p))
        return seen[-1]

    use = Counter()
    for f in made["faces"]:
        for i, p in enumerate(f):
            a, b = key(p), key(f[(i + 1) % len(f)])
            use[frozenset((a, b))] += 1
    loose = [e for e, n in use.items() if n != 2
             and not all(abs(p[2] - eave) < 1e-4 for p in e)]
    area = sum(Polygon([(p[0], p[1]) for p in f]).area for f in made["faces"]
               if Polygon([(p[0], p[1]) for p in f]).area > 1e-9)
    return loose, max(_plane_error(f) for f in made["faces"]), area


def _trial_outlines():
    rng = random.Random(5)
    out = [RECT, ELL]
    while len(out) < 26:
        poly = _orthogonal_outline(rng)
        if poly is not None:
            # every other one leaned a few degrees, like a plot that is not square
            out.append(affinity.skew(poly, xs=rng.uniform(-4, 4)) if len(out) % 2 else poly)
    return out


@pytest.mark.parametrize("gabled", [False, True])
def test_every_roof_is_flat_faced_tiles_its_outline_and_meets_edge_to_edge(gabled):
    """Above the eave every edge is shared by exactly two faces -- two slopes,
    or a slope and a gable wall -- so with the ceilings below the roof is a
    closed cell. And every face is flat to well inside the micron
    homemaker-addon tolerates."""
    gable = (lambda a, b: abs(a[1] - b[1]) > 1e-6) if gabled else None
    made_gables = 0
    for outline in _trial_outlines():
        made = roofs.roof(outline, 35.0, is_gable=gable)
        loose, flatness, area = _closure(made, outline)
        assert not loose, f"{len(loose)} roof edges belong to one face only"
        assert flatness < 2e-7
        assert area == pytest.approx(outline.area, rel=1e-4)
        made_gables += made["gables"]
    assert (made_gables > 5) == gabled


def test_control_a_roof_with_a_face_removed_is_caught_open():
    made = roofs.roof(ELL, 35.0)
    made["faces"].pop(1)
    assert _closure(made, ELL)[0]


# --------------------------------------------------------------------------- #
# gables
# --------------------------------------------------------------------------- #
def _short_sides(a, b):
    return abs(a[0] - b[0]) < 1e-9          # RECT's two 5 m ends


def test_a_roof_that_ends_at_a_party_wall_gets_a_gable():
    made = roofs.roof(RECT, 45.0, eave=3.0, is_gable=_short_sides)
    assert (made["gables"], made["hipped"]) == (2, 0)
    walls = [f for f in made["faces"] if len({p[0] for p in f}) == 1]      # vertical: one x
    assert len(walls) == 2
    for wall in walls:
        assert sorted(p[2] for p in wall) == pytest.approx([3.0, 3.0, 5.5])
    # the ridge now runs the whole length, wall to wall
    assert {(p[0], p[1]) for f in made["faces"] for p in f if p[2] == pytest.approx(5.5)} \
        >= {(0.0, 2.5), (8.0, 2.5)}


def test_a_party_wall_along_the_side_of_a_roof_keeps_its_slope():
    made = roofs.roof(RECT, 45.0, is_gable=lambda a, b: abs(a[1] - b[1]) < 1e-9 and a[1] < 1)
    assert (made["gables"], made["hipped"]) == (0, 1)
    assert sorted(len(f) for f in made["faces"]) == [3, 3, 4, 4]           # the hipped roof


# --------------------------------------------------------------------------- #
# from rooms
# --------------------------------------------------------------------------- #
def _room(vertices, elevation=3.0, roofed=True, walls=None):
    styles = ["default", "default"] + (walls or ["default"] * len(vertices))
    return {"vertices": vertices, "elevation": elevation, "height": 3.0,
            "face_styles": styles, "usage": "bedroom", "roofed": roofed}


def test_rooms_that_share_a_wall_are_under_one_roof():
    rooms = [_room([[0, 0], [4, 0], [4, 5], [0, 5]]), _room([[4, 0], [8, 0], [8, 5], [4, 5]]),
             _room([[20, 0], [24, 0], [24, 4], [20, 4]]),                   # a separate wing
             _room([[0, 0], [8, 0], [8, 5], [0, 5]], elevation=0.0, roofed=False)]
    faces, widgets, notes = roofs.for_rooms(rooms, 45.0)
    assert len(widgets) == 2 and not notes
    assert all(w["usage"] == "void" for w in widgets)
    assert min(p[2] for f in faces for p in f["vertices"]) == pytest.approx(6.0)   # the top ceiling
    assert max(p[2] for f in faces for p in f["vertices"]) == pytest.approx(8.5)
    for w in widgets:                           # each marker is inside its roof, off the ceiling
        assert 6.0 < w["position"][2] < 8.5


def test_a_party_wall_is_read_from_the_rooms_own_blank_walls():
    party_end = _room([[0, 0], [8, 0], [8, 5], [0, 5]],
                      walls=["default", "blank", "default", "default"])     # the x = 8 end
    faces, _, notes = roofs.for_rooms([party_end], 45.0)
    vertical = [f for f in faces if len({p[0] for p in f["vertices"]}) == 1]
    assert len(vertical) == 1 and {p[0] for p in vertical[0]["vertices"]} == {8.0}
    assert not notes
    assert not [f for f in roofs.for_rooms([party_end], 45.0, gables=False)[0]
                if len({p[0] for p in f["vertices"]}) == 1]


def test_nothing_is_roofed_that_has_a_storey_over_it():
    assert roofs.for_rooms([_room([[0, 0], [8, 0], [8, 5], [0, 5]], roofed=False)], 35.0) \
        == ([], [], [])


@pytest.mark.skipif(not (REPO / "examples" / "harbor-house").is_dir(), reason="examples absent")
@pytest.mark.parametrize("programme", ["programme-house", "harbor-house", "maple-court"])
def test_real_designs_get_roofs_that_close(programme, monkeypatch):
    from homemaker_layout import geometry, rooms_export

    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    prog = REPO / "examples" / programme
    for path in sorted(prog.glob("coldstart-1a24b6a+orth-500000-s*.dom")):
        doc = rooms_export.document(path, prog)
        top = [r for r in doc["rooms"] if r["roofed"]]
        assert top and doc["faces"] and doc["widgets"], path.name
        eave = top[0]["elevation"] + top[0]["height"]
        made = {"faces": [f["vertices"] for f in doc["faces"]]}
        loose, flatness, area = _closure(made, None, eave)
        assert not loose, f"{path.name}: {len(loose)} roof edges belong to one face only"
        assert flatness < 2e-7, path.name
        want = sum(o.area for o in roofs.outlines([r["vertices"] for r in top]))
        assert area == pytest.approx(want, rel=1e-3), path.name
        flat = rooms_export.document(path, prog, roof_pitch=None)
        assert "faces" not in flat and flat["rooms"] == doc["rooms"]
    geometry.clear_cache()

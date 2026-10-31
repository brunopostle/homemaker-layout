"""`mutate_pivot3` (homemaker-py-hjc5), the owner's sketch: A beside B over C
becomes A and B over C. Every cell keeps its plan area, its corner of the whole
cell and what is inside it, on every geometry."""

from __future__ import annotations

import copy
import glob
import math
from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, geometry, graph, operators

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
RECT = [[0.0, 0.0], [20.0, 0.0], [20.0, 12.0], [0.0, 12.0]]


def _sketch(monkeypatch, side="r"):
    """A on one side of a 20 x 12 rectangle, B and C stacked on the other."""
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    root = dom.Node(node=[list(p) for p in RECT], node_file=[list(p) for p in RECT],
                    height=3.0, elevation=0.0, wall_inner=0.0, wall_outer=0.0)
    root.division, root.rotation = [0.3, 0.3] if side == "r" else [0.7, 0.7], 0
    solo, half = dom.Node(type="a"), dom.Node(rotation=1, division=[0.4, 0.4])
    half.left, half.right = dom.Node(type="b"), dom.Node(type="c")
    root.left, root.right = (solo, half) if side == "r" else (half, solo)
    return operators._finalise(root)


def _box(leaf):
    pts = [geometry.coordinate(leaf, i) for i in range(geometry.n_edges(leaf))]
    xs, ys = zip(*pts)
    return (min(xs), min(ys), max(xs), max(ys))


def _cells(root):
    geometry.clear_cache()
    return {lf.type: _box(lf) for lf in root.leaves()}


def _overlap(p, q):
    return min(p[2], q[2]) - max(p[0], q[0]), min(p[3], q[3]) - max(p[1], q[1])


@pytest.mark.parametrize("side", ["l", "r"])
@pytest.mark.parametrize("span", ["l", "r"])
def test_the_sketch(monkeypatch, side, span):
    """Three cells: the chosen short cell ends up across the whole width, on the
    side it started, the other two beside each other beyond it, in their old
    order, and every area is kept. Asserted from the plan, not the tree."""
    root = _sketch(monkeypatch, side)
    before = _cells(root)
    areas = {lf.type: geometry.area(lf) for lf in root.leaves()}
    h = root.by_id(side)
    long_type, rest_type = h.by_id(span).type, h.by_id("r" if span == "l" else "l").type
    operators._pivot3([root], 0, root, side, span)
    operators._finalise(root)
    after = _cells(root)
    for lf in root.leaves():
        assert geometry.area(lf) == pytest.approx(areas[lf.type], rel=1e-9)
    # across the whole of the old stacked direction, the rectangle's other axis
    long_box, rest_box, a_box = after[long_type], after[rest_type], after["a"]
    full = (min(b[0] for b in before.values()), min(b[1] for b in before.values()),
            max(b[2] for b in before.values()), max(b[3] for b in before.values()))
    assert (long_box[2] - long_box[0]) == pytest.approx(full[2] - full[0]) \
        or (long_box[3] - long_box[1]) == pytest.approx(full[3] - full[1])
    # the long cell stays on its side of the rest, along the axis they were stacked on
    ax_before = before[long_type][1] < before[rest_type][1]
    assert (long_box[1] < rest_box[1]) == ax_before
    # the old long cell and the rest stay in their old left-right order
    assert (a_box[0] < rest_box[0]) == (before["a"][0] < before[rest_type][0])
    # the two still share a wall, and the long cell meets both
    for p, q in ((a_box, rest_box), (long_box, a_box), (long_box, rest_box)):
        o = _overlap(p, q)
        assert max(o) > 0.1 and min(o) == pytest.approx(0.0, abs=1e-6)


def test_the_move_undoes_itself(monkeypatch):
    """Having become (A|B)/C, spanning with A gives A|(B/C) back: the same plan."""
    root = _sketch(monkeypatch)
    before = _cells(root)
    operators._pivot3([root], 0, root, "r", "r")     # C (or B) spans
    operators._finalise(root)
    # the cut half is now the one holding the old long cell
    side = "l" if root.left.divided else "r"
    h = root.by_id(side)
    span = "l" if h.left.type == "a" else "r"
    operators._pivot3([root], 0, root, side, span)
    operators._finalise(root)
    after = _cells(root)
    for k in before:
        assert after[k] == pytest.approx(before[k], abs=1e-6)


def test_the_comparison_catches_a_wrong_answer(monkeypatch):
    """Negative control: `mutate_rotate`'s turn of the cut alone keeps no plan,
    and the sketch's assertions read it: A no longer occupies its old corner."""
    root = _sketch(monkeypatch)
    before = _cells(root)
    root.rotation = (root.rotation + 1) % 4
    operators._finalise(root)
    after = _cells(root)
    assert any(after[k] != pytest.approx(before[k], abs=1e-3) for k in before)


def test_what_is_inside_a_cell_is_drawn_the_same_way(monkeypatch):
    """A subdivided long cell keeps its inner cut's direction and its children's
    order, whichever side of the T it ends up on."""
    root = _sketch(monkeypatch)
    root.left = dom.Node(rotation=1, division=[0.5, 0.5])
    root.left.left, root.left.right = dom.Node(type="a"), dom.Node(type="z")
    operators._finalise(root)
    before = _cells(root)
    across = abs(before["a"][1] - before["z"][1]) > 0.1      # stacked in y
    below = before["a"][1] < before["z"][1]
    operators._pivot3([root], 0, root, "r", "l")
    operators._finalise(root)
    after = _cells(root)
    assert (abs(after["a"][1] - after["z"][1]) > 0.1) == across
    assert (after["a"][1] < after["z"][1]) == below


def _artefacts():
    out = []
    for prog in ("programme-house", "harbor-house", "health-centre", "maple-court"):
        found = sorted(glob.glob(str(EXAMPLES / prog / "coldstart-*+orth-500000-s0.dom")))
        if found:
            out.append(found[-1])
    if not out:
        pytest.skip("no evolved artefacts")
    return out


def _load(path, mode, tmp_path):
    root = dom.load(path)
    if mode == "native":
        v2 = tmp_path / "v2.dom"
        v2.write_text(dom.dumps(root, version=2))
        root = dom.load(str(v2), native=True)
    return operators._finalise(root)


@pytest.fixture(params=["orth", "skew", "native"])
def mode(request, monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", request.param != "skew")
    geometry.clear_cache()
    return request.param


def _shafts(root):
    lvls = dom.levels(root)
    return sorted(operators._shaft_paths(lvls)).__len__()


def test_on_the_corpus(mode, tmp_path):
    """Every option on every artefact: no leaf lost, the top-level cells' areas
    kept where a cut can reach them, leaves' types kept per storey, shafts kept,
    and the tree still sound."""
    tested = above = exact = 0
    for path in _artefacts():
        root = _load(path, mode, tmp_path)
        lvls0 = dom.levels(root)
        for li, n0 in operators._owned_branches(root):
            for side, span in operators._pivot3_options(lvls0, li, n0):
                r = operators._finalise(copy.deepcopy(root))
                lvls = dom.levels(r)
                n = lvls[li].by_id(n0.id)
                h = n.by_id(side)
                cells = [h.left, h.right, n.by_id("l" if side == "r" else "r")]
                geometry.clear_cache()
                before = [geometry.area(c) for c in cells]
                types = [sorted(str(lf.type) for lf in lv.leaves()) for lv in lvls]
                shafts = _shafts(r)
                above += any((a := lv.by_id(n0.id)) is not None and a.divided
                             for lv in lvls[li + 1:])
                operators._pivot3(lvls, li, n, side, span)
                operators._finalise(r)
                geometry.clear_cache()
                assert [sorted(str(lf.type) for lf in lv.leaves())
                        for lv in dom.levels(r)] == types
                assert _shafts(r) == shafts, (path, li, n0.id)
                got = [geometry.area(c) for c in cells]
                assert sum(got) == pytest.approx(sum(before), rel=1e-6)
                if mode != "native":
                    assert got == pytest.approx(before, rel=1e-5), (path, li, n0.id)
                exact += got == pytest.approx(before, rel=1e-5)
                tested += 1
    assert tested and above and exact, (tested, above, exact)
    print(mode, tested, above, exact)


def test_a_storey_with_only_the_halves_is_refused(monkeypatch):
    """Upstairs keeps the first cut but not the second: nothing for it to be."""
    root = _sketch(monkeypatch)
    up = dom.Node(rotation=0, division=[0.3, 0.3], height=3.0)
    up.left, up.right = dom.Node(type="d"), dom.Node(type="e")
    root.above = up
    up.below = root
    operators._finalise(root)
    lvls = dom.levels(root)
    assert len(lvls) == 2
    assert operators._pivot3_options(lvls, 0, root) == []
    up.right.rotation, up.right.division = 1, [0.4, 0.4]
    up.right.left, up.right.right = dom.Node(type="e"), dom.Node(type="f")
    operators._finalise(root)
    assert operators._pivot3_options(dom.levels(root), 0, root) != []


def test_gated_off_by_default(monkeypatch):
    from homemaker_layout import driver
    assert "pivot3" in operators.MUTATIONS
    src = Path(driver.__file__).read_text()
    assert 'os.environ.get("HOMEMAKER_PIVOT3", "") != "1"' in src
    rng = np.random.default_rng(1)
    root = _sketch(monkeypatch)
    _, label = operators.mutate_pivot3(root, rng, ["C"])
    assert label.startswith("pivot3 0/root")
    assert len(root.leaves()) == 3

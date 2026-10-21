"""`mutate_pivot` (homemaker-py-mtfo): a grid of four quadrants turned on its
other axis -- halves left and right become halves top and bottom -- with every
quadrant, and everything inside it, where it was.

The claim is about walls, so the tests measure walls: every leaf's corners,
in order, on every storey, before and after. A grid's two cross cuts are put
in line first, since a jog is the one thing the move cannot keep."""

from __future__ import annotations

import copy
import glob
import math
from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, geometry, operators

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
RECT = [[0.0, 0.0], [20.0, 0.0], [20.0, 12.0], [0.0, 12.0]]


def _artefacts() -> "list[str]":
    """One evolved artefact per programme, at the newest stamp that has all four."""
    out = []
    for prog in ("programme-house", "harbor-house", "health-centre", "maple-court"):
        found = sorted(glob.glob(str(EXAMPLES / prog / "coldstart-*+orth-500000-s0.dom")))
        if found:
            out.append(found[-1])
    if not out:
        pytest.skip("no evolved artefacts")
    return out


def _load(path, mode, tmp_path) -> dom.Node:
    root = dom.load(path)
    if mode == "native":
        v2 = tmp_path / "v2.dom"
        v2.write_text(dom.dumps(root, version=2))
        root = dom.load(str(v2), native=True)
    return operators._finalise(root)


def _grids(root):
    lvls = dom.levels(root)
    return [(li, n.id) for li, n in operators._owned_branches(root)
            if operators._pivotable(lvls, li, n)]


def _align(n) -> None:
    """Put the right half's cross cut on the left half's wall line."""
    operators._finalise(_top(n))
    y = operators._cut_pos(n.left.rotation, n.left.division[0])
    n.right.division = [operators._cut_pos(n.right.rotation, y)] * len(n.right.division)
    operators._finalise(_top(n))
    walls = operators._walls(n)
    if walls is not None:                     # quad tree: ratios are not lines
        q, d = walls[1]
        c = [geometry.coordinate(n.right, i) for i in range(4)]
        for i, (p0, p1) in enumerate(((c[0], c[1]), (c[3], c[2]))):
            t = operators._line_param(p0, p1, q, d)
            if t is not None:
                n.right.division[i] = t
    operators._finalise(_top(n))


def _top(n):
    r = n
    while r.parent is not None:
        r = r.parent
    while r.below is not None:
        r = r.below
    return r


def _tag(root) -> None:
    i = 0
    for lvl in dom.levels(root):
        for leaf in lvl.leaves():
            leaf.type = f"t{i}"
            i += 1


def _corners(root) -> dict:
    geometry.clear_cache()
    return {leaf.type: [geometry.coordinate(leaf, i) for i in range(geometry.n_edges(leaf))]
            for lvl in dom.levels(root) for leaf in lvl.leaves()}


def _shift(before, after) -> "tuple[float, int]":
    """Worst corner move over all leaves, allowing a leaf's corner numbering to
    turn (it is a label), and how many leaves only had theirs turned."""
    worst, turned = 0.0, 0
    assert before.keys() == after.keys()
    for k, b in before.items():
        a = after[k]
        if len(a) != len(b):
            return math.inf, turned
        d = min(max(math.dist(p, q) for p, q in zip(b, a[s:] + a[:s])) for s in range(len(a)))
        if d < 1e-9 and max(math.dist(p, q) for p, q in zip(b, a)) > 1e-9:
            turned += 1
        worst = max(worst, d)
    return worst, turned


@pytest.fixture(params=["orth", "skew", "native"])
def mode(request, monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", request.param != "skew")
    geometry.clear_cache()
    return request.param


def test_pivot_keeps_every_cell(mode, tmp_path):
    tested = above = 0
    for path in _artefacts():
        root = _load(path, mode, tmp_path)
        for li, nid in _grids(root):
            for seed in range(4):                 # every choice of which half is `l`
                r = operators._finalise(copy.deepcopy(root))
                lvls = dom.levels(r)
                n = lvls[li].by_id(nid)
                _align(n)
                _tag(r)
                before = _corners(r)
                operators._pivot(lvls, li, n, np.random.default_rng(seed))
                operators._finalise(r)
                assert n.rotation % 2 != dom.levels(root)[li].by_id(nid).rotation % 2
                worst, turned = _shift(before, _corners(r))
                assert worst < 1e-9, (path, li, nid, seed, worst)
                # only a cell above spanning the whole grid takes the grid's
                # (turned) corner numbering; no quadrant's numbering moves
                assert turned <= len(lvls) - 1 - li
                tested += 1
                above += any((a := lv.by_id(nid)) is not None and a.divided
                             for lv in lvls[li + 1:])
    assert tested and above, "no grid, or none with a grid above: a vacuous test"


def test_the_comparison_catches_a_moved_cell(mode, tmp_path):
    """Negative control: turning the grid's cut WITHOUT moving the quadrants
    -- what `mutate_rotate` does -- must register as moved walls."""
    root = _load(_artefacts()[0], mode, tmp_path)
    li, nid = _grids(root)[0]
    lvls = dom.levels(root)
    n = lvls[li].by_id(nid)
    _align(n)
    _tag(root)
    before = _corners(root)
    n.rotation = (n.rotation + 1) % 4
    operators._finalise(root)
    assert _shift(before, _corners(root))[0] > 0.1


def test_a_jog_goes_at_the_area_weighted_line(monkeypatch):
    """Cross cuts out of line cannot both survive one straight primary: each
    new half keeps the area of the two quadrants it is made of."""
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    root = dom.Node(node=[list(p) for p in RECT], node_file=[list(p) for p in RECT],
                    height=3.0, elevation=0.0, wall_inner=0.0, wall_outer=0.0)
    root.division, root.rotation = [0.3, 0.3], 0
    root.left = dom.Node(rotation=1, division=[0.2, 0.2])
    root.right = dom.Node(rotation=3, division=[0.4, 0.4])
    for half in (root.left, root.right):
        half.left, half.right = dom.Node(type="a"), dom.Node(type="b")
    operators._finalise(root)
    for seed in range(4):
        r = copy.deepcopy(root)
        before = {id(q): (q.type, geometry.area(q)) for q in r.leaves()}
        operators._pivot([r], 0, r, np.random.default_rng(seed))
        operators._finalise(r)
        for half in (r.left, r.right):
            old = sum(before[id(q)][1] for q in (half.left, half.right))
            assert geometry.area(half) == pytest.approx(old, rel=1e-12)


def test_refused_where_a_storey_above_keeps_only_the_halves():
    root = dom.Node(node=[list(p) for p in RECT], node_file=[list(p) for p in RECT],
                    height=3.0, elevation=0.0, wall_inner=0.0, wall_outer=0.0)
    root.division, root.left, root.right = [0.5, 0.5], dom.Node(rotation=1, division=[0.5, 0.5]), \
        dom.Node(rotation=1, division=[0.5, 0.5])
    for half in (root.left, root.right):
        half.left, half.right = dom.Node(type="a"), dom.Node(type="b")
    up = copy.deepcopy(root)
    root.above = up
    operators._finalise(root)
    assert operators._pivotable(dom.levels(root), 0, root)
    up.left.division = up.left.left = up.left.right = None
    up.left.type = "c"
    operators._finalise(root)
    assert not operators._pivotable(dom.levels(root), 0, root)
    child, desc = operators.mutate_pivot(root, np.random.default_rng(0), [])
    assert desc == "pivot noop"


def test_the_search_does_not_draw_it_unless_asked(monkeypatch):
    from homemaker_layout import driver

    PH = EXAMPLES / "harbor-house"
    if not (PH / "init.dom").exists():
        pytest.skip("examples absent")
    drawn = []
    real = operators.mutate_pivot
    monkeypatch.setitem(operators.MUTATIONS, "pivot",
                        lambda *a, **k: (drawn.append(1), real(*a, **k))[1])
    monkeypatch.delenv("HOMEMAKER_PIVOT", raising=False)
    driver.search(dom.load(str(PH / "init.dom")), str(PH), budget=1500, child_budget=20, seed=1)
    assert not drawn
    monkeypatch.setenv("HOMEMAKER_PIVOT", "1")
    driver.search(dom.load(str(PH / "init.dom")), str(PH), budget=1500, child_budget=20, seed=1)
    assert drawn, "the flagged search never drew the move: a vacuous test"

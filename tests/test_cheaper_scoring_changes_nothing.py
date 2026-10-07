"""Two ways a score was made cheaper, and the proof that neither changed it.

**Each storey's adjacency graph is built once per state of the tree**
(`homemaker-py-8b2u.11`). A score used to build every storey's graph four
times: twice before `dom.merge_divided` and twice after, the same graph each
time. It now builds it once before, and after the merge only for the storeys
the merge could have changed -- the lowest storey it touched and everything
over it, since geometry is read downwards and never upwards.

That last sentence is an argument, and this file is its test: on designs as a
search holds them (every operator applied to artefacts of two programmes, both
trees), the score with graphs kept is the score with every graph rebuilt, bit
for bit. The negative control tells the scorer the merge touched nothing when
it did, and the same comparison then has to fail -- by a different score or by
the scorer tripping over a cell that is no longer there.

**A native storey's walls are found by walking its cuts**
(`homemaker-py-8b2u.10`), not by testing every pair of cells. Held to the
all-pairs graph it replaced: the same walls, widths and end points, and the
same order. Its control hides one pair from the walk.
"""

from __future__ import annotations

import copy
import inspect
from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, dom_v2, geometry, graph, operators, programme
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parent.parent
PROGRAMMES = ("programme-house", "maple-court")

pytestmark = pytest.mark.skipif(
    not (REPO / "examples" / "maple-court").is_dir(), reason="examples absent")


@pytest.fixture(autouse=True)
def restore_switch():
    was = geometry.ORTHOGONAL_DIVISION
    yield
    geometry.ORTHOGONAL_DIVISION = was
    geometry.clear_cache()


def _designs():
    """``(fitness, tree, orthogonal switch)``: an artefact of each programme,
    quad and native, and the children every operator makes of it."""
    for name in PROGRAMMES:
        prog = REPO / "examples" / name
        path = sorted(prog.glob("coldstart-*+orth-500000-s*.dom"))[-1]
        fit = Fitness(*load_config(prog))
        reqs = programme.load_programme_dir(str(prog))
        types = sorted(reqs) + ["C", "O"]
        geometry.ORTHOGONAL_DIVISION = True
        quad = dom.load(str(path))
        native = dom_v2.to_native(quad)
        for root, orth in ((quad, True), (native, False)):
            geometry.ORTHOGONAL_DIVISION = orth
            yield fit, root, orth
            for op_name, op in sorted(operators.MUTATIONS.items()):
                params = inspect.signature(op).parameters
                kw = {k: v for k, v in (("reqs", reqs), ("fit", fit)) if k in params}
                for seed in range(2):
                    geometry.ORTHOGONAL_DIVISION = orth
                    geometry.clear_cache()
                    child, desc = op(root, np.random.default_rng(seed), types, **kw)
                    if "noop" not in desc:
                        yield fit, child, orth


def _score(fit, root, orth):
    geometry.ORTHOGONAL_DIVISION = orth
    return fit.score_with_fails(copy.deepcopy(root))


def _compare(monkeypatch, lie: bool = False):
    """Score every design as shipped and with every graph rebuilt; returns
    ``(designs, how many merged above the ground, how many differ)``. With
    `lie`, the shipped scorer is told the merge touched nothing."""
    designs = list(_designs())
    real_merge = dom.merge_divided
    seen: list = []

    def merge(root, **kw):
        seen.append(real_merge(root, **kw))
        return None if lie else seen[-1]

    monkeypatch.setattr(dom, "merge_divided", merge)
    kept = []
    for d in designs:
        try:
            kept.append(_score(*d))
        except Exception as e:          # a stale graph names cells that are gone
            assert lie, e
            kept.append(("raised", type(e).__name__))
    merged = [m for m in seen if m is not None]
    monkeypatch.setattr(dom, "merge_divided", real_merge)

    real_graphs = graph.storey_graphs
    monkeypatch.setattr(
        graph, "storey_graphs",
        lambda root, door_width, usages, reuse=None, keep=0:
            real_graphs(root, door_width, usages))
    rebuilt = [_score(*d) for d in designs]
    monkeypatch.setattr(graph, "storey_graphs", real_graphs)
    return len(designs), merged, sum(a != b for a, b in zip(kept, rebuilt))


def test_a_score_with_graphs_kept_is_the_score_with_every_graph_rebuilt(monkeypatch):
    n, merged, differ = _compare(monkeypatch)
    assert n > 60
    # the comparison must have something to compare: merges that fired, and
    # some of them above the ground floor, where graphs really are kept
    assert len(merged) > 10 and any(m > 0 for m in merged)
    assert differ == 0


def test_control_keeping_a_graph_the_merge_changed_is_caught(monkeypatch):
    _, merged, differ = _compare(monkeypatch, lie=True)
    assert merged and differ > 0


def test_one_build_per_storey_and_one_more_for_each_the_merge_could_change(monkeypatch):
    builds = []
    real = geometry.leaf_graph
    monkeypatch.setattr(geometry, "leaf_graph",
                        lambda *a, **k: builds.append(1) or real(*a, **k))
    real_merge = dom.merge_divided
    lowest = []
    monkeypatch.setattr(dom, "merge_divided",
                        lambda root, **kw: lowest.append(real_merge(root, **kw)) or lowest[-1])
    for fit, root, orth in _designs():
        del builds[:], lowest[:]
        storeys = len(dom.levels(root))
        _score(fit, root, orth)
        again = 0 if lowest[0] is None else storeys - lowest[0]
        assert len(builds) == storeys + again


def test_merge_divided_names_the_lowest_storey_it_touched():
    def building(*types_by_storey):
        lvl = prev = None
        for pair in types_by_storey:
            n = dom.Node(type=None, division=[0.5, 0.5],
                         left=dom.Node(type=pair[0]), right=dom.Node(type=pair[1]))
            if prev is None:
                lvl = n
            else:
                prev.above = n
            prev = n
        dom.link(lvl)
        return lvl

    assert dom.merge_divided(building(("l1", "k1"), ("b1", "b2"))) is None
    assert dom.merge_divided(building(("O", "O"), ("b1", "b2"))) == 0
    # half over a room and half over a garden: neither supported nor not
    assert dom.merge_divided(building(("O", "l1"), ("O", "O"))) is None
    root = building(("l1", "k1"), ("O", "O"))
    assert dom.merge_divided(root) == 1 and not root.above.divided


# --------------------------------------------------------------------------- #
# walls by walking the cuts (8b2u.10)
# --------------------------------------------------------------------------- #
ELL = [[0, 0], [12, 0], [12, 5], [5, 5], [5, 12], [0, 12]]


def _ell():
    """Two storeys on an L-shaped plot, cut finely enough that cells are void,
    cropped, and wrapped round the inner corner."""
    def grid(depth, axis="u"):
        if depth == 0:
            return {"cell": "l1"}
        other = "v" if axis == "u" else "u"
        return {"cut": axis, "at": 0.37 + 0.05 * depth,
                "low": grid(depth - 1, other), "high": grid(depth - 1, other)}

    # the storey above inherits the first two cuts and stops there
    upper = {"low": {"cell": "b1"},
             "high": {"low": {"cell": "b2"}, "high": {"cell": "C"}}}
    return dom_v2.from_document({
        "format": "homemaker-dom", "version": 2, "frame": {"u": [1.0, 0.0]},
        "plot": ELL, "wall_outer": 0.0, "wall_inner": 0.08,
        "storeys": [{"elevation": 0.0, "height": 3.0, "tree": grid(5)},
                    {"elevation": 3.0, "height": 3.0, "tree": upper}]}, native=True)


def _all_pairs(leaves, door_width):
    """The loop `geometry.leaf_graph` ran before: every pair measured."""
    from homemaker_layout import cells

    polys = [geometry.polygon(lf) for lf in leaves]
    out = []
    for i in range(len(leaves)):
        for j in range(i + 1, len(leaves)):
            width, seg = cells.shared_wall(polys[i], polys[j])
            if width >= door_width:
                out.append((i, j, width, seg))
    return out


def _walls_differ(door_width=1.2) -> "tuple[int, int, int]":
    """``(storeys, walls, storeys whose graph is not the all-pairs graph)``
    over every native design."""
    trees = [root for _, root, orth in _designs() if not orth] + [_ell()]
    storeys = walls = differ = 0
    geometry.ORTHOGONAL_DIVISION = False
    for root in trees:
        geometry.clear_cache()
        geometry.mark_voids(root)
        for lvl in dom.levels(root):
            leaves = lvl.leaves()
            at = {id(lf): i for i, lf in enumerate(leaves)}
            want = _all_pairs(leaves, door_width)
            G = geometry.leaf_graph(lvl, door_width)
            got = [(at[id(a)], at[id(b)], d["width"], d["coordinates"])
                   for a, b, d in G.edges(data=True)]
            storeys += 1
            walls += len(want)
            differ += sorted(got) != want or list(G.nodes()) != leaves \
                or [[at[id(x)] for x in G.neighbors(lf)] for lf in leaves] != _neighbours(want, len(leaves))
    return storeys, walls, differ


def _neighbours(walls, n):
    """Each cell's neighbours in the order an all-pairs loop adds them."""
    out = [[] for _ in range(n)]
    for i, j, _, _ in walls:
        out[i].append(j)
        out[j].append(i)
    return out


def test_walking_the_cuts_finds_the_walls_every_pair_tested_would():
    storeys, walls, differ = _walls_differ()
    assert storeys > 150 and walls > 5000
    assert differ == 0
    # and at a width nothing is narrower than, so that no wall is hidden by
    # the door: every stretch two cells share
    assert _walls_differ(door_width=1e-3)[2] == 0


def test_control_a_pair_the_walk_misses_is_caught(monkeypatch):
    real = geometry._native_facing
    monkeypatch.setattr(geometry, "_native_facing",
                        lambda root, leaves, dw: real(root, leaves, dw)[1:])
    assert _walls_differ()[2] > 100


def test_the_walk_measures_a_few_pairs_per_cell_not_every_pair(monkeypatch):
    from homemaker_layout import cells

    calls = []
    real = cells.shared_wall
    monkeypatch.setattr(cells, "shared_wall", lambda a, b: calls.append(1) or real(a, b))
    prog = REPO / "examples" / "maple-court"
    geometry.ORTHOGONAL_DIVISION = True
    root = dom_v2.to_native(dom.load(str(sorted(prog.glob("coldstart-*+orth-*.dom"))[-1])))
    geometry.ORTHOGONAL_DIVISION = False
    geometry.clear_cache()
    n = 0
    for lvl in dom.levels(root):
        n += len(lvl.leaves())
        geometry.leaf_graph(lvl)
    assert n > 60 and len(calls) < 4 * n

"""`mutate_swap_cells` (homemaker-py-8wgz): labels move among neighbouring cells.
No wall moves, the cells are connected in the adjacency graph, stair cells stay
out of it, and the set always holds more than one kind of cell (§39.191)."""

from __future__ import annotations

import copy
import glob
from pathlib import Path

import networkx as nx
import numpy as np
import pytest

from homemaker_layout import dom, driver, geometry, operators

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _design(prog="maple-court"):
    found = sorted(glob.glob(str(EXAMPLES / prog / "coldstart-*+orth-500000-s0.dom")))
    if not found:
        pytest.skip("no artefact")
    return operators._finalise(dom.load(found[-1]))


def _cells(root):
    geometry.clear_cache()
    return {(li, lf.id): lf for li, lvl in enumerate(dom.levels(root)) for lf in lvl.leaves()}


@pytest.fixture(autouse=True)
def orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()


@pytest.mark.parametrize("k", [2, 3, 4])
def test_labels_move_among_neighbours_and_no_wall_moves(k):
    root = _design()
    before = _cells(root)
    shape = {c: [geometry.coordinate(lf, i) for i in range(geometry.n_edges(lf))]
             for c, lf in before.items()}
    types = {c: lf.type for c, lf in before.items()}
    fired = 0
    for seed in range(30):
        child, desc = operators.mutate_swap_cells(root, np.random.default_rng(seed), [], k=k)
        if "noop" in desc:
            continue
        fired += 1
        after = _cells(child)
        assert after.keys() == before.keys()
        moved = [c for c in after if after[c].type != types[c]]
        li = moved[0][0]
        assert {c[0] for c in moved} == {li}
        ids = desc.split("/", 1)[1].split(",")
        assert len(ids) == k and {c[1] for c in moved} <= set(ids)
        # the same labels, on the storey it touched and so on all of them
        assert sorted(str(lf.type) for lf in after.values()) == sorted(str(t) for t in types.values())
        graph = geometry.leaf_graph(dom.levels(child)[li])
        nodes = [dom.levels(child)[li].by_id(i) for i in ids]
        assert nx.is_connected(graph.subgraph(nodes))
        assert all(after[(li, i)].type != dom.GENERIC_STAIR for i in ids)
        assert len({operators._kind(types[(li, i)]) for i in ids}) > 1
        for c, lf in after.items():
            pts = [geometry.coordinate(lf, i) for i in range(geometry.n_edges(lf))]
            assert np.allclose(pts, shape[c], atol=1e-9), c
    assert fired > 10


def test_the_connection_check_can_fail():
    """Negative control: two cells drawn without the graph are not all neighbours."""
    root = _design()
    lvl = dom.levels(root)[0]
    geometry.clear_cache()
    graph = geometry.leaf_graph(lvl)
    leaves = lvl.leaves()
    assert any(not nx.is_connected(graph.subgraph([a, b]))
               for a in leaves[:6] for b in leaves[:6] if a is not b)


def test_a_stair_is_never_taken():
    root = _design()
    lvl = dom.levels(root)[0]
    for seed in range(40):
        rng = np.random.default_rng(seed)
        start = operators._pick(rng, [lf for lf in lvl.leaves() if lf.type != "E"])
        geometry.clear_cache()
        assert all(c.type != "E" for c in operators._adjacent_cells(lvl, start, 4, rng))


def test_a_design_with_only_rooms_declines():
    root = copy.deepcopy(_design())
    for lvl in dom.levels(root):
        for lf in lvl.leaves():
            lf.type = "x1"
    _, desc = operators.mutate_swap_cells(root, np.random.default_rng(0), [])
    assert "noop" in desc


def test_off_by_default():
    assert "swap_cells" in operators.MUTATIONS
    assert 'os.environ.get("HOMEMAKER_SWAP_CELLS", "") != "1"' in Path(driver.__file__).read_text()

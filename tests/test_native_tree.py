"""The native rectangle-frame tree (`homemaker-py-8b2u.4`, DESIGN.md §39.103).

A format-v2 file loaded with `native=True` is not fitted into Urb's quad tree:
each divided node keeps the line the file gives it, and `geometry` draws the
building by splitting the frame rectangle and cropping to the plot. Two halves
again. Every design the quad tree can hold must score THE SAME as a native
tree -- that is the gate. And the designs it cannot hold must score at all,
and sensibly.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest
import yaml

from homemaker_layout import dom, dom_v2, fitness_cmd, geometry, graph
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parent.parent
PH = REPO / "examples" / "programme-house"
DIAG = REPO / "experiments" / "diag_8b2u2_roundtrip.py"

LEANING = [[0, 0], [20, 0], [20, 10], [12, 10]]       # left side leans in
ELL = [[0, 0], [12, 0], [12, 5], [5, 5], [5, 12], [0, 12]]


def _doc(plot, *trees, **over) -> dict:
    d = {"format": "homemaker-dom", "version": 2, "frame": {"u": [1.0, 0.0]},
         "plot": plot, "wall_outer": 0.0, "wall_inner": 0.08,
         "storeys": [{"elevation": 3.0 * i, "height": 3.0, "tree": t}
                     for i, t in enumerate(trees)]}
    d.update(over)
    return d


def _native(doc) -> dom.Node:
    return dom_v2.from_document(doc, native=True)


def _score(root):
    conf, cost = load_config(PH)
    return Fitness(conf, cost).score_with_fails(root)


def _by_type(root, storey=0):
    return {lf.type: lf for lf in dom.levels(root)[storey].leaves()}


@pytest.fixture(autouse=True)
def switch_off(monkeypatch):
    """A native tree has one geometry. Nothing here may depend on the
    orthogonal-division switch, so it is held OFF throughout."""
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", False)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


# --------------------------------------------------------------------------- #
# what only a native tree can hold
# --------------------------------------------------------------------------- #
WEDGE_TREE = {"cut": "u", "at": 0.5, "low": {"cell": "l1"},
              "high": {"cut": "v", "at": 0.5,
                       "low": {"cell": "k1"}, "high": {"cell": "b1"}}}


def test_a_room_cropped_to_a_wedge_is_drawn_and_fails_on_shape():
    root = _native(_doc(LEANING, WEDGE_TREE))
    wedge = _by_type(root)["k1"]
    assert geometry.n_edges(wedge) == 3
    assert geometry.area(wedge) == pytest.approx(0.5 * 4 * (10 * 10 / 12 - 5))
    assert geometry.quad_corners(wedge) is None
    score, fails = _score(root)
    assert math.isfinite(score) and score >= 0
    assert "0/rl shape" in fails
    assert not any("rr shape" in f or "/l shape" in f for f in fails)


def test_the_same_wedge_as_ground_level_garden_is_not_asked_about_its_shape():
    tree = yaml.safe_load(yaml.safe_dump(WEDGE_TREE))
    tree["high"]["low"]["cell"] = "O"
    _, fails = _score(_native(_doc(LEANING, tree)))
    assert not any(f.endswith(" shape") for f in fails)


def test_a_cell_outside_the_plot_is_in_the_file_and_in_no_loop():
    tree = {"cut": "u", "at": 0.5, "low": {"cell": "l1"},
            "high": {"cut": "v", "at": 0.25, "low": {"cell": "k1"}, "high": {"cell": "b1"}}}
    doc = _doc(LEANING, tree)
    root = _native(doc)
    gone = root.by_id("rl")
    assert gone.void and gone.type == "k1"
    assert [lf.type for lf in root.leaves()] == ["l1", "b1"]
    assert yaml.safe_load(dom.dumps(root, version=2))["storeys"][0]["tree"] == tree
    score, fails = _score(root)
    assert math.isfinite(score)
    assert not any(f.startswith("0/rl ") for f in fails)       # nothing is said of it


def test_an_l_shaped_plot_two_storeys_with_a_status_vertex():
    """Six corners plus a collinear vertex where the street side becomes a
    party wall. The notch is two empty cells, one per storey; the cell against
    the split side has an edge on each half of it."""
    plot = [[0, 0], [7, 0]] + ELL[1:]
    tree = {"cut": "v", "at": 5 / 12,
            "low": {"cut": "u", "at": 5 / 12, "low": {"cell": "l1"}, "high": {"cell": "C"}},
            "high": {"cut": "u", "at": 5 / 12, "low": {"cell": "k1"}, "high": {"cell": "O"}}}
    upper = {"low": {"low": {"cell": "b1"}, "high": {"cell": "C"}},
             "high": {"low": {"cell": "b2"}, "high": {"cell": "O"}}}
    root = _native(_doc(plot, tree, upper,
                        perimeter=["street", "party", None, None, None, None, "private"]))
    for lvl in dom.levels(root):
        assert [lf.type for lf in lvl.leaves()][-1] != "O"      # the notch is void
        assert sum(geometry.area(lf) for lf in lvl.leaves()) == pytest.approx(
            12 * 12 - 7 * 7)
    k1 = _by_type(root)["k1"]
    sides = [geometry.boundary_id(k1, e) for e in range(geometry.n_edges(k1))]
    assert "#0" in sides and "#1" in sides                       # both halves of the side
    assert root.perimeter["#0"] == "street" and root.perimeter["#6"] == "private"
    G = geometry.leaf_graph(root)
    assert {frozenset((a.type, b.type)) for a, b in G.edges()} == {
        frozenset(("l1", "C")), frozenset(("l1", "k1"))}
    score, fails = _score(root)
    assert math.isfinite(score) and score > 0
    assert not any(f.endswith(" shape") for f in fails)


def test_a_frame_of_the_files_own_needs_no_switch():
    r = math.sqrt(0.5)
    diamond = [[0, 0], [10 * r, 10 * r], [0, 20 * r], [-10 * r, 10 * r]]
    root = _native(_doc(diamond, {"cut": "v", "at": 0.4,
                                  "low": {"cell": "l1"}, "high": {"cell": "k1"}},
                        frame={"u": [r, r]}))
    cells_ = _by_type(root)
    assert geometry.usable_rectangle(cells_["l1"]) == pytest.approx((4.0, 10.0))
    assert geometry.usable_rectangle(cells_["k1"]) == pytest.approx((6.0, 10.0))
    with pytest.raises(dom_v2.DomFormatError):                  # the quad tree cannot
        dom_v2.from_document(_doc(diamond, {"cell": "l1"}, frame={"u": [r, r]}))


def test_a_stair_is_fitted_to_a_four_cornered_core_only():
    square = [[0, 0], [10, 0], [10, 10], [0, 10]]
    tree = {"cut": "v", "at": 0.5, "low": {"cell": "E"}, "high": {"cell": "l1"}}
    upper = {"low": {"cell": "E"}, "high": {"cell": "b1"}}
    clipped = [[0, 0], [10, 0], [10, 10], [2, 10], [0, 7]]      # the core loses a corner
    for plot, want in ((square, True), (clipped, False)):
        root = _native(_doc(plot, tree, upper))
        lvls = dom.levels(root)
        graphs = [geometry.leaf_graph(lv) for lv in lvls]
        core = _by_type(root)["E"]
        assert bool(graph.stack_corners_in_use(core, graphs, lvls)) is want


def test_merging_outdoor_cells_below_keeps_the_native_wall_above():
    square = [[0, 0], [10, 0], [10, 10], [0, 10]]
    tree = {"cut": "v", "at": 0.3, "low": {"cell": "O"}, "high": {"cell": "O"}}
    upper = {"low": {"cell": "b1"}, "high": {"cell": "b2"}}
    root = _native(_doc(square, tree, upper))
    up = dom.levels(root)[1]
    up.division = [0.9, 0.9]                                    # stale, as v1's are
    geometry.clear_cache()
    assert geometry._native_cut(up)[:2] == ("v", pytest.approx(3.0))
    dom.merge_divided(root)
    geometry.clear_cache()
    assert not root.divided and dom.levels(root)[1].divided
    assert geometry._native_cut(dom.levels(root)[1])[:2] == ("v", pytest.approx(3.0))


def test_homemaker_fitness_scores_a_v2_file_natively(tmp_path):
    for cfg in PH.glob("*.config"):
        (tmp_path / cfg.name).write_text(cfg.read_text())
    path = tmp_path / "odd.dom"
    path.write_text(yaml.safe_dump(_doc(LEANING, WEDGE_TREE), sort_keys=False))
    conf, cost = load_config(tmp_path)
    fitness_cmd.score_file(path, Fitness(conf, cost))
    assert "0/rl shape" in (tmp_path / "odd.dom.fails").read_text().splitlines()
    assert float((tmp_path / "odd.dom.score").read_text()) >= 0


# --------------------------------------------------------------------------- #
# the gate
# --------------------------------------------------------------------------- #
def _diag():
    spec = importlib.util.spec_from_file_location("_rt", DIAG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


needs_corpus = pytest.mark.skipif(
    not (REPO / "examples" / "maple-court").is_dir(), reason="examples absent")


def _native_and_quad_scores(rt, nudge=0.0):
    """Every orthogonal artefact scored as the quad tree it is and as the
    native tree of the same building; returns how many scores or fail counts
    differ. `nudge` moves one cut of the native tree (the negative control)."""
    differ = 0
    for p, prog in rt.corpus():
        geometry.ORTHOGONAL_DIVISION = True         # the v1 file's own convention
        quad = dom.load(str(p))
        doc = dom_v2.to_document(quad)
        s0, f0 = rt.score(quad, prog)
        geometry.ORTHOGONAL_DIVISION = False        # ...which a native tree ignores
        if nudge:
            doc["storeys"][0]["tree"]["at"] += nudge
        s1, f1 = rt.score(dom_v2.from_document(doc, native=True), prog)
        differ += rt.differs(s0, s1, 1e-6) or len(f0) != len(f1)
    return differ


@needs_corpus
def test_every_orthogonal_artefact_scores_the_same_as_a_native_tree():
    """192 designs, each drawn two ways -- Urb's quad recursion with orthogonal
    division, and a rectangle split and cropped -- and scored by one scorer:
    the same score and the same fails, every one."""
    assert _native_and_quad_scores(_diag()) == 0


@needs_corpus
def test_control_a_native_tree_with_one_cut_moved_scores_differently():
    assert _native_and_quad_scores(_diag(), nudge=0.01) > 100


# --------------------------------------------------------------------------- #
# the search edits a native tree with the genes it always had (§39.104)
# --------------------------------------------------------------------------- #
def _native_artefact():
    from homemaker_layout import programme

    path = sorted(PH.glob("coldstart-1a24b6a+orth-500000-s*.dom"))[0]
    geometry.ORTHOGONAL_DIVISION = True
    quad = dom.load(str(path))
    root = dom_v2.to_native(quad)
    geometry.ORTHOGONAL_DIVISION = False
    reqs = programme.load_programme_dir(str(PH))
    return root, reqs, sorted(reqs) + ["C", "O"]


@needs_corpus
def test_every_operator_edits_a_native_tree_and_the_genome_carries_it():
    """Rotation and ratio mean on a rectangle what they meant on a quad, so
    no operator had to be rewritten -- which is a claim, and this is its test:
    each one applied to a native design gives a native child that scores, and
    that survives the genome with the same score."""
    import inspect

    import numpy as np

    from homemaker_layout import genome, operators

    root, reqs, types = _native_artefact()
    conf, cost = load_config(PH)
    fit = Fitness(conf, cost)
    fired = set()
    for name, op in sorted(operators.MUTATIONS.items()):
        params = inspect.signature(op).parameters
        kw = {k: v for k, v in (("reqs", reqs), ("fit", fit)) if k in params}
        for seed in range(4):
            geometry.clear_cache()
            child, desc = op(root, np.random.default_rng(seed), types, **kw)
            assert child.plot is not None, name
            if "noop" in desc:
                continue
            fired.add(name)
            score, _ = fit.score_with_fails(child)
            assert math.isfinite(score), name
            back = genome.decode(genome.encode(child))
            assert back.plot == child.plot and back.frame_u == child.frame_u, name
            assert fit.score_with_fails(back)[0] == pytest.approx(score, rel=1e-9), name
    assert len(fired) >= 12


@needs_corpus
def test_a_native_tree_the_search_has_turned_round_is_written_and_read_back():
    """The reader always puts `low` on the left. The search does not: half its
    cuts start from the far side, and the left child is then the HIGH one.
    The writer has to say so in the frame's terms."""
    import numpy as np

    from homemaker_layout import dom_upgrade_cmd, operators

    root, _reqs, types = _native_artefact()
    rng = np.random.default_rng(3)
    for _ in range(12):
        root, _ = operators.mutate_rotate(root, rng, types)
        root, _ = operators.mutate_swap(root, rng, types)
    assert any(not geometry._native_cut(n)[2]
               for lvl in dom.levels(root) for n in _divided(lvl))
    text = dom.dumps(root, version=2)
    back = dom_v2.from_document(yaml.safe_load(text), native=True)
    assert dom_upgrade_cmd.unmatched_cells(root, back) == 0
    assert dom.dumps(back, version=2) == text


def _divided(n):
    if n.divided:
        yield n
        yield from _divided(n.left)
        yield from _divided(n.right)


def _evolve(tmp_path, seed_doc_or_none, budget=250):
    from homemaker_layout import evolve

    for cfg in PH.glob("*.config"):
        (tmp_path / cfg.name).write_text(cfg.read_text())
    if seed_doc_or_none is None:
        (tmp_path / "init.dom").write_text((PH / "init.dom").read_text())
    else:
        (tmp_path / "init.dom").write_text(yaml.safe_dump(seed_doc_or_none, sort_keys=False))
    out = tmp_path / "out.dom"
    import os
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert evolve.main(["init.dom", "--budget", str(budget), "--seed", "0",
                            "--workers", "1", "--native", "--output", str(out)]) == 0
    finally:
        os.chdir(cwd)
    return out


def test_homemaker_evolve_native_from_a_v1_seed_writes_v2(tmp_path):
    out = _evolve(tmp_path, None)
    doc = yaml.safe_load(out.read_text())
    assert (doc["format"], doc["version"]) == ("homemaker-dom", 2)
    root = dom.load(str(out), native=True)
    assert root.plot is not None and len(dom.levels(root)) >= 1
    assert math.isfinite(_score(root)[0])


def test_homemaker_evolve_native_on_an_l_shaped_plot(tmp_path):
    """What the pivot was for: a plot Urb's quad tree cannot even load."""
    plot = [[0, 0], [14, 0], [14, 7], [7, 7], [7, 13], [0, 13]]
    seed = _doc(plot, {"cell": None}, wall_outer=0.25,
                perimeter=["street", None, None, None, None, "private"])
    root = dom.load(str(_evolve(tmp_path, seed)), native=True)
    assert len(root.plot) == 6
    inner = 14 * 13 - 7 * 6 - 0.25 * (2 * (14 + 13)) + 4 * 0.0625
    for lvl in dom.levels(root):
        assert lvl.leaves()
        assert sum(geometry.area(lf) for lf in lvl.leaves()) == pytest.approx(inner)
    assert math.isfinite(_score(root)[0])

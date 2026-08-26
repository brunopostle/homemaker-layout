"""Tests for the finish-time global cell→room collapse (homemaker-py-94g).

Covers the contracts of Fitness.collapse_global / collapse_finish:
  - global relabel to the demand set (larger cell → larger target)
  - hard level constraint (never introduce a wrong-level fail)
  - c/o/s partition exclusion (circulation/structure cells are never relabelled)
  - no-op safety (no programme) and the keep-better wrapper
"""

from homemaker_layout import geometry
from homemaker_layout.dom import Node, _link_subtree
from homemaker_layout.fitness import Fitness


def _two_leaf_root(t_left: str, t_right: str, side: float = 6.0, div: float = 0.4):
    geometry.clear_cache()
    root = Node(
        node=[[0, 0], [side, 0], [side, side], [0, side]],
        rotation=0, division=[div, div],
        left=Node(type=t_left), right=Node(type=t_right),
    )
    _link_subtree(root, None, "")
    return root


def _conf(spaces, **extra):
    return {"spaces": spaces, **extra}


# --------------------------------------------------------------------------- #
# Global relabel
# --------------------------------------------------------------------------- #

def test_relabels_to_demand_set():
    # two leaves both typed b1; demand {b1, b2} — collapse spreads them so the
    # larger cell takes the larger target (b1=16) and the smaller takes b2=12.
    conf = _conf({
        "b1": {"size": [16.0, 4.0], "width": [4.0, 1.0], "proportion": [1.5, 0.5]},
        "b2": {"size": [12.0, 3.0], "width": [3.5, 0.8], "proportion": [1.5, 0.5]},
    })
    fit = Fitness(conf=conf)
    root = _two_leaf_root("b1", "b1")
    left, right = root.leaves()
    assert geometry.area(right) > geometry.area(left)

    fit.collapse_global(root)

    assert sorted(lf.type for lf in root.leaves()) == ["b1", "b2"]
    assert right.type == "b1"
    assert left.type == "b2"


# --------------------------------------------------------------------------- #
# Hard level constraint
# --------------------------------------------------------------------------- #

def test_level_constraint_never_assigns_wrong_level():
    # b2 requires level 1; a single-storey tree is all level 0, so no leaf may
    # take b2 — both stay b1 rather than gaining a wrong-level fail.
    conf = _conf({
        "b1": {"size": [16.0, 4.0]},
        "b2": {"size": [12.0, 3.0], "level": 1},
    })
    fit = Fitness(conf=conf)
    root = _two_leaf_root("b1", "b1")
    fit.collapse_global(root)
    assert all(lf.type == "b1" for lf in root.leaves())
    assert "b2" not in {lf.type for lf in root.leaves()}


# --------------------------------------------------------------------------- #
# c/o/s partition exclusion
# --------------------------------------------------------------------------- #

def test_cos_prefixed_cells_are_not_relabelled():
    # A GENERIC circulation leaf is skeleton — never relabelled, never a demand
    # slot. This used to be written with a programme code ("cr1") that collided
    # with the c* prefix; programme codes can no longer do that at all, since
    # programme.validate_codes rejects them at load (homemaker-py-ju3, DESIGN.md
    # §39.2), so the exclusion is now tested with the generic type it is for.
    conf = _conf({"b1": {"size": [16.0, 4.0]}})
    fit = Fitness(conf=conf)
    root = _two_leaf_root("C", "b1")
    fit.collapse_global(root)
    assert sorted(lf.type for lf in root.leaves()) == ["C", "b1"]


# --------------------------------------------------------------------------- #
# No-op safety + defaults
# --------------------------------------------------------------------------- #

def test_no_programme_is_noop():
    fit = Fitness(conf={})
    root = _two_leaf_root("b1", "b1")
    fit.collapse_global(root)
    assert [lf.type for lf in root.leaves()] == ["b1", "b1"]


def test_single_code_is_noop():
    # one assignable code, count 2 → demand == supply of the same code → no change
    conf = _conf({"b1": {"size": [16.0, 4.0], "count": 2}})
    fit = Fitness(conf=conf)
    root = _two_leaf_root("b1", "b1")
    fit.collapse_global(root)
    assert [lf.type for lf in root.leaves()] == ["b1", "b1"]


# --------------------------------------------------------------------------- #
# 2-opt local search beyond the Jacobi plateau (homemaker-py-9wi)
# --------------------------------------------------------------------------- #

def _four_leaf_chain(t1: str, t2: str, t3: str, t4: str, width: float = 1.0, height: float = 2.0):
    # A 1x4 strip of equal cells split twice at 0.5: the leaf-adjacency graph
    # is a chain (1-2, 2-3, 3-4) with no 1-3/2-4 edges -- see build_graphs.
    geometry.clear_cache()
    left = Node(rotation=0, division=[0.5, 0.5], left=Node(type=t1), right=Node(type=t2))
    right = Node(rotation=0, division=[0.5, 0.5], left=Node(type=t3), right=Node(type=t4))
    root = Node(
        node=[[0, 0], [4 * width, 0], [4 * width, height], [0, height]],
        rotation=0, division=[0.5, 0.5],
        left=left, right=right,
    )
    _link_subtree(root, None, "")
    return root


def test_two_opt_polish_escapes_jacobi_plateau():
    # Two adjacency pairs (p1<->p2, q1<->q2) on a 4-cell chain p1-q1-p2-q2.
    # Every code shares identical size/width/proportion targets (all four
    # cells are geometrically identical), so the ONLY thing that can prefer
    # one labelling over another is adjacency -- isolating the effect.
    #
    # Starting interleaved (p1,q1,p2,q2), the true optimum interleaves the
    # OTHER way (p1,p2 adjacent + q1,q2 adjacent, 4 satisfied requirements),
    # but the Jacobi relaxation (adjacency bonus computed from the PREVIOUS
    # round's neighbour labels, re-solved synchronously) 2-cycles between two
    # states that each satisfy 0 requirements and never reaches it -- a
    # textbook case of the quadratic-assignment plateau the issue describes.
    # 2-opt, tried after the Jacobi fixpoint, finds the escaping swap.
    spec = {
        "size": [2.0, 1.0], "width": [1.0, 1.0], "proportion": [2.0, 1.0], "count": 1,
    }
    conf = _conf({
        "p1": {**spec, "adjacency": ["p2"]},
        "p2": {**spec, "adjacency": ["p1"]},
        "q1": {**spec, "adjacency": ["q2"]},
        "q2": {**spec, "adjacency": ["q1"]},
    })
    fit = Fitness(conf=conf)

    def satisfied(root):
        from homemaker_layout import graph as graph_mod
        G = graph_mod.build_graphs(root, 1.2)[0]
        prog = fit._programme
        return sum(
            1
            for lf in root.leaves()
            for ac in prog[lf.type].adjacency
            if graph_mod.has_adjacency(lf, ac, G)
        )

    root_jacobi = _four_leaf_chain("p1", "q1", "p2", "q2")
    fit.collapse_global(root_jacobi, adjacency=True, local_search=False)
    assert satisfied(root_jacobi) == 0  # the Jacobi-only plateau

    root_polished = _four_leaf_chain("p1", "q1", "p2", "q2")
    fit.collapse_global(root_polished, adjacency=True, local_search=True)
    assert satisfied(root_polished) == 4  # 2-opt reaches the true optimum


# --------------------------------------------------------------------------- #
# Stale leaf-share must not leak into a hypothetical candidate (homemaker-py-iio)
# --------------------------------------------------------------------------- #

def test_collapse_value_ignores_stale_share_for_hypothetical_code():
    # A leaf that once held a live share (share>1, share_type==its type at the
    # time) but was since retyped away carries stale share/share_type
    # metadata -- graph.leaf_share's docstring: any retype silently
    # invalidates a stale share, guarded everywhere by share_type==type. But
    # _collapse_value probes a hypothetical candidate by temporarily
    # overwriting leaf.type, and graph.leaf_share reads that overwritten
    # type -- so a stale share_type that happens to equal the CANDIDATE code
    # must not spuriously reactivate; only the leaf's own real current type
    # may legitimately carry a live share.
    conf = _conf({"b1": {"size": [16.0, 4.0], "width": [4.0, 1.0], "proportion": [1.5, 0.5]}},
                 leaf_sharing=True)
    fit = Fitness(conf=conf)
    prog = fit._programme
    forbid, fail_w = fit._COLLAPSE_FORBID, fit._COLLAPSE_FAIL_W

    stale_leaf, _ = _two_leaf_root("other", "other").leaves()
    stale_leaf.type = "other"
    stale_leaf.share = 3
    stale_leaf.share_type = "b1"  # stale: leaf is not currently typed "b1"
    val_stale = fit._collapse_value(stale_leaf, "b1", 0, prog, "quality", forbid, fail_w)

    clean_leaf, _ = _two_leaf_root("other", "other").leaves()
    clean_leaf.type = "other"  # share stays at the default 1 / share_type None
    val_clean = fit._collapse_value(clean_leaf, "b1", 0, prog, "quality", forbid, fail_w)

    assert val_stale == val_clean

    # But the leaf's OWN current type still legitimately carries a live share.
    live_leaf, _ = _two_leaf_root("b1", "b1").leaves()
    live_leaf.type = "b1"
    live_leaf.share = 3
    live_leaf.share_type = "b1"
    val_live_self = fit._collapse_value(live_leaf, "b1", 0, prog, "quality", forbid, fail_w)
    assert val_live_self != val_clean


def test_collapse_global_dump_reload_agree_with_stale_share(tmp_path):
    # End-to-end regression for the bug: a stale share/share_type surviving
    # in-memory but dropped by dom.dump/dom.load (dom._emit only serialises
    # share while share_type==type) must not change collapse_global's
    # relabelling -- before the fix it did, because the stale metadata leaked
    # into the Hungarian assignment's candidate valuation and swayed it to
    # relabel the WRONG leaf (right, physically a poor fit for "b2") instead
    # of the size-appropriate one, purely because right's stale share_type
    # happened to equal that candidate code.
    from homemaker_layout import dom

    conf = _conf({
        "b1": {"size": [16.0, 4.0], "width": [4.0, 1.0], "proportion": [1.5, 0.5]},
        "b2": {"size": [10.8, 2.0], "width": [3.5, 0.8], "proportion": [1.5, 0.5]},
    }, leaf_sharing=True)

    def _make_root():
        root = _two_leaf_root("b1", "b1")
        _left, right = root.leaves()
        right.share = 2
        right.share_type = "b2"  # stale: right is currently typed "b1", not "b2"
        return root

    live = _make_root()
    Fitness(conf=conf).collapse_global(live)

    path = tmp_path / "stale_share.dom"
    dumped = _make_root()
    dom.dump(dumped, str(path))
    reloaded = dom.load(str(path))
    Fitness(conf=conf).collapse_global(reloaded)

    live_types = [lf.type for lf in live.leaves()]
    reloaded_types = [lf.type for lf in reloaded.leaves()]
    assert live_types == reloaded_types
    # And it's the size-consistent labelling in both cases (left, the smaller
    # leaf, takes the smaller-target b2; not the stale-share-swayed choice).
    assert live_types == ["b2", "b1"]


def test_collapse_global_commit_does_not_resurrect_stale_share(tmp_path):
    # homemaker-py-r5a: unlike the iio bug above (a stale stamp swaying which
    # CANDIDATE code wins), this is the COMMIT door -- collapse_global's own
    # assignment relabels the leaf back to the code its stale share_type
    # names, so share_type == type becomes true again "for real" and the
    # leaf would resurrect a share=3 credit for area that was never sized
    # for 3 rooms. Demand/sizes mirror test_relabels_to_demand_set (two
    # identically-typed leaves of different area spread across two demand
    # codes by size fit) so collapse is EXPECTED to move the smaller (left)
    # leaf onto "n" -- exactly the stale share_type stamped on it below.
    from homemaker_layout import dom

    conf = _conf({
        "b1": {"size": [16.0, 4.0], "width": [4.0, 1.0], "proportion": [1.5, 0.5]},
        "n": {"size": [12.0, 3.0], "width": [3.5, 0.8], "proportion": [1.5, 0.5]},
    }, leaf_sharing=True)

    def _make_root():
        root = _two_leaf_root("b1", "b1")
        left, _right = root.leaves()
        left.share = 3
        left.share_type = "n"  # stale: left is currently typed "b1", not "n"
        return root

    live = _make_root()
    Fitness(conf=conf).collapse_global(live)
    left, right = live.leaves()
    # Collapse did relabel left back onto "n" (the scenario the bug needs)...
    assert left.type == "n"
    # ...but the resurrected-looking match must not carry a share credit --
    # the stamp predates this assignment and was never re-verified.
    assert not (left.share > 1 and left.share_type == left.type)

    path = tmp_path / "stale_share_commit.dom"
    dumped = _make_root()
    dom.dump(dumped, str(path))
    reloaded = dom.load(str(path))
    Fitness(conf=conf).collapse_global(reloaded)

    assert [lf.type for lf in live.leaves()] == [lf.type for lf in reloaded.leaves()]
    assert [lf.share for lf in live.leaves()] == [lf.share for lf in reloaded.leaves()]
    assert (
        [lf.share_type for lf in live.leaves()]
        == [lf.share_type for lf in reloaded.leaves()]
    )


def test_collapse_finish_is_keep_better_and_unmerged():
    # collapse_finish returns (tree, base, collapsed, applied); the tree it hands
    # back is unmerged (leaves still carry their divisions), and collapsed<=base.
    conf = _conf({
        "b1": {"size": [16.0, 4.0], "width": [4.0, 1.0], "proportion": [1.5, 0.5]},
        "b2": {"size": [12.0, 3.0], "width": [3.5, 0.8], "proportion": [1.5, 0.5]},
    })
    fit = Fitness(conf=conf)
    root = _two_leaf_root("b1", "b1")
    tree, base_f, coll_f, applied = fit.collapse_finish(root)
    assert coll_f <= base_f
    assert applied == (coll_f < base_f) or coll_f == base_f
    assert len(tree.leaves()) == 2  # unmerged: both room leaves intact


def test_collapse_finish_guard_is_canonical_even_with_insearch_collapse_on():
    # homemaker-py-sd3 regression: score_with_fails auto-collapses BEFORE
    # counting fails whenever the Fitness instance itself is configured with
    # collapse_insearch=True (as driver.collapse_best used to build its
    # evaluator). That silently made base_fails equal the ALREADY-collapsed
    # count, so the 94g keep-better guard compared a collapsed tree against a
    # collapsed tree and could never see collapse_global's true effect.
    # collapse_finish must force canonical (collapse_insearch=False) scoring
    # for its own base/collapsed measurement regardless of self's conf.
    conf = _conf({
        "b1": {"size": [16.0, 4.0], "width": [4.0, 1.0], "proportion": [1.5, 0.5]},
        "b2": {"size": [12.0, 3.0], "width": [3.5, 0.8], "proportion": [1.5, 0.5]},
    }, collapse_insearch=True)
    fit = Fitness(conf=conf)
    assert fit._collapse_insearch is True
    root = _two_leaf_root("b1", "b1")  # both b1 -> missing b2 is a real fail

    tree, base_f, coll_f, applied = fit.collapse_finish(root)

    # canonical base: the pre-collapse tree really is missing b2 -- if the
    # guard were still vacuous, base_f would already equal coll_f (both
    # silently pre-collapsed) instead of reporting the true starting fail.
    assert base_f >= 1
    assert coll_f < base_f
    assert applied
    assert sorted(lf.type for lf in tree.leaves()) == ["b1", "b2"]
    # collapse_finish must not leak its temporary override back onto self.
    assert fit._collapse_insearch is True

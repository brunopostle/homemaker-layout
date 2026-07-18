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
    # cr1 collides with the c* (circulation) convention the scorer counts against,
    # so it is skeleton — never relabelled and never a demand slot.
    conf = _conf({
        "cr1": {"size": [20.0, 4.0]},
        "b1": {"size": [16.0, 4.0]},
    })
    fit = Fitness(conf=conf)
    root = _two_leaf_root("cr1", "b1")
    fit.collapse_global(root)
    assert sorted(lf.type for lf in root.leaves()) == ["b1", "cr1"]


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

"""`merge_divided` must not mint a type the programme has switched off (§39.66).

`homemaker-py-4e7`, the owner's observation: a programme-house model showed its
ground-floor outdoor space labelled *sahn*, which is inert because sahn
circulation is off -- so it should have read *Outside*.

The search was not at fault. Both ground-floor outdoor leaves are `O` in the
genome and in the written `.dom`. The `S` was minted afterwards, by the merge:

* `Fitness.preprocess_building` converts every `S` to `O` when
  `allow_sahn_circulation` is falsey -- the default, and every corpus programme;
* `dom.merge_divided` then ran and minted fresh `S` leaves, sixteen lines later;
* nothing converted those.

`preprocess_building` cannot be the cleanup, because its own docstring says it
must run BEFORE the merge "because it changes merge outcomes" -- which is exactly
why. So the rule lives in the merge, stated once.

**This is not a cosmetic label**, which is what these tests mostly exist to pin.
`dom.is_circulation` is True for `S` and False for `O`, so a minted sahn joins the
circulation graph, counts for access and connectivity, satisfies a neighbour's
`adjacency: [c]`, and takes the `uncrinkliness_circulation` family. Measured on
the corpus: removing them costs **+2 `access` fails** on health-centre s2, which
had four -- two spaces that were only ever reachable through a sahn the
configuration says does not exist.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from homemaker_layout import dom, fitness, genome, geometry
from homemaker_layout.dom import Node

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CORNERS = [[0, 0], [12, 0], [12, 8], [0, 8]]


def _ground_pair(left: str, right: str) -> Node:
    """A single-storey plot split in two. With nothing below, `is_supported` and
    `is_unsupported` are both False (no below-leaves at all), so the merge falls
    through to its ground-floor branch -- the one that mints the sahn."""
    g = Node(node=[list(c) for c in CORNERS], height=3.0, elevation=0.0,
             division=[0.5, 0.5], rotation=0,
             left=Node(type=left), right=Node(type=right))
    dom.link(g)
    geometry.clear_cache()
    return g


# --------------------------------------------------------------------------- #
# the parameter, both ways
# --------------------------------------------------------------------------- #
def test_the_ground_floor_merge_mints_outside_by_default():
    root = _ground_pair("O", "O")
    dom.merge_divided(root)
    leaf, = root.leaves()
    assert leaf.type == "O"


def test_the_ground_floor_merge_still_mints_a_sahn_when_asked():
    """The parameter has to work both ways, or a programme that enables sahn
    circulation silently loses the feature."""
    root = _ground_pair("O", "O")
    dom.merge_divided(root, allow_sahn=True)
    leaf, = root.leaves()
    assert leaf.type == "S"


def test_the_default_matches_the_config_default():
    """Omitting the argument must give what every corpus programme asks for.
    Defaulting the other way would reproduce the defect by omission, which is
    how it survived in the first place."""
    assert not fitness.CONF_DEFAULTS["allow_sahn_circulation"]
    root = _ground_pair("O", "O")
    dom.merge_divided(root)
    assert root.leaves()[0].type == "O"


# --------------------------------------------------------------------------- #
# why it is not cosmetic
# --------------------------------------------------------------------------- #
def test_a_minted_sahn_would_be_circulation_and_an_outside_leaf_is_not():
    """The whole consequence in one assertion: this is what
    `allow_sahn_circulation = 0` exists to switch off."""
    sahn = _ground_pair("O", "O")
    dom.merge_divided(sahn, allow_sahn=True)
    outside = _ground_pair("O", "O")
    dom.merge_divided(outside)

    s, o = sahn.leaves()[0], outside.leaves()[0]
    assert dom.is_outside(s) and dom.is_outside(o), "both are outdoor space"
    assert dom.is_circulation(s) is True
    assert dom.is_circulation(o) is False


def test_a_sahn_satisfies_an_adjacency_c_requirement_and_an_outside_leaf_does_not():
    from homemaker_layout import graph as graph_mod
    assert graph_mod.code_matches_requirement("S", "c") is True
    assert graph_mod.code_matches_requirement("O", "c") is False


# --------------------------------------------------------------------------- #
# the cascade, and the scoring path
# --------------------------------------------------------------------------- #
def test_a_minted_sahn_cascades_into_the_merge_above_it():
    """`_merge_node` is post-order, so an `S` it mints one level down is seen by
    the merge above as a non-`O` outside child -- which mints another. That is
    how one ground-floor merge became four sahns on health-centre s2."""
    g = Node(node=[list(c) for c in CORNERS], height=3.0, elevation=0.0,
             division=[0.5, 0.5], rotation=0,
             left=Node(division=[0.5, 0.5], rotation=0,
                       left=Node(type="O"), right=Node(type="O")),
             right=Node(type="O"))
    dom.link(g)
    geometry.clear_cache()
    dom.merge_divided(g, allow_sahn=True)
    assert [lf.type for lf in g.leaves()] == ["S"], "the cascade no longer happens"

    g2 = Node(node=[list(c) for c in CORNERS], height=3.0, elevation=0.0,
              division=[0.5, 0.5], rotation=0,
              left=Node(division=[0.5, 0.5], rotation=0,
                        left=Node(type="O"), right=Node(type="O")),
              right=Node(type="O"))
    dom.link(g2)
    geometry.clear_cache()
    dom.merge_divided(g2)
    assert [lf.type for lf in g2.leaves()] == ["O"]


@pytest.mark.skipif(not (EXAMPLES / "programme-house").is_dir(),
                    reason="examples absent")
@pytest.mark.parametrize("prog,name", [
    ("programme-house", "coldstart-c836457+orth-500000-s2.dom"),
    ("health-centre", "coldstart-c836457+orth-500000-s2.dom"),
])
def test_scoring_a_committed_artefact_leaves_no_sahn_behind(prog, name):
    """The end-to-end guard, on two artefacts that carried minted sahns (one
    each for programme-house, four for health-centre).

    `score_with_fails` is what has to pass the flag; asserting on
    `merge_divided` alone would not catch `Fitness` forgetting to."""
    d = EXAMPLES / prog
    path = d / name
    if not path.is_file():
        pytest.skip(f"{name} absent")
    conf, cost = fitness.load_config(str(d))
    fit = fitness.Fitness(conf, cost)
    assert not fit.conf("allow_sahn_circulation"), "fixture assumes sahns are off"

    root = genome.decode(genome.encode(dom.load(str(path))))
    fit.score_with_fails(copy.deepcopy(root))

    # re-run the scorer's own preprocessing order on the tree we keep, so we can
    # inspect what it leaves behind
    fit.preprocess_building(root)
    dom.merge_divided(root, allow_sahn=bool(fit.conf("allow_sahn_circulation")))
    sahns = [lf for lvl in dom.levels(root) for lf in lvl.leaves() if lf.type == "S"]
    assert not sahns, (
        f"{len(sahns)} sahn(s) survive a score with sahn circulation off: "
        f"{[lf.id for lf in sahns]}")

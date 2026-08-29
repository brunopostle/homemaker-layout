"""Tests for leaf-adjacency graph build, merge_divided, and pre-merge checks.

Oracle: edge counts verified against Perl urb (Urb::Quad::Graph, door_width=1.2)
across the 35-file corpus.  Widths for 2f45907 verified edge-by-edge.

Fidelity decision (DESIGN.md §8.1): has_vertical_connection is a faithful stub —
any leaf of the target type on the level below counts; no spatial overlap check.
"""

from pathlib import Path

import pytest

from homemaker_layout import dom, geometry
from homemaker_layout.dom import merge_divided, levels
from homemaker_layout.graph import build_graphs

CORPUS = Path(__file__).parent.parent / "examples" / "programme-house"

pytestmark = pytest.mark.skipif(not CORPUS.is_dir(), reason="Corpus not available")

# ---------------------------------------------------------------------------
# Perl-oracle edge counts per file (generated from Urb::Quad::Graph, door=1.2)
# ---------------------------------------------------------------------------
PERL_EDGE_COUNTS = {
    "0aec8e39552ff3bc9f43e085912644c5.dom": [5, 3, 8],
    "105ceaf8751377af694a5bb8854bed3e.dom": [3, 5, 8],
    "155953b017c5c7b7559d5a2a1f22cd5f.dom": [7, 5, 3],
    "21059668d774c17322e78931605080ad.dom": [8, 5],
    "2c13a0816affe390130cb0ad24336d81.dom": [5, 10],
    "2f45907abd9accac2a124d311732f749.dom": [9, 3, 6],
    "3ec9e7f4785e3db8b71921444c8fd4fa.dom": [10, 3, 6],
    "3ff824bf8e5e00f28a736fcb405a4702.dom": [6, 8],
    "458aa8b8756bc099ce22f0ee92ce4c88.dom": [8, 3, 3],
    "48ffdc096e07ba0bdc7b537485ce7a79.dom": [9, 3, 6],
    "6cdced8e6d3aae40bdb7180d1a206729.dom": [10, 5],
    "6fa7ebd4d570ebe48c8845fbc4e4ead0.dom": [4, 3, 4],
    "77f9db022c0f124eef216ab3737edd3c.dom": [9, 3, 6],
    "7d8269c8faa6adf23432243c13e90cb6.dom": [10, 6],
    "7ef10b4dfe6bf7d9cee5bf0cbd7d67a9.dom": [3, 5, 5],
    "82c7439d3098ad710fef7d8caa3e320d.dom": [7, 9],
    "8fbadf0d7cd70ff6eb49c2dc978ed4e0.dom": [8, 3, 6],
    "a82f07068e4408fdd0d5e3dc469a8dee.dom": [3, 9, 3],
    "aa0dcab98927d2c933e8381d37734971.dom": [8, 8],
    "aa4f7a9839a84435ac07fdf8111cce42.dom": [8, 5],
    "b5d6002ff0b04f9269566b14d5e91f2a.dom": [6, 6],
    "c074775d0660ba48fa607f4472c7e484.dom": [3, 3, 9],
    "c436666f7cf1c24b20daaa625a01a071.dom": [8, 3, 6],
    "c7fab3037ca6ff7a02a42553570b2aaa.dom": [9, 3, 6],
    "c848f73cf1a847b8cb6583dbde94c633.dom": [8, 3, 6],
    "c964435454c459f86c3ed9a5a7621132.dom": [3, 9, 3],
    "ca9e80c5c1502f1050eaa548978dbb2d.dom": [6, 8],
    "candidate-001.dom": [3, 9, 9],
    "candidate-002.dom": [3, 9, 9],
    "cb93a2d2de7f5d37af450a8ce7b681b1.dom": [6, 8],
    "cd39357b1ba79aec4943411cdca51668.dom": [3, 5, 5],
    "cf0b8a77e8b2325f92a7e7d150184a55.dom": [5, 6],
    "de9468f607f5d0a88cc554ad1776b537.dom": [7, 5, 3],
    "eebf1980a672d9ec11cfc69c029d6796.dom": [4, 5, 4],
    "init.dom": [0],
}


def test_edge_counts_match_perl_corpus():
    """Edge counts per level must match Perl oracle across all 35 corpus files."""
    for fname, expected in PERL_EDGE_COUNTS.items():
        root = dom.load(str(CORPUS / fname))
        actual = [
            geometry.leaf_graph(lvl, 1.2).number_of_edges()
            for lvl in dom.levels(root)
        ]
        assert actual == expected, f"{fname}: got {actual}, expected {expected}"


def test_edge_widths_2f45907():
    """Edge widths for 2f45907 must match Perl values to 3 d.p."""
    root = dom.load(str(CORPUS / "2f45907abd9accac2a124d311732f749.dom"))
    lvls = dom.levels(root)

    def edges_as_dict(G):
        return {
            tuple(sorted((a.id, b.id))): round(d["width"], 3)
            for a, b, d in G.edges(data=True)
        }

    # Level 0 (Perl-verified widths)
    g0 = edges_as_dict(geometry.leaf_graph(lvls[0], 1.2))
    assert g0[("lll", "llr")] == pytest.approx(4.176, abs=0.001)
    assert g0[("lll", "rl")] == pytest.approx(1.237, abs=0.001)
    assert g0[("lll", "rr")] == pytest.approx(1.586, abs=0.001)
    assert g0[("lll", "lrl")] == pytest.approx(2.175, abs=0.001)
    assert g0[("lll", "lrr")] == pytest.approx(2.001, abs=0.001)
    assert g0[("llr", "rr")] == pytest.approx(2.429, abs=0.001)
    assert g0[("lrl", "lrr")] == pytest.approx(2.422, abs=0.001)
    assert g0[("lrr", "rl")] == pytest.approx(2.306, abs=0.001)
    assert g0[("rl", "rr")] == pytest.approx(2.639, abs=0.001)

    # Level 1
    g1 = edges_as_dict(geometry.leaf_graph(lvls[1], 1.2))
    assert g1[("l", "rl")] == pytest.approx(3.543, abs=0.001)
    assert g1[("l", "rr")] == pytest.approx(4.014, abs=0.001)
    assert g1[("rl", "rr")] == pytest.approx(2.639, abs=0.001)

    # Level 2
    g2 = edges_as_dict(geometry.leaf_graph(lvls[2], 1.2))
    assert g2[("ll", "rrr")] == pytest.approx(2.581, abs=0.001)
    assert g2[("ll", "lr")] == pytest.approx(4.176, abs=0.001)
    assert g2[("lr", "rl")] == pytest.approx(3.543, abs=0.001)
    assert g2[("lr", "rrl")] == pytest.approx(1.252, abs=0.001)
    assert g2[("rl", "rrl")] == pytest.approx(2.639, abs=0.001)
    assert g2[("rrl", "rrr")] == pytest.approx(2.625, abs=0.001)


def test_all_edge_widths_at_or_above_door_width():
    """Every edge in every graph must have width >= 1.2 (the door_width threshold)."""
    for fname in PERL_EDGE_COUNTS:
        root = dom.load(str(CORPUS / fname))
        for lvl in dom.levels(root):
            G = geometry.leaf_graph(lvl, 1.2)
            for _, _, d in G.edges(data=True):
                assert d["width"] >= 1.2 - 1e-9, f"{fname}: edge width {d['width']} < 1.2"


def test_graph_nodes_equal_leaf_count():
    """Every graph must have exactly one vertex per leaf (isolated or connected)."""
    for fname in PERL_EDGE_COUNTS:
        root = dom.load(str(CORPUS / fname))
        for lvl in dom.levels(root):
            leaves = lvl.leaves()
            G = geometry.leaf_graph(lvl, 1.2)
            assert G.number_of_nodes() == len(leaves), fname


def test_build_graphs_length_matches_level_count():
    """build_graphs must return one graph per storey."""
    for fname in PERL_EDGE_COUNTS:
        root = dom.load(str(CORPUS / fname))
        gs = build_graphs(root)
        assert len(gs) == len(dom.levels(root)), fname


def test_merge_divided_candidate_002():
    """candidate-002 level 2 collapses 5 outdoor leaves into a single O node."""
    root = dom.load(str(CORPUS / "candidate-002.dom"))
    lvl2_before = levels(root)[2]
    leaves_before = [leaf.type for leaf in lvl2_before.leaves()]
    # level 2 has 7 leaves, of which 5 are O/S types in the l-subtree
    assert len(leaves_before) == 7

    merge_divided(root)
    lvl2_after = levels(root)[2]
    leaves_after = [(leaf.id, leaf.type) for leaf in lvl2_after.leaves()]
    # After merge the 5 outdoor leaves in l collapse to a single O
    assert len(leaves_after) == 3
    assert ("l", "O") in leaves_after


def test_two_phase_build_graphs_independent():
    """Pre-merge and post-merge graphs must be independent (different node counts
    after merging a file that actually merges)."""
    root = dom.load(str(CORPUS / "candidate-002.dom"))
    graphs_pre = build_graphs(root)
    pre_nodes_l2 = graphs_pre[2].number_of_nodes()

    merge_divided(root)
    graphs_post = build_graphs(root)
    post_nodes_l2 = graphs_post[2].number_of_nodes()

    assert pre_nodes_l2 == 7
    assert post_nodes_l2 == 3


# --------------------------------------------------------------------------- #
# homemaker-py-1i8 / DESIGN.md §38.12 — the missing-space cascade must not be
# weighted by how verbosely the programme was written.
# --------------------------------------------------------------------------- #
def _missing_fails(declared: dict) -> list[str]:
    """Fails for a bare plot that declares one required room, absent."""
    from homemaker_layout.graph import check_space_counts
    from homemaker_layout.programme import _parse_spaces

    reqs = _parse_spaces({"spaces": {"x1": dict({"usage": "living"}, **declared)}})
    root = dom.Node(node=[[0, 0], [6, 0], [6, 6], [0, 6]], type="O")
    fails, missing = check_space_counts(root, reqs)
    assert missing, "the room should be reported missing"
    return fails


def test_missing_space_cost_is_independent_of_declared_keys():
    """A missing room costs the same whether or not the author typed the
    optional keys.

    It used to cost 2 base + one placeholder per key PRESENT IN THE YAML, so a
    room declaring size/width/proportion cost 5 fails and one declaring size
    alone cost 3. Under `value *= 0.5 ** len(failures)` that is a 4x difference
    in penalty between two single rooms, decided by verbosity -- and the tiered
    comparator inherits it, since n_hard is dominated by these cascades.
    """
    verbose = _missing_fails({"size": [16.0, 4.0], "width": [4.0, 1.0],
                              "proportion": [1.5, 0.5]})
    terse = _missing_fails({"size": [16.0, 4.0]})
    assert len(verbose) == len(terse) == 5
    assert set(verbose) == set(terse)


def test_missing_space_placeholders_mirror_the_checks_a_present_room_faces():
    """All three, always -- because a present room is checked on all three.

    `get_space_params` fills width and proportion from defaults (deriving width
    from size when absent), so the requirement exists however the config is
    spelled. The placeholder count has to mirror that or the two paths
    disagree.
    """
    fails = _missing_fails({"size": [16.0, 4.0]})
    for check in ("size", "width", "proportion"):
        assert f"missing x1: would need {check} check" in fails
    assert sum(1 for f in fails if f.startswith("missing required space")) == 2


def test_missing_space_cascade_scales_per_instance_not_per_code():
    fails = _missing_fails({"size": [16.0, 4.0], "count": 3})
    assert len(fails) == 15
    for i in (1, 2, 3):
        assert f"missing required space: x1#{i}" in fails

"""Tests for programme.py parsing and validation."""

from pathlib import Path

import pytest

from homemaker_layout import dom, fitness, programme

# --------------------------------------------------------------------------- #
# homemaker-py-ju3 / DESIGN.md §39.2 — reserved generic type prefixes
# --------------------------------------------------------------------------- #
def test_validate_codes_accepts_codes_that_merely_start_with_c_o_s():
    """§39.4: the generic-type tests match C/O/S EXACTLY, so a programme code
    may start with any letter. This used to raise — that was the bug, not the
    rule."""
    programme.validate_codes(["cr1", "of", "st1", "st2", "b1", "k1", "la1"])


@pytest.mark.parametrize("code", ["C", "O", "S"])
def test_validate_codes_rejects_exact_generic_types(code):
    """A code spelled exactly like a generic structural type is a genuine
    ambiguity no matching rule can resolve, so it still fails loudly."""
    with pytest.raises(ValueError, match="generic structural types"):
        programme.validate_codes([code])


def test_exact_generic_rejected_by_both_parse_paths():
    """programme._parse_spaces and fitness.Fitness._load_programme parse
    conf["spaces"] independently — validating only one would leave the other
    door open."""
    conf = {"spaces": {"C": {"size": [80.0, 10.0]}}}
    with pytest.raises(ValueError, match="generic structural types"):
        programme._parse_spaces(conf)
    with pytest.raises(ValueError, match="generic structural types"):
        fitness.Fitness(conf=conf)


def test_colliding_code_is_a_full_requirement_not_a_generic():
    """The §39.2 damage in one assertion: a c-prefixed code must keep its
    declared targets and stay in the required set."""
    conf = {"spaces": {"cr1": {"size": [80.0, 10.0], "width": [6.0, 1.5],
                               "proportion": [2.0, 0.5], "count": 1,
                               "usage": "living"}}}
    fit = fitness.Fitness(conf=conf)
    assert fit.get_space_params("cr1", "size") == [80.0, 10.0]
    assert fit.get_space_params("cr1", "width") == [6.0, 1.5]
    assert not dom.is_generic("cr1")
    assert not dom.is_circulation(dom.Node(type="cr1"))
    assert not dom.is_outside(dom.Node(type="of"))
    # ...while the genuine generics still classify as before
    assert dom.is_circulation(dom.Node(type="C"))
    assert dom.is_outside(dom.Node(type="O"))
    assert dom.is_outside(dom.Node(type="S")) and dom.is_circulation(dom.Node(type="S"))


def test_a_codes_first_letter_no_longer_decides_anything():
    """§39.7: usage is DECLARED, so a code's spelling carries no meaning at all.

    `b1` was a bedroom purely because it started with "b"; here it declares
    `utility` and that is what it is. This is the property the old prefix
    convention could not offer, and the reason `la1` "Laundry Room" was being
    trimmed as a living room.
    """
    reqs = programme._parse_spaces({"spaces": {
        "l1": {"size": [20.0, 4.0], "usage": "utility"},
        "k1": {"size": [12.0, 3.0], "usage": "none"},
        "b1": {"size": [16.0, 4.0], "usage": "utility"},
        "zzz": {"size": [3.0, 1.0], "usage": "bedroom"},
    }})
    assert reqs["l1"].usage == "utility"
    assert reqs["k1"].usage == "none"
    assert reqs["b1"].usage == "utility"
    assert reqs["zzz"].usage == "bedroom"


def test_usage_is_mandatory_and_reported_by_code():
    with pytest.raises(ValueError, match=r"declare no .usage.*\['b1'\]|\['b1'\].*declare no"):
        programme._parse_spaces({"spaces": {"b1": {"size": [16.0, 4.0]}}})


def test_unknown_usage_is_rejected_not_silently_ignored():
    with pytest.raises(ValueError, match="unknown usage value"):
        programme._parse_spaces(
            {"spaces": {"b1": {"size": [16.0, 4.0], "usage": "craft"}}})


def test_usage_is_rejected_by_both_parse_paths():
    """Fitness parses conf["spaces"] independently of programme._parse_spaces."""
    conf = {"spaces": {"b1": {"size": [16.0, 4.0]}}}
    with pytest.raises(ValueError, match="declare no"):
        programme._parse_spaces(conf)
    with pytest.raises(ValueError, match="declare no"):
        fitness.Fitness(conf=conf)


def test_usage_survives_a_retype_because_it_is_code_level():
    """The mutation-safety property: usage is looked up from the CODE, so a
    retype changes the class automatically and nothing can go stale."""
    fit = fitness.Fitness(conf={"spaces": {
        "b1": {"size": [16.0, 4.0], "usage": "bedroom"},
        "s9": {"size": [16.0, 4.0], "usage": "utility"},
    }})
    leaf = dom.Node(type="b1")
    assert fit.usage_of(leaf) == "bedroom"
    leaf.type = "s9"                      # exactly what mutate_retype does
    assert fit.usage_of(leaf) == "utility"


def test_corpus_programmes_are_namespace_clean():
    """Every checked-in example must load — a regression here means a corpus
    programme reintroduced a colliding code."""
    for d in sorted(Path("examples").iterdir()):
        if (d / "patterns.config").is_file():
            programme.load_programme_dir(str(d))


def test_scoring_is_invariant_under_programme_code_spelling(tmp_path):
    """§39.4's headline invariant: renaming a programme code must not change
    what a layout scores.

    Builds one layout from harbor-house (whose codes ``cr1``/``of``/``st1``/
    ``st2`` all begin with a reserved generic letter), then relabels that exact
    tree AND its config together and re-scores. Same geometry, same topology,
    only the spelling differs — so any difference is the generic-type rule
    leaking into the programme namespace, which is the bug this guards.
    """
    import copy
    import re
    import shutil

    import numpy as np

    from homemaker_layout import driver, operators

    rename = {"cr1": "fr1", "of": "ao", "st1": "gs1", "st2": "gs2"}
    src = Path("examples/harbor-house")
    shutil.copytree(src, tmp_path / "hh")
    cfg = tmp_path / "hh" / "patterns.config"
    text = cfg.read_text()
    for old, new in rename.items():
        text = re.sub(rf"^(  ){re.escape(old)}:$", rf"\g<1>{new}:", text, flags=re.M)
    cfg.write_text(text)

    def evaluator(directory):
        overrides = driver._overrides_for(True, False, None, False, True, False)
        conf, cost = fitness.load_config(str(directory), overrides=dict(overrides or {}))
        return fitness.Fitness(conf, cost)

    def relabel(root):
        for lvl in dom.levels(root):
            for leaf in lvl.leaves():
                leaf.type = rename.get(leaf.type, leaf.type)
                leaf.share_type = rename.get(leaf.share_type, leaf.share_type)
        return root

    reqs = programme.load_programme_dir(str(src))
    before, after = evaluator(src), evaluator(tmp_path / "hh")
    for seed in range(3):
        root = operators.constructive_topology(
            dom.load(str(src / "init.dom")), reqs, np.random.default_rng(seed),
            sorted(reqs) + ["C", "O"],
            min_storeys=programme.storey_minimum(str(src)),
            adjacency_aware=True, proportion_aware=True, circ_divisor=3,
            leaf_sharing=True, leaf_share_factor=3, depth_balanced=True,
            interior_outside=True, outside_divisor=3)
        score_a, fails_a = before.score_with_fails(copy.deepcopy(root))
        score_b, fails_b = after.score_with_fails(relabel(copy.deepcopy(root)))
        normalised = tuple(sorted(
            re.sub(r"\b(%s)\b" % "|".join(rename), lambda m: rename[m.group(1)], f)
            for f in fails_a))
        assert f"{score_a:.12g}" == f"{score_b:.12g}", f"seed {seed}: score differs"
        assert normalised == tuple(sorted(fails_b)), f"seed {seed}: fails differ"

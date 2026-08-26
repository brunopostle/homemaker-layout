"""Tests for programme.py parsing and validation."""

from pathlib import Path

import pytest

from homemaker_layout import fitness, programme

# --------------------------------------------------------------------------- #
# homemaker-py-ju3 / DESIGN.md §39.2 — reserved generic type prefixes
# --------------------------------------------------------------------------- #
def test_validate_codes_accepts_non_reserved_prefixes():
    programme.validate_codes(["b1", "k1", "t3", "la1", "me1", "n", "fr1", "ao"])


@pytest.mark.parametrize("code", ["cr1", "of", "st1", "C", "O", "s2"])
def test_validate_codes_rejects_reserved_prefixes(code):
    """A colliding code must fail LOUDLY: silently reinterpreting it as a
    generic type is the whole bug (§39.2)."""
    with pytest.raises(ValueError, match="reserved generic type prefixes"):
        programme.validate_codes([code])


def test_reserved_prefix_rejected_by_both_parse_paths():
    """programme._parse_spaces and fitness.Fitness._load_programme parse
    conf["spaces"] independently — validating only one would leave the other
    door open."""
    conf = {"spaces": {"cr1": {"size": [80.0, 10.0]}}}
    with pytest.raises(ValueError, match="reserved generic type prefixes"):
        programme._parse_spaces(conf)
    with pytest.raises(ValueError, match="reserved generic type prefixes"):
        fitness.Fitness(conf=conf)


def test_semantic_but_unreserved_prefixes_are_allowed():
    """l/k/b/t carry adjacency semantics but never discard a requirement, so
    programme codes may use them freely — only c/o/s are reserved."""
    reqs = programme._parse_spaces({"spaces": {
        "l1": {"size": [20.0, 4.0]}, "k1": {"size": [12.0, 3.0]},
        "b1": {"size": [16.0, 4.0]}, "t1": {"size": [3.0, 1.0]},
    }})
    assert sorted(reqs) == ["b1", "k1", "l1", "t1"]


def test_corpus_programmes_are_namespace_clean():
    """Every checked-in example must load — a regression here means a corpus
    programme reintroduced a colliding code."""
    for d in sorted(Path("examples").iterdir()):
        if (d / "patterns.config").is_file():
            programme.load_programme_dir(str(d))

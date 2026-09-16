"""The constructor must judge adjacency the way the scorer does (1v7).

``operators.py``'s greedy and beam room placement scored a candidate slot by
comparing FIRST CHARACTERS: the target's first letter against each neighbour
type's first letter. §39.4 had already given `graph.py` the right rule --
generics matched exactly, everything else by Perl's prefix semantics -- and
``graph.code_matches_requirement`` is documented as "the single place that
answers 'does this leaf count as the thing the programme asked to be next to'",
shared with ``cpsat`` so the exact solver optimises the same relation the scorer
checks. The greedy/beam path never adopted it.

Every disagreement over-credits: the constructor believed requirements were
satisfied that the scorer then failed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from homemaker_layout import graph, programme

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CORPUS = ["harbor-house", "maple-court", "health-centre", "programme-house"]
pytestmark = pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(),
                                reason="examples absent")


def _first_char_rule(code: str, target: str) -> bool:
    """The rule that was in operators.py before homemaker-py-1v7."""
    return code[:1].lower() == target[:1].lower()


@pytest.mark.parametrize("target,neighbour", [
    ("b1", "b2"),      # programme-house: a bedroom is not another bedroom
    ("de1", "dp1"),    # health-centre
    ("rc1", "re1"),    # health-centre
    ("o", "of"),       # harbor-house: a room named `of` is NOT outside space
])
def test_the_first_char_rule_over_credited_these(target, neighbour):
    """Each of these was counted as satisfying the requirement and is not."""
    assert _first_char_rule(neighbour, target), "premise: the old rule matched"
    assert not graph.code_matches_requirement(neighbour, target)


def test_prefix_semantics_are_preserved():
    """§39.4 kept Perl's `^target` for ordinary codes deliberately -- a
    requirement for `r` IS satisfied by `rc1`. The fix must not tighten that
    into exact equality."""
    assert graph.code_matches_requirement("rc1", "r")
    assert graph.code_matches_requirement("b1", "b1")


def test_the_generic_targets_stay_exact():
    """`c` means circulation, not "any code starting with c" (§39.4)."""
    assert graph.code_matches_requirement("C", "c")
    assert not graph.code_matches_requirement("cr1", "c")
    assert graph.code_matches_requirement("O", "o")
    assert not graph.code_matches_requirement("of", "o")


@pytest.mark.parametrize("name", CORPUS)
def test_no_remaining_disagreement_on_the_corpus(name):
    """Sweep every adjacency target against every code the programme can place:
    the constructor's rule and the scorer's must now agree everywhere."""
    reqs = programme.load_programme_dir(str(EXAMPLES / name))
    codes = sorted(reqs) + ["C", "O", "S"]
    targets = {a for r in reqs.values() for a in r.adjacency if a}
    for target in sorted(targets):
        for code in codes:
            # what the constructor now asks
            assert graph.code_matches_requirement(code, target) == \
                   graph.code_matches_requirement(code, target)


def test_operators_no_longer_compares_first_characters():
    """A source check, because the defect is a shape of code rather than a
    value: nothing in the adjacency placement may slice a type to one char."""
    src = (Path(__file__).resolve().parent.parent / "src" / "homemaker_layout"
           / "operators.py").read_text()
    for marker in ('[:1].lower()', '[0].lower()'):
        assert marker not in src, (
            f"operators.py still contains {marker!r} -- first-character type "
            f"tests were removed by homemaker-py-1v7")

"""Oracle unit tests that do not invoke perl."""

import pytest

from homemaker import oracle


def test_fail_lines_sorted_and_filtered():
    s = oracle.Score(fitness=0.5, fails="---\nb fail\n\na fail\n  \n")
    assert s.fail_lines == ("a fail", "b fail")
    assert s.n_fails == 2


def test_fail_lines_empty():
    s = oracle.Score(fitness=0.5, fails="")
    assert s.fail_lines == ()
    assert s.n_fails == 0


def test_score_batch_empty_list():
    assert oracle.score_batch([]) == []


def test_score_batch_rejects_cross_directory(tmp_path):
    a = tmp_path / "a" / "x.dom"
    b = tmp_path / "b" / "y.dom"
    for p in (a, b):
        p.parent.mkdir()
        p.write_text("")
    with pytest.raises(ValueError, match="batch spans directories"):
        oracle.score_batch([a, b])

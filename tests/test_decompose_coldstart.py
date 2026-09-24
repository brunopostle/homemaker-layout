"""The sweep decomposition must group fail families correctly and refuse to
report an incomplete sweep as a result (DESIGN.md §39.31, §39.47)."""

from __future__ import annotations

import csv
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "experiments" / "decompose_coldstart.py"
TABLE = (Path(__file__).resolve().parent.parent
         / "experiments" / "results" / "coldstart_baseline.tsv")
pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="script absent")


def _mod():
    spec = importlib.util.spec_from_file_location("decompose_coldstart", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _verifier_mod():
    spec = importlib.util.spec_from_file_location(
        "verify_results_table", SCRIPT.parent / "verify_results_table.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rows_to_score():
    """(objective, rows) for the fullest objective in the table, current or not.

    These tests ask what TODAY'S evaluator emits; the artefact is only input
    geometry, so the objective it was measured at does not have to be the
    current one. Keying on the current objective meant all three stopped running
    the moment an objective changed -- i.e. for the whole week between a change
    and the sweep that re-baselines it, which is precisely when the evaluator is
    being edited. §39.20 is the standing lesson: a test that skips is a test
    that is not running, and nobody reads the skip count.
    """
    import csv as _csv
    import collections
    if not TABLE.is_file():
        pytest.skip("results table absent")
    rows = list(_csv.DictReader(TABLE.open(), delimiter="\t"))
    if not rows:
        pytest.skip("results table is empty")
    by = collections.Counter(r["objective"] for r in rows)
    obj = by.most_common(1)[0][0]
    return obj, [r for r in rows if r["objective"] == obj]


# Real lines, taken from scoring the committed corpus -- not invented shapes.
CASES = [
    ("0/lllr outside edge too long", "outside edge too long"),
    ("1/rrll rrlr edge too long", "edge too long"),
    ("2/llll lllrl edge too long", "edge too long"),
    ("1/rllr (py) not adjacent to c", "not adjacent to c"),
    ("0/rrrrll (t9) not adjacent to c", "not adjacent to c"),
    ("level 0 not connected", "level N not connected"),
    ("level 1 no outside space", "level N no outside space"),
    ("0/rlrlr proportion", "proportion"),
    ("2/llr proportion", "proportion"),
    ("too few stairs (0, min 1)", "too few stairs (N, min N)"),
    ("0/ crinkliness", "crinkliness"),
]


@pytest.mark.parametrize("line,want", CASES)
def test_family_strips_everything_that_is_not_the_kind(line, want):
    assert _mod().family(line) == want


def test_the_second_leaf_id_does_not_split_a_family():
    """'<a> <b> edge too long' names two leaves. Leaving the second on made one
    family appear as three families of one -- hiding exactly the concentration
    the decomposition exists to find."""
    m = _mod()
    fams = {m.family(l) for l in ("1/rrll rrlr edge too long",
                                  "2/llll lllrl edge too long",
                                  "0/lr rrrr edge too long")}
    assert fams == {"edge too long"}


def test_outside_edge_too_long_stays_its_own_family():
    """fitness.py raises these from two different checks (lines 1778 and 1795);
    merging them would hide which one moved."""
    m = _mod()
    assert m.family("0/lllr outside edge too long") != m.family("1/a rrlr edge too long")


def test_every_committed_fail_line_normalises_to_a_bare_kind():
    """No family may still carry a leaf id, a room code, or a raw number."""
    import re
    m = _mod()
    v = _verifier_mod()
    _, rows = _rows_to_score()
    seen = 0
    for r in rows:
        _, orth = v.split_objective(r["objective"])
        got = v.score_lines(r["programme"], r["dom"], orthogonal=orth)
        if got is None:
            continue
        for ln in got[0]:
            f = m.family(ln)
            seen += 1
            assert "/" not in f, f"{ln!r} -> {f!r} still has a leaf path"
            assert not re.search(r"\d", f.replace("N", "")), f"{ln!r} -> {f!r}"
            assert not re.match(r"^[lr]+ ", f), f"{ln!r} -> {f!r} starts with a leaf id"
    assert seen, "scored the corpus and it produced no failures at all"


def test_every_committed_fail_line_is_classifiable():
    """Every fail string the CURRENT evaluator emits must have a tier.

    Re-homed from `test_fitness.py`, which globbed `.fails` off disk. Those are
    gitignored by-products of whatever objective wrote them, so that guard
    eventually failed on debris from before the objective stamp existed rather
    than on a regression (§39.50). Re-scoring asks the same question of data
    that is current by construction.
    """
    from homemaker_layout.fitness import classify_fail_tier
    v = _verifier_mod()
    _, rows = _rows_to_score()
    seen = 0
    for r in rows:
        _, orth = v.split_objective(r["objective"])
        got = v.score_lines(r["programme"], r["dom"], orthogonal=orth)
        if got is None:
            continue
        for ln in got[0]:
            classify_fail_tier(ln)      # raises ValueError if untiered
            seen += 1
    assert seen, "scored the corpus and it produced no failures at all"


def test_an_incomplete_sweep_is_refused_not_averaged():
    """§39.31: a decomposition is not a result until the sweep is complete."""
    r = subprocess.run([sys.executable, str(SCRIPT)],
                       capture_output=True, text=True, cwd=SCRIPT.parent.parent)
    out = r.stdout
    if "INCOMPLETE" in out:
        assert r.returncode == 2
        assert "--partial" in out
        assert "§39.31" in out or "39.31" in out
    else:
        assert r.returncode in (0, 1)


def test_partial_marks_every_section_provisional(tmp_path, monkeypatch, capsys):
    """Builds its own incomplete sweep rather than waiting for one.

    This used to run the script against the live table and skip when the sweep
    was complete -- so the moment the sweep finished, the guard stopped running
    and nothing said so. That is §39.20 exactly: parity tests that skipped on
    every clean checkout and were believed to be passing for years.
    """
    import csv as _csv
    m = _mod()
    if not TABLE.is_file():
        pytest.skip("results table absent")
    v_spec = importlib.util.spec_from_file_location(
        "verify_results_table", SCRIPT.parent / "verify_results_table.py")
    v = importlib.util.module_from_spec(v_spec)
    v_spec.loader.exec_module(v)

    rows = list(_csv.DictReader(TABLE.open(), delimiter="\t"))
    # Any objective with rows, not necessarily the current one -- the script
    # takes `--objective`, and what is under test is the PROVISIONAL marking,
    # not which sweep is live. Keying on the current objective made this skip
    # for the whole window between an objective change and its re-baseline.
    target, _ = _rows_to_score()
    # filtered from THIS read of the table: `_rows_to_score` opens its own, so
    # its row objects are different objects and identity-dropping one of them
    # silently drops nothing -- which left the table complete and the test
    # asserting PROVISIONAL against a finished sweep.
    live = [r for r in rows if r["objective"] == target]
    if len(live) < 2:
        pytest.skip("need at least two rows at one objective")

    # the same table minus one row, so the sweep reads as incomplete
    short = tmp_path / "coldstart_baseline.tsv"
    with short.open("w", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter="\t")
        w.writeheader()
        w.writerows([r for r in rows if r is not live[-1]])
    monkeypatch.setattr(m, "TABLE", short)

    import sys as _sys
    monkeypatch.setattr(_sys, "argv",
                        ["decompose_coldstart.py", "--partial",
                         "--objective", target])
    assert m.main() == 0
    out = capsys.readouterr().out
    assert "PROVISIONAL" in out
    assert "Nothing below is a result" in out
    for section in ("=== rows", "=== fail families"):
        i = out.index(section)
        assert "PROVISIONAL" in out[i:i + 60], f"{section} is not marked"


def test_the_target_objective_does_not_depend_on_the_environment(monkeypatch):
    """§39.43: which rows exist is a fact about the table, not about whoever is
    running this. Deriving the whole stamp from the environment is what made
    the verifier able to see only half its table."""
    m = _mod()
    v_spec = importlib.util.spec_from_file_location(
        "verify_results_table", SCRIPT.parent / "verify_results_table.py")
    v = importlib.util.module_from_spec(v_spec)
    v_spec.loader.exec_module(v)
    monkeypatch.delenv("HOMEMAKER_ORTHOGONAL_DIVISION", raising=False)
    off = m.default_target(v)[0]
    monkeypatch.setenv("HOMEMAKER_ORTHOGONAL_DIVISION", "1")
    assert m.default_target(v)[0] == off


def test_a_cross_objective_comparison_names_the_confound():
    """§39.12 clause 3. Any commit to fitness.py/geometry.py between the two
    objectives must be printed before the numbers are."""
    m = _mod()
    src = SCRIPT.read_text()
    assert "separating_commits" in src
    i = src.index("def main")
    body = src[i:]
    assert body.index("separating_commits") < body.index("paired_report"), (
        "the numbers are printed before the confound that explains them")

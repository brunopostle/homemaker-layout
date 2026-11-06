"""The owner's answers to the ordering questionnaire, held as tests
(`homemaker-py-5fje.2`, DESIGN.md §39.201-§39.204).

Each answered comparison is a pair of committed designs, A and B, in
`experiments/results/questionnaire/`, and the owner's verdict on which is
worse is in `answers.tsv` beside them. `test_candidate_agrees` requires the
candidate aggregation P1 (geometric mean over the brief's rooms) to give the
owner's verdict on every one.

`test_todays_objective_agrees` asks the same of today's score (A0). It is a
strict xfail on the comparisons A0 is known to get wrong: today it documents
the disagreement, and the day the objective changes it XPASSes, which fails
the run and forces this file to be revisited.

"Equally bad" answers (O3) are not tested: no score here can make two
different plans exactly level, and §39.204 reads that answer as calibration.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from homemaker_layout import dom, geometry, programme
from homemaker_layout.fitness import Fitness

REPO = Path(__file__).resolve().parent.parent
HERE = REPO / "experiments" / "results" / "questionnaire"
PROG = REPO / "examples" / "maple-court"
pytestmark = pytest.mark.skipif(not (HERE / "answers.tsv").is_file(), reason="no answers")

# comparisons today's objective orders against the owner (§39.204)
A0_WRONG = {"O1-0", "O6-3", "O6-5", "O6-6", "O8-0"}


def _answers():
    if not (HERE / "answers.tsv").is_file():
        return []
    items = {i["id"]: i for i in json.loads((HERE / "items.json").read_text())}
    newest = {}
    with (HERE / "answers.tsv").open() as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row["worse"] in ("A", "B"):
                newest[(row["item"], int(row["rung"]))] = row["worse"]
    return [(f"{i}-{r}", items[i]["rungs"][r], w) for (i, r), w in sorted(newest.items())]


ANSWERS = _answers()


@pytest.fixture(scope="module")
def scorer():
    sys.path.insert(0, str(REPO / "experiments"))
    spec = importlib.util.spec_from_file_location(
        "diag_aggregation", REPO / "experiments" / "diag_aggregation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.path.insert(0, str(REPO / "experiments"))
    from successive_halving import load_config
    return mod.arms, Fitness(*load_config(PROG)), programme.load_programme_dir(str(PROG))


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    geometry.clear_cache()
    yield
    geometry.clear_cache()


def _verdict(scorer, key, rung, arm):
    arms, fit, reqs = scorer
    s = {}
    for side in ("a", "b"):
        geometry.clear_cache()
        root = dom.load(str(HERE / f"{key}-{side}.dom"))
        dom.link(root)
        s[side] = arms(fit, reqs, root, 1e-3, rung[side]["cost"])[arm]
    if abs(s["a"] - s["b"]) <= 0.001 * max(abs(s["a"]), abs(s["b"])):
        return "="
    return "A" if s["a"] < s["b"] else "B"


@pytest.mark.parametrize("key,rung,worse", ANSWERS, ids=[a[0] for a in ANSWERS])
def test_candidate_agrees(scorer, key, rung, worse):
    assert _verdict(scorer, key, rung, "P1") == worse, \
        f"{key}: owner says {worse} worse ({rung['a']['desc']} / {rung['b']['desc']})"


@pytest.mark.parametrize("key,rung,worse", [
    pytest.param(*a, marks=pytest.mark.xfail(strict=True, reason="A0 disagrees, §39.204"))
    if a[0] in A0_WRONG else a for a in ANSWERS], ids=[a[0] for a in ANSWERS])
def test_todays_objective_agrees(scorer, key, rung, worse):
    assert _verdict(scorer, key, rung, "A0") == worse

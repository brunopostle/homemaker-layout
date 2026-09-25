"""`OBJECTIVE_SOURCES` must name every file a score actually executes (§39.63).

The coldstart runner stamps every row with `git log -1 -- OBJECTIVE_SOURCES`,
and refuses to start when one of those files is uncommitted. Both are only as
good as the list, and the list was written from someone's idea of what "the
objective" means rather than from what a score runs. It has been wrong twice:

* fitness.py alone -- geometry.py decides every leaf's area, so an
  orthogonal-division sweep took the same stamp as a non-orthogonal one
  (homemaker-py-32t, §39.32);
* + geometry.py -- but `Fitness.score_with_fails` calls `dom.merge_divided` and
  `preprocess_building` outright and reaches into `graph` for every adjacency
  and connectivity check. A one-line semantic edit to dom.py moved the twelve
  committed artefacts from 255 fails to 257 while the stamp stayed
  `691cc21+orth` and `uncommitted_objective_sources` stayed silent (§39.63).

Both were found by reading. This test finds the next one by measuring: it runs
one real `score_with_fails` in a clean interpreter and asks which
`homemaker_layout` modules got loaded. A module that joins the scoring path
fails this test until someone classifies it -- either into `OBJECTIVE_SOURCES`,
where it changes what a stamp means, or out of it with a reason.

It is a guard that CAN fire, which §39.61 is the argument for.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RUNNER = REPO / "experiments" / "run_coldstart_baseline.py"
PROGRAMME = REPO / "examples" / "programme-house"
ARTEFACT = "coldstart-c836457+orth-500000-s0.dom"

pytestmark = pytest.mark.skipif(
    not RUNNER.is_file() or not (PROGRAMME / ARTEFACT).is_file(),
    reason="runner or corpus artefact absent")

# Loaded by a score, but NOT part of the objective, each with the reason it is
# not. Anything here is a claim that can be checked by reading the module.
NOT_OBJECTIVE: dict[str, str] = {}

# Deliberately outside the objective: these decide how the search MOVES, not
# what a committed .dom scores. If one of them starts being loaded by a score,
# that is a real change and this test should say so.
SEARCH_SIDE = ("solver", "driver", "operators", "innerloop", "shapecurve",
               "cpsat", "evolve", "genome", "bubble")


def _runner():
    spec = importlib.util.spec_from_file_location("coldstart_runner", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _modules_loaded_by_a_score() -> set[str]:
    """Run one real score in a clean interpreter; return the `homemaker_layout`
    submodules it loaded. A subprocess because this process has long since
    imported the whole package."""
    code = (
        "import sys, copy, json\n"
        "from homemaker_layout import dom, fitness\n"
        f"conf, cost = fitness.load_config({str(PROGRAMME)!r})\n"
        "fit = fitness.Fitness(conf, cost)\n"
        f"root = dom.load({str(PROGRAMME / ARTEFACT)!r})\n"
        "fit.score_with_fails(copy.deepcopy(root))\n"
        "print(json.dumps(sorted(m.split('.')[-1] for m in sys.modules\n"
        "                        if m.startswith('homemaker_layout.'))))\n"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"scoring subprocess failed:\n{r.stderr}"
    return set(json.loads(r.stdout.strip().splitlines()[-1]))


def test_every_module_a_score_loads_is_named_in_objective_sources():
    loaded = _modules_loaded_by_a_score()
    named = {Path(p).stem for p in _runner().OBJECTIVE_SOURCES}
    missing = sorted(loaded - named - set(NOT_OBJECTIVE))
    assert not missing, (
        f"{missing} are loaded by a score but are not in OBJECTIVE_SOURCES.\n"
        "A change to one of them moves fail counts while the stamp does not, "
        "which is §39.42 arriving through a file nobody listed.\n"
        "Add it to OBJECTIVE_SOURCES, or to NOT_OBJECTIVE with the reason it "
        "cannot affect a score.")


def test_objective_sources_all_exist():
    for rel in _runner().OBJECTIVE_SOURCES:
        assert (REPO / rel).is_file(), f"{rel} is named as objective source but is absent"


def test_objective_sources_are_not_over_broad():
    """The converse failure: naming a file that scoring never touches makes the
    stamp move for changes that alter nothing, and retires a corpus for free."""
    loaded = _modules_loaded_by_a_score()
    named = {Path(p).stem for p in _runner().OBJECTIVE_SOURCES}
    assert not sorted(named - loaded), (
        f"{sorted(named - loaded)} are stamped as the objective but a score "
        "never loads them")


def test_search_side_modules_stay_out_of_the_scoring_path():
    loaded = _modules_loaded_by_a_score()
    crossed = sorted(set(SEARCH_SIDE) & loaded)
    assert not crossed, (
        f"{crossed} are documented as search-side but a score now loads them. "
        "Either the scoring path grew (so they belong in OBJECTIVE_SOURCES and "
        "the corpus needs re-stamping) or an import leaked in.")

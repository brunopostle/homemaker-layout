"""A row must record the SEARCH it was run with, not just the objective (§39.65).

Until §39.65 a `coldstart_baseline.tsv` row said what objective scored it and
nothing about the search that produced it. The runner passes no operator flag,
so every sweep measures whatever the defaults happen to be -- and there are
seven gated operators. Flipping any one of them changed what every future row
meant while the rows stayed labelled identically. That is §39.42's failure one
layer out, and §39.63's a second time: a stamp that does not cover what it is
read as covering.

Two columns, because two different things move, exactly as the objective needs
both `objective_commit` and the `+orth` environment suffix:

* `search_commit` -- last commit touching `SEARCH_SOURCES`; catches a behaviour
  change or a flipped default in `driver.py`;
* `search_config` -- hash of the effective knob values as `homemaker-evolve`
  resolves them; catches an environment override, which no commit records.

What these tests hold is that neither can go quietly stale: the source partition
cannot leave a new module unclassified, and the hash must actually move when a
knob does.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
RUNNER = REPO / "experiments" / "run_coldstart_baseline.py"
SRC = REPO / "src" / "homemaker_layout"

pytestmark = pytest.mark.skipif(not RUNNER.is_file(), reason="runner absent")


def _runner():
    spec = importlib.util.spec_from_file_location("coldstart_runner", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# the partition: every module is classified, exactly once
# --------------------------------------------------------------------------- #
def test_every_module_is_classified_exactly_once():
    """The guard that keeps both stamps honest as the package grows.

    A module that is neither an objective source nor a search source nor
    explicitly neither is a module whose changes no stamp records. Adding one
    fails here until somebody decides which it is -- which is the decision
    §39.63 found had been skipped for `dom.py` and `graph.py`.
    """
    mod = _runner()
    obj = set(mod.OBJECTIVE_SOURCES)
    search = set(mod.SEARCH_SOURCES)
    neither = set(mod.NEITHER_SOURCES)
    on_disk = {f"src/homemaker_layout/{f.name}" for f in SRC.glob("*.py")}

    assert not (obj & search), f"in both objective and search: {sorted(obj & search)}"
    assert not (obj & neither), f"in both objective and neither: {sorted(obj & neither)}"
    assert not (search & neither), f"in both search and neither: {sorted(search & neither)}"

    unclassified = sorted(on_disk - obj - search - neither)
    assert not unclassified, (
        f"{unclassified} is in no category, so no stamp records changes to it. "
        "Put it in OBJECTIVE_SOURCES (it changes what a .dom scores), "
        "SEARCH_SOURCES (it changes how the search moves), or NEITHER_SOURCES "
        "with the reason.")

    phantom = sorted((obj | search | neither) - on_disk)
    assert not phantom, f"classified but absent from disk: {phantom}"


def test_search_sources_are_not_objective_sources():
    """`test_objective_sources.py` proves a score loads none of these. This is
    the same claim from the other side, so the two lists cannot both drift into
    agreeing with each other and disagreeing with reality."""
    mod = _runner()
    for rel in mod.SEARCH_SOURCES:
        assert rel not in mod.OBJECTIVE_SOURCES


# --------------------------------------------------------------------------- #
# the config hash
# --------------------------------------------------------------------------- #
def test_search_config_is_stable_and_records_the_operator_gate():
    mod = _runner()
    h1, c1 = mod.search_config()
    h2, c2 = mod.search_config()
    assert h1 == h2 and c1 == c2, "the hash is not a function of the config alone"
    assert "support_outside" in c1, (
        "the operator gate whose flip motivated §39.65 is not in the recorded "
        "configuration")
    assert len(h1) == 10 and all(ch in "0123456789abcdef" for ch in h1)


def test_the_hash_moves_when_a_knob_moves(monkeypatch):
    """The whole point: a different search must not hash the same.

    Driven through the environment rather than by editing a default, because
    that is the case no commit records and therefore the case `search_commit`
    cannot catch on its own.
    """
    mod = _runner()
    monkeypatch.delenv("HOMEMAKER_SUPPORT_OUTSIDE", raising=False)
    base_h, base_c = mod.search_config()

    monkeypatch.setenv("HOMEMAKER_SUPPORT_OUTSIDE",
                       "0" if base_c["support_outside"] else "1")
    other_h, other_c = mod.search_config()

    assert other_c["support_outside"] != base_c["support_outside"], (
        "the environment override did not reach the effective config -- "
        "search_config is reading something other than what evolve runs")
    assert other_h != base_h, (
        "two different searches hash identically, so a row cannot tell them "
        "apart, which is the defect §39.65 exists to fix")


def test_a_recorded_config_round_trips_through_its_sidecar(tmp_path, monkeypatch):
    mod = _runner()
    monkeypatch.setattr(mod, "SEARCH_CONFIGS", tmp_path / "search_configs")
    h, conf = mod.search_config()

    first = mod.write_search_config(h, conf)
    assert first is not None and first.name == f"{h}.json"
    assert json.loads(first.read_text()) == json.loads(
        json.dumps(conf, default=str)), "the sidecar does not hold the config"

    assert mod.write_search_config(h, conf) is None, (
        "writing the same config twice reported it as new, so the sweep would "
        "re-commit an unchanged sidecar on every run")


# --------------------------------------------------------------------------- #
# the schema
# --------------------------------------------------------------------------- #
def test_the_table_schema_carries_both_search_columns():
    mod = _runner()
    assert mod.FIELDS[-2:] == ["search_commit", "search_config"]


TABLE = REPO / "experiments" / "results" / "coldstart_baseline.tsv"


@pytest.mark.skipif(not TABLE.is_file(), reason="results table absent")
def test_rows_predating_the_columns_say_so_rather_than_guessing():
    """The 48 rows recorded before §39.65 carry `-`, not a back-filled guess.

    Back-filling them from today's defaults would assert something nobody
    measured -- and would be wrong for exactly the rows that matter, since
    `support_outside` did not exist when any of them ran.
    """
    import csv
    mod = _runner()
    rows = list(csv.DictReader(TABLE.open(), delimiter="\t"))
    assert rows, "table is empty"
    for r in rows:
        assert set(mod.FIELDS) <= set(r), f"row missing columns: {sorted(set(mod.FIELDS) - set(r))}"
        assert r["search_commit"] and r["search_config"], (
            "a row has an empty search stamp; unrecorded must read '-'")

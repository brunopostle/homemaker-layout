"""The owner's ruling, held on every programme (DESIGN.md §39.85):

    An omitted room should be closer to a working building than a building
    with no circulation.

`experiments/diag_ruling_omit_vs_circulation.py` builds both buildings for an
artefact -- the CHEAPEST single-room omission, and every circulation cell
absorbed by its neighbouring room -- and requires the first to score higher.
One artefact per programme, smallest to largest, so an objective change that
breaks the ordering for any programme size fails here. The self-test inflates
the missing-room cascade and must make the tool report a violation: without
it, a pass would mean nothing (CLAUDE.md, the negative-control rule).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from homemaker_layout import geometry

TOOL = Path(__file__).resolve().parent.parent / "experiments" / "diag_ruling_omit_vs_circulation.py"
CORPUS = "coldstart-07b2058+orth-500000-s0.dom"
pytestmark = pytest.mark.skipif(not TOOL.is_file(), reason="tool absent")


def _tool():
    spec = importlib.util.spec_from_file_location("diag_ruling", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _orth(monkeypatch):
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)


@pytest.mark.parametrize("prog", ["programme-house", "health-centre",
                                  "harbor-house", "maple-court"])
def test_omitting_a_room_beats_losing_circulation(prog, capsys):
    assert _tool().main(["--programme", prog, "--corpus", CORPUS]) == 0, \
        capsys.readouterr().out


def test_the_check_can_fail(monkeypatch, capsys):
    from homemaker_layout import graph
    monkeypatch.setattr(graph, "check_space_counts", graph.check_space_counts)
    assert _tool().main(["--programme", "programme-house", "--corpus", CORPUS,
                         "--self-test"]) == 0, capsys.readouterr().out
    assert "control fired" in capsys.readouterr().out

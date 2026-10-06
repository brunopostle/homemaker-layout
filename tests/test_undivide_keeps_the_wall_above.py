"""Owner, 2026-10-06: "undividing a cell shouldn't undivide cells above by
default" -- and it should not move their walls either (DESIGN.md §39.98/§39.100).

An upper-storey node inherits its cut from the node below and stores a ratio of
its own that is ignored meanwhile. The search never synchronises the two, so
removing the lower cut used to leave the upper node cutting at a stale value:
one `undivide` in six shifted a wall upstairs by a third of a metre.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from homemaker_layout import dom

REPO = Path(__file__).resolve().parent.parent
DIAG = REPO / "experiments" / "diag_3tzk_operator_walls.py"
PROGRAMMES = ("programme-house", "health-centre")

pytestmark = pytest.mark.skipif(
    not (REPO / "examples" / "health-centre").is_dir(), reason="examples absent")


def _census():
    spec = importlib.util.spec_from_file_location("_walls", DIAG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.census(draws=6, only=["undivide", "deslim"], raw=True,
                      programmes=PROGRAMMES)


def test_removing_a_cut_leaves_the_wall_above_where_it_was():
    stats = _census()
    assert stats["undivide"]["events"] > 5          # the case does arise
    assert stats["undivide"]["moved"] == 0
    assert stats["deslim"]["moved"] == 0


def test_control_without_the_hand_up_walls_move(monkeypatch):
    monkeypatch.setattr(dom, "hand_cut_up", lambda n: None)
    assert _census()["undivide"]["moved"] > 0

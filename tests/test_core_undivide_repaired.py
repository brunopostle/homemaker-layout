"""`mutate_core_undivide` as its docstring describes it, behind a switch
(`homemaker-py-w4e`, DESIGN.md §39.106).

"Reverse of core_divide: merge a C sub-core back into a single C leaf on all
floors." As shipped it does neither half: it looks for a path OWNED on two
storeys, and it types the merged cell as the room beside the stair. The
repaired form is default OFF -- it changes what a search does, and the A/B
that decides it needs the box -- so the first thing held here is that the
switch being off changes nothing.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, evolve, genome, geometry, operators, programme

REPO = Path(__file__).resolve().parent.parent
PH = REPO / "examples" / "programme-house"
TYPES = ["b1", "l1", "C", "O"]


def _two_storeys_with_a_divided_core() -> dom.Node:
    """What `core_divide` leaves: `C | b1` at one path on both storeys."""
    def storey():
        return dom.Node(division=[0.5, 0.5], left=dom.Node(type="l1"),
                        right=dom.Node(division=[0.3, 0.3], left=dom.Node(type="C"),
                                       right=dom.Node(type="b1")))
    root = storey()
    root.above = storey()
    dom.link(root)
    return root


@pytest.fixture
def repaired(monkeypatch):
    monkeypatch.setattr(operators, "CORE_UNDIVIDE_REPAIRED", True)


def test_the_switch_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv("HOMEMAKER_CORE_UNDIVIDE_REPAIRED", raising=False)
    assert evolve._parse_args(["init.dom"]).core_undivide_repaired is False
    assert evolve._parse_args(
        ["init.dom", "--core-undivide-repaired"]).core_undivide_repaired is True
    monkeypatch.setenv("HOMEMAKER_CORE_UNDIVIDE_REPAIRED", "1")
    assert evolve._parse_args(["init.dom"]).core_undivide_repaired is True


def test_as_shipped_it_declines_the_tree_core_divide_leaves(monkeypatch):
    monkeypatch.setattr(operators, "CORE_UNDIVIDE_REPAIRED", False)
    _, desc = operators.mutate_core_undivide(
        _two_storeys_with_a_divided_core(), np.random.default_rng(0), TYPES)
    assert "noop" in desc


def _stair_cells(root) -> list:
    return [(lvl.by_id("r").divided, lvl.by_id("r").type) for lvl in dom.levels(root)]


def test_repaired_it_gives_the_stair_its_cell_back_on_every_storey(repaired):
    child, desc = operators.mutate_core_undivide(
        _two_storeys_with_a_divided_core(), np.random.default_rng(0), TYPES)
    assert "noop" not in desc
    assert _stair_cells(child) == [(False, "C"), (False, "C")]     # not the room beside it


def test_control_the_precondition_repaired_alone_leaves_a_room_there():
    """The second defect on its own -- what the switch must NOT do, and what
    the same check says about it. The variant lives in the diagnostic that
    measured it (68 of 128 firings emptied the stair shaft, §39.106)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_w4e", REPO / "experiments" / "diag_w4e_core_undivide.py")
    w4e = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w4e)
    child, desc = w4e.core_undivide(_two_storeys_with_a_divided_core(),
                                    np.random.default_rng(0), TYPES, restore_c=False)
    assert "noop" not in desc
    assert _stair_cells(child) == [(False, "b1"), (False, "b1")]


@pytest.mark.skipif(not PH.is_dir(), reason="examples absent")
def test_repaired_it_undoes_a_core_divide(repaired, monkeypatch):
    """On real designs: divide the core, then undivide it, and the topology
    is the parent's again in most draws (the rest picked another stacked
    pair); the staircase is never thrown away."""
    monkeypatch.setattr(geometry, "ORTHOGONAL_DIVISION", True)
    reqs = programme.load_programme_dir(str(PH))
    types = sorted(reqs) + ["C", "O"]
    fired = restored = emptied = 0
    for path in sorted(PH.glob("coldstart-1a24b6a+orth-500000-s*.dom")):
        geometry.clear_cache()
        base = genome.decode(genome.encode(dom.load(str(path))))
        for seed in range(6):
            divided, desc = operators.mutate_core_divide(
                base, np.random.default_rng(100 + seed), types)
            if "noop" in desc:
                continue
            child, desc = operators.mutate_core_undivide(
                divided, np.random.default_rng(seed), types)
            if "noop" in desc:
                continue
            fired += 1
            restored += genome.signature(child) == genome.signature(base)
            emptied += (bool(operators._shaft_paths(dom.levels(divided)))
                        and not operators._shaft_paths(dom.levels(child)))
    geometry.clear_cache()
    assert fired >= 6
    assert restored >= 0.6 * fired
    assert emptied == 0

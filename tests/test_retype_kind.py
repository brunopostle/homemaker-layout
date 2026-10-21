"""`--retype-kind` (homemaker-py-urzf.2, DESIGN.md §39.154): label moves change
only a cell's kind, never one room into another -- the edit the scorer's
relabelling erased in 28-70% of draws."""
from pathlib import Path

import numpy as np
import pytest

from homemaker_layout import dom, operators, programme

PROG = Path(__file__).parent.parent / "examples" / "programme-house"
SEED = PROG / "c964435454c459f86c3ed9a5a7621132.dom"


def _labels(root):
    return [(li, lf.id, lf.type) for li, lvl in enumerate(dom.levels(root)) for lf in lvl.leaves()]


def _changes(op, monkeypatch, on, draws=200):
    if on:
        monkeypatch.setenv("HOMEMAKER_RETYPE_KIND", "1")
    else:
        monkeypatch.delenv("HOMEMAKER_RETYPE_KIND", raising=False)
    root = dom.load(str(SEED))
    dom.link(root)
    types = sorted(programme.load_programme_dir(str(PROG))) + ["C", "O"]
    before = _labels(root)
    out = []
    for s in range(draws):
        child, desc = op(root, np.random.default_rng(s), types)
        if "noop" in desc:
            continue
        diff = [(a[2], b[2]) for a, b in zip(before, _labels(child)) if a[2] != b[2]]
        out.append(diff)
    return out


@pytest.mark.parametrize("on", [True, False])
def test_retype_changes_kind_only_when_asked(monkeypatch, on):
    diffs = _changes(operators.mutate_retype, monkeypatch, on)
    room_to_room = sum(1 for d in diffs for a, b in d
                       if operators._kind(a) == operators._kind(b))
    assert diffs and all(len(d) == 1 for d in diffs)
    if on:
        assert room_to_room == 0
    else:  # negative control: the default draws room -> room freely
        assert room_to_room > len(diffs) // 4


@pytest.mark.parametrize("on", [True, False])
def test_level_retype_swaps_kinds_only_when_asked(monkeypatch, on):
    diffs = _changes(operators.mutate_level_retype, monkeypatch, on)
    same = sum(1 for d in diffs if len(d) == 2
               and operators._kind(d[0][0]) == operators._kind(d[0][1]))
    assert diffs
    if on:
        assert same == 0
    else:
        assert same > 0


def test_the_cli_sets_the_environment(monkeypatch):
    from homemaker_layout import evolve
    monkeypatch.delenv("HOMEMAKER_RETYPE_KIND", raising=False)
    assert evolve._parse_args(["init.dom"]).retype_kind is False
    assert evolve._parse_args(["init.dom", "--retype-kind"]).retype_kind is True

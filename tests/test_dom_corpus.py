"""Corpus-backed tests for dom round-trip and free-branch ownership.

Skipped when the Urb checkout is absent (these need only its .dom files, not
perl).
"""

from pathlib import Path

import pytest

from homemaker import dom, solver

CORPUS = Path("/home/bruno/src/urb/examples/programme-house")

pytestmark = pytest.mark.skipif(not CORPUS.is_dir(), reason="Urb corpus not available")


def test_roundtrip_idempotent_and_area_preserving(tmp_path):
    # dump() does not reproduce the source bytes (different YAML style); the
    # real invariants are that a dumped file reloads to the same dump (stable
    # fixed point) and that per-leaf geometry survives the trip (§4.1 is the
    # area validation against Urb itself).
    from homemaker import geometry

    for src in sorted(CORPUS.glob("*.dom")):
        root = dom.load(str(src))
        areas = [geometry.area(leaf) for lvl in dom.levels(root) for leaf in lvl.leaves()]
        once = tmp_path / ("once_" + src.name)
        dom.dump(root, str(once))

        root2 = dom.load(str(once))
        areas2 = [geometry.area(leaf) for lvl in dom.levels(root2) for leaf in lvl.leaves()]
        assert areas == pytest.approx(areas2, abs=1e-9), src.name

        twice = tmp_path / ("twice_" + src.name)
        dom.dump(root2, str(twice))
        assert twice.read_bytes() == once.read_bytes(), src.name


def test_free_branches_known_dof():
    # DOF figures from DESIGN.md §4.5
    expected = {
        "2f45907abd9accac2a124d311732f749.dom": 7,
        "candidate-002.dom": 6,
        "c964435454c459f86c3ed9a5a7621132.dom": 6,
    }
    for name, dof in expected.items():
        root = dom.load(str(CORPUS / name))
        assert len(solver.free_branches(root)) == dof, name


def test_free_branches_are_lowest_storey_owners():
    for src in sorted(CORPUS.glob("*.dom")):
        root = dom.load(str(src))
        for b in solver.free_branches(root):
            assert b.divided
            assert b.below is None or not b.below.divided

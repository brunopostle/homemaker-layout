"""`evolve._preflight` — the advisory pre-run feasibility warnings.

DESIGN.md §39.11 shipped two checks (does the demand fit the plot; is there
enough daylit wall for it). §39.17 adds the third, and the reason it is a
separate check is the whole point: check 2 divides demand evenly across
storeys, but a programme pins rooms to level 0 and the ground floor is the one
storey that cannot set itself back to buy more perimeter. Averaging hides a
ground floor that is short.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from homemaker_layout import evolve

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
pytestmark = pytest.mark.skipif(not (EXAMPLES / "harbor-house").is_dir(),
                                reason="examples absent")


def _warnings(progdir, capsys) -> list[str]:
    evolve._preflight(str(progdir))
    return [ln for ln in capsys.readouterr().err.splitlines() if ln.startswith("WARNING")]


def _ground(lines):
    return [ln for ln in lines if "pinned to level 0" in ln]


@pytest.mark.parametrize("name", ["harbor-house", "maple-court"])
def test_ground_floor_shortfall_is_reported(name, capsys):
    """Both plateau programmes pass the averaged check and fail the ground-floor
    one -- which is the case §39.17 exists to catch."""
    ground = _ground(_warnings(EXAMPLES / name, capsys))
    assert len(ground) == 1, f"{name} should warn about its pinned ground floor"
    assert "courtyard" in ground[0]
    assert "§39.17" in ground[0]


@pytest.mark.parametrize("name", ["health-centre", "programme-house"])
def test_programmes_with_a_slack_ground_floor_stay_quiet(name, capsys):
    """The two programmes that reach near-zero fails have ground-floor frontage
    to spare, and must not be warned about it."""
    assert _ground(_warnings(EXAMPLES / name, capsys)) == []


def test_the_ground_floor_check_is_stricter_than_the_averaged_one(capsys):
    """maple-court is the case that shows why averaging is not enough: the
    per-storey average asks for a far smaller courtyard than the ground floor
    actually needs. If these ever agree, one of the two checks is redundant."""
    lines = _warnings(EXAMPLES / "maple-court", capsys)
    averaged = [ln for ln in lines if "per storey needs" in ln]
    assert averaged and _ground(lines)

    def m2(line, after):
        tail = line.split(after, 1)[1]
        return float("".join(c for c in tail.split("m2")[0] if c.isdigit() or c == "."))

    assert m2(_ground(lines)[0], "roughly") > m2(averaged[0], "Roughly")


def test_preflight_never_raises_on_a_directory_it_cannot_read(tmp_path, capsys):
    """Advisory only: it must never be able to stop a run."""
    evolve._preflight(str(tmp_path))
    assert _warnings(tmp_path, capsys) == []

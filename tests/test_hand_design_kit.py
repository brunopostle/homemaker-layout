"""The kit for drawing a design by hand (`experiments/hand_design.py`,
`examples/harbor-house/HAND-BRIEF.md`; `homemaker-py-2g7.1`).

Two things have to hold for a person to draw a plan and get a score: the
composer must read what a drawing program actually writes, and the starter
drawing must itself be a design that composes. Both were untested, and the
first was false -- Inkscape writes a vertical wall as `M x,y V y2` and a
freshly drawn line as a relative `m`, and the composer read neither.
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

from homemaker_layout import compose, dom, geometry

REPO = Path(__file__).resolve().parent.parent
HARBOR = REPO / "examples" / "harbor-house"


@pytest.mark.parametrize("d, want", [
    ("M 10,5 L 10,20", [(10, 5), (10, 20)]),
    ("M 10,5 V 20", [(10, 5), (10, 20)]),              # Inkscape, a vertical wall
    ("M10 5H20", [(10, 5), (20, 5)]),                  # ...a horizontal one, minified
    ("m 10,5 0,15", [(10, 5), (10, 20)]),              # Inkscape, a freshly drawn line
    ("m 10,5 v 15", [(10, 5), (10, 20)]),
    ("M 1,2 3,4", [(1, 2), (3, 4)]),                   # the lineto left implicit
    ("m 1,1 h 3 v 2", [(1, 1), (4, 1), (4, 3)]),       # one path round a corner
    ("m 5,5 l 2,0 l 0,3", [(5, 5), (7, 5), (7, 8)]),
])
def test_the_composer_reads_straight_paths_however_they_are_written(d, want):
    assert compose._parse_path_points(d) == [(float(x), float(y)) for x, y in want]


@pytest.mark.parametrize("d", [
    "M 0,0 C 1,1 2,2 3,3",              # a curve is not a wall
    "M 0,0 L 1,0 M 2,2 L 3,3",          # two separate lines in one path
    "M 0,0",                            # a point
])
def test_and_refuses_what_is_not_one_run_of_straight_wall(d):
    assert compose._parse_path_points(d) is None


def test_a_path_round_a_corner_is_one_wall_per_segment(tmp_path):
    svg = tmp_path / "t.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">'
        '<g inkscape:groupmode="layer" inkscape:label="storey-0">'
        '<path d="m 4,0 v 8"/><path d="M 4,5 H 10"/><polyline points="0,3 2,3 2,8"/>'
        '</g></svg>')
    lines = compose.parse_svg(str(svg))[0].lines
    assert lines == [((4.0, 0.0), (4.0, 8.0)), ((4.0, 5.0), (10.0, 5.0)),
                     ((0.0, 3.0), (2.0, 3.0)), ((2.0, 3.0), (2.0, 8.0))]


def _kit():
    spec = importlib.util.spec_from_file_location(
        "_hand_design", REPO / "experiments" / "hand_design.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def harbor_copy(tmp_path, monkeypatch):
    """The kit pointed at a copy of harbor-house, so no test touches the
    owner's drawing."""
    kit = _kit()
    prog = tmp_path / "examples" / "harbor-house"
    prog.mkdir(parents=True)
    for f in ("init.dom", "patterns.config", "costs.config"):
        if (HARBOR / f).exists():
            shutil.copy(HARBOR / f, prog / f)
    (tmp_path / "experiments").mkdir()
    shutil.copy(REPO / "experiments" / "build_hand_3storey.py", tmp_path / "experiments")
    monkeypatch.setattr(kit, "REPO", tmp_path)
    was = geometry.ORTHOGONAL_DIVISION
    yield kit, prog
    geometry.ORTHOGONAL_DIVISION = was
    geometry.clear_cache()


@pytest.mark.skipif(not HARBOR.is_dir(), reason="examples absent")
def test_the_starter_drawing_is_a_design_that_composes_and_scores(harbor_copy, capsys):
    kit, prog = harbor_copy
    assert kit.main(["--template"]) == 0
    assert kit.main([]) == 0
    out = capsys.readouterr().out
    root = dom.load(str(prog / "hand.dom"))
    assert len(dom.levels(root)) == 2
    # two stair cores and a corridor on each floor, and it says what is missing
    assert "still to place: cr1" in out and "n x5" in out
    assert "too many stairs" not in out and "too few stairs" not in out


@pytest.mark.skipif(not HARBOR.is_dir(), reason="examples absent")
def test_the_kit_will_not_overwrite_a_drawing(harbor_copy):
    kit, prog = harbor_copy
    assert kit.main(["--template"]) == 0
    (prog / "hand.svg").write_text("somebody's afternoon")
    assert kit.main(["--template"]) == 2
    assert (prog / "hand.svg").read_text() == "somebody's afternoon"
    assert kit.main(["--template", "--force"]) == 0


@pytest.mark.skipif(not HARBOR.is_dir(), reason="examples absent")
def test_a_wall_that_stops_short_is_explained_not_guessed_at(harbor_copy, capsys):
    kit, prog = harbor_copy
    assert kit.main(["--template"]) == 0
    svg = prog / "hand.svg"
    # a wall across the west garden that stops 4 m short of the corridor
    svg.write_text(svg.read_text().replace(
        '<text x="5.300"', '<path d="M 0,14 H 6.6"/>\n    <text x="5.300"', 1))
    assert kit.main([]) == 1
    assert "DOES NOT COMPOSE" in capsys.readouterr().out

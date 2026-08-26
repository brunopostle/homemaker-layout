"""homemaker-py-2g7.1: plan->dom composer tests.

Synthetic fixtures only -- no real human trace exists yet (see DESIGN.md sec
37.x). These exercise the two acceptance-criteria halves: a slicible
partition round-trips to a scoring .dom, and a non-slicible one is reported
with the offending region rather than mis-parsed.
"""

from __future__ import annotations

import textwrap

import pytest

from homemaker_layout import dom, geometry
from homemaker_layout.compose import LabelError, NonSlicible, StoreyTrace, compose, parse_svg

BOUNDARY_YAML = textwrap.dedent(
    """\
    node: [[0.0, 0.0], [10.0, 0.0], [10.0, 8.0], [0.0, 8.0]]
    perimeter: {a: null, b: null, c: null, d: null}
    height: 3.0
    elevation: 0.0
    wall_inner: 0.08
    wall_outer: 0.25
    rotation: 0
    """
)

# Plot is 10x8. Cut 1 (axis 0, vertical) at x=4 splits into a left column
# (x:0-4, full height) and a right column (x:4-10). Cut 2 (axis 1,
# horizontal) at y=5 splits the right column into a bottom room (y:0-5) and
# a top room (y:5-8) -- exercises both axes and depth-2 recursion.
GOOD_SVG = textwrap.dedent(
    """\
    <svg xmlns="http://www.w3.org/2000/svg"
         xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
      <g inkscape:groupmode="layer" inkscape:label="storey-0">
        <path d="M 4,0 L 4,8"/>
        <path d="M 4,5 L 10,5"/>
        <text x="2" y="4">fr1</text>
        <text x="7" y="2.5">k1</text>
        <text x="7" y="6.5">b1</text>
      </g>
    </svg>
    """
)

# Same partition, endpoints perturbed by < 0.15 (default tol) to exercise
# snapping: a hand-drawn line that overlaps/undershoots slightly.
SLOPPY_SVG = textwrap.dedent(
    """\
    <svg xmlns="http://www.w3.org/2000/svg"
         xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
      <g inkscape:groupmode="layer" inkscape:label="storey-0">
        <path d="M 4.06,-0.05 L 3.95,8.07"/>
        <path d="M 3.96,5.04 L 10.06,4.93"/>
        <text x="2" y="4">fr1</text>
        <text x="7" y="2.5">k1</text>
        <text x="7" y="6.5">b1</text>
      </g>
    </svg>
    """
)

# One dangling interior line that touches neither pair of opposite edges --
# not a guillotine cut of the plot, and there is no other line to try.
NON_SLICIBLE_SVG = textwrap.dedent(
    """\
    <svg xmlns="http://www.w3.org/2000/svg"
         xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
      <g inkscape:groupmode="layer" inkscape:label="storey-0">
        <path d="M 3,3 L 7,3"/>
      </g>
    </svg>
    """
)


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content)
    return p


def test_composes_synthetic_partition_and_scores(tmp_path):
    boundary_path = _write(tmp_path, "boundary.dom", BOUNDARY_YAML)
    svg_path = _write(tmp_path, "plan.svg", GOOD_SVG)

    boundary = dom.load(str(boundary_path))
    storeys = parse_svg(str(svg_path))
    root = compose(boundary, storeys)

    leaves = root.leaves()
    assert sorted(leaf.type for leaf in leaves) == ["b1", "fr1", "k1"]

    # round-trips through the .dom text format
    out_path = tmp_path / "plan.dom"
    dom.dump(root, str(out_path))
    reloaded = dom.load(str(out_path))
    reloaded_types = sorted(leaf.type for leaf in reloaded.leaves())
    assert reloaded_types == ["b1", "fr1", "k1"]

    # geometry is sane: leaf areas sum to the (wall-inset) plot area
    total = sum(geometry.area(leaf) for leaf in reloaded.leaves())
    assert total == pytest.approx(geometry.area(reloaded), rel=1e-9)

    # scores cleanly through the native fitness engine (no config on disk:
    # unconstrained score, just confirms it runs end-to-end without raising)
    from homemaker_layout.fitness import Fitness

    fitness = Fitness({}, {})
    score, failures = fitness.score_with_fails(reloaded)
    assert isinstance(score, float)
    assert len(failures) > 0  # unconstrained rooms + no programme: expected fails


def test_snaps_sloppy_hand_traced_lines(tmp_path):
    boundary_path = _write(tmp_path, "boundary.dom", BOUNDARY_YAML)
    svg_path = _write(tmp_path, "plan.svg", SLOPPY_SVG)

    boundary = dom.load(str(boundary_path))
    storeys = parse_svg(str(svg_path))
    root = compose(boundary, storeys, tol=0.15)

    assert sorted(leaf.type for leaf in root.leaves()) == ["b1", "fr1", "k1"]

    # a tighter tolerance than the sketch's slop should fail to find the cuts
    boundary2 = dom.load(str(boundary_path))
    with pytest.raises((NonSlicible, LabelError)):
        compose(boundary2, storeys, tol=0.01)


def test_non_slicible_region_is_reported(tmp_path):
    boundary_path = _write(tmp_path, "boundary.dom", BOUNDARY_YAML)
    svg_path = _write(tmp_path, "plan.svg", NON_SLICIBLE_SVG)

    boundary = dom.load(str(boundary_path))
    storeys = parse_svg(str(svg_path))

    with pytest.raises(NonSlicible) as excinfo:
        compose(boundary, storeys)

    exc = excinfo.value
    assert exc.storey == 0
    # names the offending region: should be the whole plot (wall-inset
    # corners), since the dangling line doesn't localise to a sub-quad
    assert len(exc.corners) == 4
    assert "region around" in str(exc)


def test_label_count_mismatch_is_reported(tmp_path):
    svg = textwrap.dedent(
        """\
        <svg xmlns="http://www.w3.org/2000/svg"
             xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
          <g inkscape:groupmode="layer" inkscape:label="storey-0">
          </g>
        </svg>
        """
    )
    boundary_path = _write(tmp_path, "boundary.dom", BOUNDARY_YAML)
    svg_path = _write(tmp_path, "plan.svg", svg)

    boundary = dom.load(str(boundary_path))
    storeys = parse_svg(str(svg_path))

    with pytest.raises(LabelError) as excinfo:
        compose(boundary, storeys)
    assert excinfo.value.storey == 0
    assert excinfo.value.labels == []


def test_parse_svg_rejects_missing_storey_layers(tmp_path):
    svg = textwrap.dedent(
        """\
        <svg xmlns="http://www.w3.org/2000/svg"
             xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape">
          <g inkscape:groupmode="layer" inkscape:label="not-a-storey"/>
        </svg>
        """
    )
    svg_path = _write(tmp_path, "plan.svg", svg)
    with pytest.raises(ValueError):
        parse_svg(str(svg_path))


def test_compose_rejects_storey_count_mismatch(tmp_path):
    boundary_path = _write(tmp_path, "boundary.dom", BOUNDARY_YAML)
    boundary = dom.load(str(boundary_path))
    with pytest.raises(ValueError):
        compose(boundary, [StoreyTrace(), StoreyTrace()])

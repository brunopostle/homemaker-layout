"""DESIGN-INDEX.md must not fall behind DESIGN.md.

DESIGN.md is too long to load into a session, so a session loads the index
and reads sections by the line ranges it gives. A stale range sends a reader
to the wrong text without any sign that it has, which is worse than no index.
So the generated half is checked here against what the generator would write
now; the fix, when this fails, is one command:

    python experiments/build_design_index.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _tool():
    spec = importlib.util.spec_from_file_location(
        "_design_index", REPO / "experiments" / "build_design_index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_index_is_what_the_generator_would_write_today():
    tool = _tool()
    assert tool.INDEX.read_text() == tool.build(), (
        "DESIGN-INDEX.md is behind DESIGN.md: run "
        "python experiments/build_design_index.py and commit the result")


def test_every_range_starts_on_its_own_heading():
    """The check on the generator: follow each range back into DESIGN.md."""
    tool = _tool()
    lines = tool.DESIGN.read_text().splitlines()
    secs = tool.sections("\n".join(lines))
    assert len(secs) > 200
    for level, start, end, num, title in secs:
        assert lines[start - 1].startswith("#" * level + " "), (start, title)
        assert title in lines[start - 1]
        assert start <= end <= len(lines)
    # contiguous from the first heading to the end: nothing between two
    # sections belongs to neither
    for (_, _, end, _, _), (_, start, _, _, _) in zip(secs, secs[1:]):
        assert start == end + 1
    assert secs[-1][2] == len(lines)


def test_control_a_heading_added_to_the_document_is_noticed():
    tool = _tool()
    text = tool.DESIGN.read_text()
    assert tool.generated(text + "\n### 99.1 A section nobody indexed\n\nbody\n") \
        != tool.generated(text)


def test_a_heading_inside_a_code_fence_is_not_a_section():
    tool = _tool()
    text = "## 1. Real\n\n```bash\n## not a heading\n```\n\n### 1.1 Also real\n"
    assert [s[4] for s in tool.sections(text)] == ["Real", "Also real"]


def test_the_handwritten_preamble_survives_a_rebuild():
    tool = _tool()
    head = tool.INDEX.read_text().split(tool.MARKER)[0]
    assert "Load this file, not DESIGN.md" in head
    assert tool.build().startswith(head)

"""Rebuild the generated half of DESIGN-INDEX.md from DESIGN.md's headings.

DESIGN.md is the project's history and is far too long to load into a
session. DESIGN-INDEX.md is what a session loads instead: a hand-written
preamble (how to read the history, its arcs, the rulings, the nulls), then one
line per section -- its number, the lines it occupies, and its title, which
in this project is written as the finding.

Everything above the marker line in DESIGN-INDEX.md is hand-written and is
left alone. Everything below it is regenerated here. `--check` exits 1 if the
file on disk is not what this would write, and `tests/test_design_index.py`
runs it, so the index cannot fall behind the document.

    python experiments/build_design_index.py           # after editing DESIGN.md
    python experiments/build_design_index.py --check
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DESIGN = REPO / "DESIGN.md"
INDEX = REPO / "DESIGN-INDEX.md"
MARKER = "<!-- GENERATED BELOW THIS LINE by experiments/build_design_index.py -- do not edit -->"
HEADING = re.compile(r"^(#{2,3}) (.*\S)\s*$")
NUMBER = re.compile(r"^§?(\d+(?:\.\d+)*)\.?\s+(.*)$")


def sections(text: str) -> "list[tuple[int, int, int, str, str]]":
    """``(level, first line, last line, number, title)`` for every ``##`` and
    ``###`` heading outside a code fence. Lines are 1-based and a section runs
    to the line before the next heading of any level."""
    lines = text.splitlines()
    heads, fenced = [], False
    for i, line in enumerate(lines, 1):
        if line.startswith("```"):
            fenced = not fenced
        m = None if fenced else HEADING.match(line)
        if m:
            n = NUMBER.match(m.group(2))
            heads.append((len(m.group(1)), i, n.group(1) if n else "", n.group(2) if n else m.group(2)))
    out = []
    for k, (level, start, num, title) in enumerate(heads):
        end = heads[k + 1][1] - 1 if k + 1 < len(heads) else len(lines)
        out.append((level, start, end, num, title))
    return out


def generated(text: str) -> str:
    secs = sections(text)
    out = [MARKER, "",
           f"## Every section of DESIGN.md ({len(secs)} of them, {len(text.splitlines())} lines)",
           "",
           "`lines` is where to read: `sed -n '<first>,<last>p' DESIGN.md`, or the Read "
           "tool with that offset and limit. A top-level section's range is its own "
           "introduction only; its subsections follow with theirs.", ""]
    previous = 2
    for level, start, end, num, title in secs:
        label = f"§{num}" if num else "--"
        if level == 2:
            out += ["", f"**{label} {title}** -- lines {start}-{end}"]
        else:
            if previous == 2:
                out.append("")              # a list needs a blank line before it
            out.append(f"- {label} · {start}-{end} · {title}")
        previous = level
    return "\n".join(out) + "\n"


def build() -> str:
    head = INDEX.read_text() if INDEX.exists() else ""
    if MARKER not in head:
        raise SystemExit(f"{INDEX.name} has no marker line; the hand-written preamble "
                         f"must end with:\n{MARKER}")
    return head[: head.index(MARKER)] + generated(DESIGN.read_text())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if DESIGN-INDEX.md is not current; write nothing")
    a = ap.parse_args(argv)
    want = build()
    if a.check:
        if INDEX.read_text() != want:
            print("DESIGN-INDEX.md is behind DESIGN.md: run "
                  "python experiments/build_design_index.py")
            return 1
        print("DESIGN-INDEX.md is current")
        return 0
    INDEX.write_text(want)
    print(f"wrote {INDEX.name}: {len(sections(DESIGN.read_text()))} sections, "
          f"{len(want.splitlines())} lines, {len(want) // 1024} KiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Dump per-leaf areas from a .dom using the Python geometry port.

Used to validate the port against a Perl dump from Urb (see the sibling
``dump_areas.pl``). Output: one line per leaf, ``level/idpath type area``,
sorted for a stable diff.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from homemaker import dom, geometry  # noqa: E402


def main(path: str) -> None:
    root = dom.load(path)
    rows = []
    for level_idx, lvl in enumerate(dom.levels(root)):
        for leaf in lvl.leaves():
            rows.append(f"{level_idx}/{leaf.id} {leaf.type or '?'} {geometry.area(leaf):.4f}")
    print("\n".join(sorted(rows)))


if __name__ == "__main__":
    main(sys.argv[1])

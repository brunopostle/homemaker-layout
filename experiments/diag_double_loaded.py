"""`homemaker-py-sp11`: count the double-loaded corridors in a design.

A double-loaded corridor is a circulation cell at least ``--min-aspect``
times as long as it is wide whose two long walls are both lined with rooms --
more than ``--lined`` of each wall's length shared with indoor cells that are
not circulation. That is the plan Alexander argues against (Wings of Light,
107; Light on Two Sides of Every Room, 159; Short Passages, 132) and that the
default seeder can lay by running a wing's spine through its middle.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_double_loaded.py a.dom b.dom ...
    ... --self-test     # the negative control: a corridor built to fire, one built not to

For each file: the double-loaded corridors (storey, cell, length x width,
share of each long wall lined) and the total; a line per file with
``--summary``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shapely.geometry import LineString, Polygon  # noqa: E402

from homemaker_layout import dom, geometry  # noqa: E402


def _poly(leaf) -> Polygon:
    return Polygon([geometry.coordinate(leaf, i)[:2] for i in range(geometry.n_edges(leaf))])


def corridors(root, min_aspect: float = 4.0, lined: float = 0.5) -> list[tuple]:
    """(storey, id, length, width, lined_a, lined_b) for every double-loaded
    corridor in ``root``."""
    out = []
    geometry.clear_cache()
    for li, lvl in enumerate(dom.levels(root)):
        leaves = lvl.leaves()
        rooms = [_poly(x) for x in leaves
                 if not dom.is_circulation(x) and not dom.is_outside(x)]
        for leaf in leaves:
            if not dom.is_circulation(leaf):
                continue
            p = _poly(leaf)
            r = p.minimum_rotated_rectangle
            c = list(r.exterior.coords)[:4]
            sides = [LineString([c[i], c[(i + 1) % 4]]) for i in range(4)]
            sides.sort(key=lambda s: -s.length)
            length, width = sides[0].length, sides[2].length
            if width <= 0 or length / width < min_aspect:
                continue
            shares = []
            for s in sides[:2]:
                band = s.buffer(0.05, cap_style=2)
                cover = sum(band.intersection(q.buffer(0.05)).area for q in rooms) / 0.1
                shares.append(min(1.0, cover / s.length))
            if min(shares) > lined:
                out.append((li, leaf.id or "root", length, width, *shares))
    return out


def self_test() -> int:
    """A 2 x 12 m corridor between two rows of rooms must fire; the same
    corridor with rooms on one side and outside on the other must not."""
    def build(top_type):
        # three strips up y on a 12 x 10 m plot: rooms 0-4 m, a 2 m corridor,
        # then ``top_type`` 6-10 m -- built through the .dom reader, so the
        # tree is what a design file would give
        d = {"node": [[0.0, 0.0], [12.0, 0.0], [12.0, 10.0], [0.0, 10.0]],
             "perimeter": {k: None for k in "abcd"}, "height": 3.0, "elevation": 0.0,
             "wall_inner": 0.08, "wall_outer": 0.25,
             "rotation": 1, "division": [0.4, 0.4],
             "l": {"type": "r"},
             "r": {"rotation": 0, "division": [1 / 3, 1 / 3],
                   "l": {"type": "C"}, "r": {"type": top_type}}}
        root = dom._parse(d)
        dom.link(root)
        return root

    hit = corridors(build("r"))
    miss = corridors(build("O"))
    ok = len(hit) == 1 and not miss
    print(f"self-test: rooms both sides -> {len(hit)} (want 1), rooms one side -> "
          f"{len(miss)} (want 0): {'ok' if ok else 'FAILED'}")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--min-aspect", type=float, default=4.0)
    ap.add_argument("--lined", type=float, default=0.5)
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if not geometry.ORTHOGONAL_DIVISION:
        print("set HOMEMAKER_ORTHOGONAL_DIVISION=1", file=sys.stderr)
        return 2
    if args.self_test:
        return self_test()
    for f in args.files:
        found = corridors(dom.load(f), args.min_aspect, args.lined)
        metres = sum(c[2] for c in found)
        if args.summary:
            print(f"{f}: {len(found)} double-loaded, {metres:.1f} m")
            continue
        print(f"{f}: {len(found)} double-loaded corridor(s), {metres:.1f} m")
        for li, cid, length, width, a, b in found:
            print(f"    storey {li} {cid}: {length:.1f} x {width:.1f} m, lined {a:.0%} / {b:.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

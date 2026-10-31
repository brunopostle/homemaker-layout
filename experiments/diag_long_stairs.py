"""List the stair cells of a design by length: `homemaker-py-yd6t`.

`mutate_stair` labels any stacked `C` column `E`, and only stair fit limits its
shape, so a corridor can end up spelt as a stair (§39.187: 28.7 x 1.2 m on three
storeys). The owner doubts that is any good (§39.189). No bound exists yet; this
says how long they get. Reads geometry only, moves nothing.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_long_stairs.py a.dom ...
"""
import argparse

from homemaker_layout import dom, geometry


def stair_cells(root):
    """(length, width, area, storey, path) of every `E` leaf, longest first."""
    rows = []
    for storey, level in enumerate(dom.levels(root)):
        for leaf in level.leaves():
            if leaf.type == dom.GENERIC_STAIR:
                width = geometry.usable_width(leaf)
                rows.append((width * geometry.usable_aspect(leaf), width,
                             geometry.area(leaf), storey, leaf.id or "root"))
    return sorted(rows, reverse=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("doms", nargs="+")
    ap.add_argument("--over", type=float, default=0.0, help="only cells longer than this, m")
    args = ap.parse_args()
    for path in args.doms:
        rows = stair_cells(dom.load(path))
        geometry.clear_cache()
        print(f"{path}: {len(rows)} stair cells, longest {rows[0][0] if rows else 0:.1f} m")
        for length, width, area, storey, leaf in rows:
            if length > args.over:
                print(f"  {length:5.1f} x {width:.2f} m, {area:5.1f} m2, storey {storey}, {leaf}")


if __name__ == "__main__":
    main()

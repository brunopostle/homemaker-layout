"""`homemaker-py-2g7.1`: read an architectural SVG, and FIRST ask whose it is.

`examples/harbor-house/drawings/harbor-house 1.svg` is a Bonsai/IfcOpenShell export
at 1:100 -- 8197 paths, walls with thickness, 32 `IfcSpace` polygons with room
labels and the skew of a real building. It looks exactly like the human-drawn plan
this bead has been waiting for. It is not one. It is a render of
`examples/harbor-house/3m.dom` level 1 -- one of our OWN evolved layouts, via the
`3m.dom.ifc` beside it, which Bonsai reads. DESIGN.md §39.77 is the write-up of
believing otherwise for an afternoon, and the reason this tool leads with
`--provenance` rather than ending with it.

There are, as of 2026-09-28, NO human-drawn plans in this repository. The only
non-evolved `.dom` is `examples/programme-house/hand-3storey.dom`, drafted in exact
plot coordinates (§39.70).

What it does:

1. **provenance** -- census the SVG's room labels by programme code and compare
   against every level of every committed `.dom` for the programme. An exact match
   means the drawing IS that layout, and no representability verdict is reported,
   because a slicing-tree artefact is guillotine-sliceable BY CONSTRUCTION and
   saying so measures nothing;
2. extract the `IfcSpace` polygons and pair them with the labels. The labels are
   `<text transform="translate(x,y)">`, NOT x/y attributes, and each sits at its
   space's centroid;
3. estimate the building's wall direction (a length-weighted 4-fold circular mean
   over every space edge) and de-skew by it. **This matters and is the part worth
   keeping**: the plot is a skewed quad, a slicing division is NOT axis-aligned in
   sheet coordinates, and testing axis-aligned cuts on the raw drawing reports NOT
   SLICIBLE at every tolerance up to 50 cm -- a pure artefact of 1.967 degrees,
   which is 1.26 m of drift over 24 m. Any real plan traced later will need this
   first;
4. test recursive guillotine sliceability of the de-skewed bounding boxes across a
   range of snapping tolerances. On an export of our own `.dom` this measures the
   `.dom` -> IFC -> SVG round-trip cost, which came out at about a wall thickness
   (12 cm), and nothing else.

    python experiments/trace_harbor_house.py [--tol-scan] [--tol 1.5] [--force]
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from homemaker_layout import dom, geometry  # noqa: E402
from homemaker_layout.programme import load_programme_dir  # noqa: E402

SVG = REPO / "examples" / "harbor-house" / "drawings" / "harbor-house 1.svg"
PROG = REPO / "examples" / "harbor-house"
MM_PER_M = 10.0          # data-scale="1:100", and the sheet is in mm

Poly = list[tuple[float, float]]


# --------------------------------------------------------------------------- #
def _pts(d: str) -> Poly:
    return [tuple(map(float, q.split(",")))
            for q in re.findall(r"(-?[\d.]+,-?[\d.]+)", d)]


def _centroid(pl: Poly) -> tuple[float, float]:
    return (sum(q[0] for q in pl) / len(pl), sum(q[1] for q in pl) / len(pl))


def _area(pl: Poly) -> float:
    a = 0.0
    for i in range(len(pl)):
        x0, y0 = pl[i]
        x1, y1 = pl[(i + 1) % len(pl)]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2


def read_spaces(path: Path = SVG) -> tuple[list[Poly], dict[int, str]]:
    """The `IfcSpace` polygons, and the room label paired with each."""
    s = path.read_text(encoding="utf-8")
    polys = [_pts(d) for d in
             re.findall(r'<path d="([^"]+)"\s+class="IfcSpace[^"]*"\s*/>', s)]
    labels: dict[int, str] = {}
    for m in re.finditer(
            r'<text[^>]*transform="translate\(([-\d.]+),\s*([-\d.]+)\)[^"]*"[^>]*>(.*?)</text>',
            s, re.S):
        text = re.sub(r"<[^>]+>", " ", m.group(3)).strip()
        if not text:
            continue
        x, y = float(m.group(1)), float(m.group(2))
        i = min(range(len(polys)),
                key=lambda i: math.hypot(x - _centroid(polys[i])[0],
                                         y - _centroid(polys[i])[1]))
        labels[i] = text
    return polys, labels


def wall_rotation(polys: list[Poly], min_edge: float = 0.5) -> float:
    """Length-weighted 4-fold circular mean of every space edge direction.

    Four-fold because a rectangular room's edges fall into two families 90 deg
    apart and both should agree on the same building rotation.
    """
    sx = sy = 0.0
    for pl in polys:
        for i in range(len(pl)):
            x0, y0 = pl[i]
            x1, y1 = pl[(i + 1) % len(pl)]
            length = math.hypot(x1 - x0, y1 - y0)
            if length < min_edge:
                continue
            a = math.atan2(y1 - y0, x1 - x0)
            sx += length * math.cos(4 * a)
            sy += length * math.sin(4 * a)
    return math.atan2(sy, sx) / 4.0


def rotate(polys: list[Poly], theta: float) -> list[Poly]:
    c, s = math.cos(-theta), math.sin(-theta)
    return [[(x * c - y * s, x * s + y * c) for x, y in pl] for pl in polys]


def residual_misalignment(polys: list[Poly], min_edge: float = 0.5) -> list[float]:
    """Per-edge degrees off the nearest axis, after de-skew -- the residual
    `homemaker-py-ao9` is about: a real building's two wall families are not
    exactly perpendicular, so no single rotation squares both."""
    out = []
    for pl in polys:
        for i in range(len(pl)):
            x0, y0 = pl[i]
            x1, y1 = pl[(i + 1) % len(pl)]
            if math.hypot(x1 - x0, y1 - y0) < min_edge:
                continue
            a = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 90
            out.append(min(a, 90 - a))
    return sorted(out)


# --------------------------------------------------------------------------- #
# provenance: is this drawing one of OUR layouts?
# --------------------------------------------------------------------------- #
# Label -> programme code. The generic three collapse the way fitness does: a
# "Stair" is a circulation leaf, a "Sahn" takes the outside family (§39.4).
LABEL_CODE = {"circulation": "C", "stair": "C", "outside": "O", "sahn": "S"}


def label_census(labels, reqs) -> dict[str, int]:
    """The drawing's rooms counted by programme code."""
    by_name = {v.name.lower(): k for k, v in reqs.items()}
    out: dict[str, int] = {}
    for t in labels.values():
        key = t.lower()
        code = LABEL_CODE.get(key) or by_name.get(key)
        if code is None:
            continue
        out[code] = out.get(code, 0) + 1
    return out


def _generic_key(code: str) -> str:
    """`O` and `S` are one family to this comparison, as they are to the scorer."""
    return "O/S" if code in ("O", "S") else code


def _fold(census: dict[str, int]) -> dict[str, int]:
    out: dict[str, int] = {}
    for k, v in census.items():
        out[_generic_key(k)] = out.get(_generic_key(k), 0) + v
    return out


def find_source(census: dict[str, int], programme_dir: Path):
    """Every (`.dom`, level) in the programme whose leaf types match the drawing.

    A hit means the SVG is a render of that layout -- which is what
    `harbor-house 1.svg` turned out to be (§39.77).
    """
    want = _fold(census)
    hits = []
    for path in sorted(programme_dir.glob("*.dom")):
        try:
            root = dom.load(str(path))
            geometry.clear_cache()
            levels = dom.levels(root)
        except Exception:
            continue
        for i, lvl in enumerate(levels):
            got: dict[str, int] = {}
            for leaf in lvl.leaves():
                k = _generic_key(leaf.type or "")
                got[k] = got.get(k, 0) + 1
            if got == want:
                hits.append((path.name, i, sum(got.values())))
    return hits


def guillotine(boxes, idx, tol, path="root"):
    """Recursive guillotine decomposition. A cut is valid where no box straddles
    it by more than `tol`. Returns (sliceable, [(path, stuck rooms), ...])."""
    if len(idx) <= 1:
        return True, []
    for axis in (0, 1):
        lo, hi = (0, 2) if axis == 0 else (1, 3)
        for c in sorted({v for i in idx for v in (boxes[i][lo], boxes[i][hi])}):
            a = [i for i in idx if boxes[i][hi] <= c + tol]
            b = [i for i in idx if boxes[i][lo] >= c - tol]
            if a and b and len(a) + len(b) == len(idx) and not (set(a) & set(b)):
                ok_a, fa = guillotine(boxes, a, tol, path + "/A")
                ok_b, fb = guillotine(boxes, b, tol, path + "/B")
                if ok_a and ok_b:
                    return True, []
                return False, fa + fb
    return False, [(path, sorted(idx))]


def _boxes(polys):
    return [(min(q[0] for q in pl), min(q[1] for q in pl),
             max(q[0] for q in pl), max(q[1] for q in pl)) for pl in polys]


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=1.5,
                    help="snapping tolerance in sheet mm (1 mm = 10 cm at 1:100)")
    ap.add_argument("--tol-scan", action="store_true",
                    help="report sliceability across a range of tolerances")
    ap.add_argument("--force", action="store_true",
                    help="report the sliceability verdict even when the drawing is "
                         "one of our own layouts (where it measures nothing)")
    args = ap.parse_args(argv)

    polys, labels = read_spaces()
    print(f"{SVG.name}: {len(polys)} IfcSpace polygons, {len(labels)} labelled")

    # --- provenance FIRST (§39.77) ------------------------------------------ #
    reqs = load_programme_dir(str(PROG))
    census = label_census(labels, reqs)
    hits = find_source(census, PROG)
    print("\nprovenance: label census by code =",
          dict(sorted(_fold(census).items())))
    if hits:
        for name, lvl, n in hits:
            print(f"  EXACT MATCH: {name} level {lvl} ({n} leaves)")
        print("  => this drawing is a render of OUR OWN layout, not a human plan.")
    else:
        print("  no committed .dom level matches; provenance is not our output")
    drawn: dict[str, int] = {}
    for t in labels.values():
        drawn[t.lower()] = drawn.get(t.lower(), 0) + 1
    print("\nprogramme room               code  level wants drawn")
    absent_levels = set()
    for code, v in sorted(reqs.items(),
                          key=lambda kv: (kv[1].level is None, kv[1].level, kv[0])):
        d = drawn.get(v.name.lower(), 0)
        note = "" if d == v.count else ("  <-- absent" if d == 0 else "  <-- differs")
        if d == 0:
            absent_levels.add(v.level)
        print("%-28s %-5s %-5s %5d %5d%s" % (v.name[:28], code, v.level, v.count, d, note))
    print(f"\nlevels of the absent rooms: {sorted(absent_levels)}"
          "   (all level 0 => this sheet is the FIRST FLOOR plan)")
    total = sum(_area(pl) for pl in polys) / (MM_PER_M ** 2)
    print(f"drawn floor area: {total:.1f} m2")

    # --- representability --------------------------------------------------- #
    theta = wall_rotation(polys)
    rot = rotate(polys, theta)
    resid = residual_misalignment(rot)
    print(f"\ndominant wall rotation: {math.degrees(theta):+.3f} deg")
    print("residual edge misalignment after de-skew: "
          f"median {resid[len(resid)//2]:.2f} deg, "
          f"90th {resid[int(.9*len(resid))]:.2f} deg, max {resid[-1]:.2f} deg")

    raw_boxes, boxes = _boxes(polys), _boxes(rot)
    tols = ([0.0, 0.5, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 2.0, 3.0, 5.0]
            if args.tol_scan else [args.tol])
    print("\n%6s %7s   %-10s %-10s" % ("tol mm", "tol cm", "as drawn", "de-skewed"))
    for tol in tols:
        ok_raw, _ = guillotine(raw_boxes, list(range(len(raw_boxes))), tol)
        ok_rot, _ = guillotine(boxes, list(range(len(boxes))), tol)
        print("%6.1f %7.0f   %-10s %-10s" % (tol, tol * 10, ok_raw, ok_rot))

    if hits and not args.force:
        print("\nSLICEABILITY VERDICT WITHHELD: a slicing-tree artefact is "
              "guillotine-sliceable by\nconstruction, so the tolerance above is the "
              "`.dom` -> IFC -> SVG round-trip cost,\nnot a representability finding "
              "about human plans (§39.77). Pass --force to\nsee the regions anyway.")
        return 0

    ok, fails = guillotine(boxes, list(range(len(boxes))), args.tol)
    if not ok:
        print(f"\nat tol {args.tol} mm, regions with no guillotine cut:")
        for path, idx in fails:
            print("  %-14s %2d rooms: %s" % (
                path, len(idx), ", ".join(labels.get(i, "?")[:18] for i in idx)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

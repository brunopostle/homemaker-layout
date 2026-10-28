#!/usr/bin/env python3
"""Simplified SVG floor plans of a finished `.dom`, one panel per storey.

No IFC on the way: the rooms come from `rooms_export.rooms` -- the cells the
scorer sees, after its outdoor merge, in the layout's frame -- and each is
drawn as a filled polygon labelled with its code, its programme name and its
area. Party walls (perimeter `private`) are drawn heavy, stairs hatched. The
score and fail list are re-scored with today's code and printed under the
plans. A stop-gap for the drawings `homemaker-py-m1mv` is blocked on.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/plan_svg.py \
        --programme examples/harbor-house  some.dom  [-o out.svg]

The programme directory defaults to examples/<name> for the first programme
name found in the path, else the `.dom`'s own directory.
"""
import argparse
import math
import sys
from html import escape
from pathlib import Path

from homemaker_layout import dom, geometry
from homemaker_layout.fitness import Fitness, load_config
from homemaker_layout.programme import load_programme_dir
from homemaker_layout.rooms_export import rooms

REPO = Path(__file__).resolve().parent.parent

FILL = {
    "living": "#f4d8a8", "kitchen": "#f2b880", "bedroom": "#b9d3ee",
    "toilet": "#c9e7e3", "utility": "#d9d4c7", "circulation": "#f5f5f0",
    "stair": "#e0e0e0", "outside": "#cfe8bf", "sahn": "#dcefcf", "none": "#e8ddee",
}
SCALE = 22.0  # px per metre
PAD = 28.0


def programme_for(path: Path) -> Path:
    examples = REPO / "examples"
    for name in sorted((p.name for p in examples.iterdir() if (p / "patterns.config").exists()),
                       key=len, reverse=True):
        if name in str(path):
            return examples / name
    if not (path.parent / "patterns.config").exists():
        sys.exit(f"{path}: no programme found; pass --programme")
    return path.parent


def area(poly):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]))) / 2


def centroid(poly):
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        c = x0 * y1 - x1 * y0
        a += c
        cx += (x0 + x1) * c
        cy += (y0 + y1) * c
    return (cx / (3 * a), cy / (3 * a)) if a else poly[0]


def render(dom_path: Path, programme_dir: Path, title: str) -> str:
    root = dom.load(str(dom_path), native=True)
    reqs = load_programme_dir(str(programme_dir))
    made = rooms(root, programme_dir)

    conf, cost = load_config(str(programme_dir))
    scored = dom.load(str(dom_path), native=True)
    geometry.clear_cache()
    score, fails = Fitness(conf, cost).score_with_fails(scored)

    storeys: dict[int, list] = {}
    for r in made:
        storeys.setdefault(int(r["dom_id"].split("/")[0]), []).append(r)
    xs = [x for r in made for x, _ in r["vertices"]]
    ys = [y for r in made for _, y in r["vertices"]]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = (x1 - x0) * SCALE, (y1 - y0) * SCALE
    panel = w + 2 * PAD
    top = 56.0
    fail_lines = [f"{k}" + (f" x{v}" if v != 1 else "") for k, v in _count(fails).items()]
    height = top + h + 2 * PAD + 30 + 14 * (len(fail_lines) + 2)
    width = max(panel * len(storeys), 2 * PAD + 6.2 * (len(str(dom_path)) + 30))

    def pt(x, y, k):  # frame -> panel k, y up
        return (k * panel + PAD + (x - x0) * SCALE, top + PAD + (y1 - y) * SCALE)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
           f'viewBox="0 0 {width:.0f} {height:.0f}" font-family="Helvetica, Arial, sans-serif">',
           '<defs><pattern id="stair" width="6" height="6" patternUnits="userSpaceOnUse">'
           '<rect width="6" height="6" fill="#e0e0e0"/><path d="M0 6L6 0" stroke="#888" '
           'stroke-width="0.8"/></pattern></defs>',
           f'<rect width="100%" height="100%" fill="white"/>',
           f'<text x="{PAD}" y="24" font-size="16" font-weight="bold">{escape(title)}</text>',
           f'<text x="{PAD}" y="42" font-size="11" fill="#555">{escape(str(dom_path))} -- '
           f'score {score:.4g}, {len(fails)} fails</text>']
    for k, li in enumerate(sorted(storeys)):
        cx, _ = pt(x0, y1, k)
        out.append(f'<text x="{cx}" y="{top + 14}" font-size="12" font-weight="bold">'
                   f'Storey {li} (elev {storeys[li][0]["elevation"]:.1f} m)</text>')
        for r in storeys[li]:
            poly = r["vertices"]
            usage = r["usage"]
            code = r["code"]
            fill = "url(#stair)" if code == "E" else FILL.get(usage, "#eeeeee")
            if code == "O" or usage == "outside":
                fill = FILL["outside"]
            pts = " ".join("%.1f,%.1f" % pt(x, y, k) for x, y in poly)
            out.append(f'<polygon points="{pts}" fill="{fill}" stroke="#333" stroke-width="1"/>')
            walls = r["face_styles"][2:]
            for i, s in enumerate(walls):
                if s == "blank":
                    (ax, ay), (bx, by) = pt(*poly[i], k), pt(*poly[(i + 1) % len(poly)], k)
                    out.append(f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" '
                               'stroke="#000" stroke-width="4"/>')
            mx, my = pt(*centroid(poly), k)
            name = reqs[code].name if code in reqs else {
                "C": "circulation", "E": "stair", "O": "outside", "S": "sahn"}.get(code, "")
            a = area(poly)
            fs = 10 if a > 6 else 8
            out.append(f'<text x="{mx:.1f}" y="{my - 2:.1f}" font-size="{fs}" text-anchor="middle" '
                       f'font-weight="bold">{escape(code)}</text>')
            if a > 4:
                out.append(f'<text x="{mx:.1f}" y="{my + 9:.1f}" font-size="8" text-anchor="middle" '
                           f'fill="#333">{escape(name[:18])}</text>')
                out.append(f'<text x="{mx:.1f}" y="{my + 18:.1f}" font-size="8" '
                           f'text-anchor="middle" fill="#666">{a:.1f} m²</text>')
    # scale bar
    sy = top + h + 2 * PAD + 10
    out.append(f'<line x1="{PAD}" y1="{sy}" x2="{PAD + 5 * SCALE}" y2="{sy}" stroke="#000" '
               'stroke-width="2"/>')
    out.append(f'<text x="{PAD + 5 * SCALE + 6}" y="{sy + 4}" font-size="10">5 m '
               '(heavy line: party wall; hatched: stair)</text>')
    for i, line in enumerate(["fails:"] + (fail_lines or ["none"])):
        out.append(f'<text x="{PAD}" y="{sy + 22 + 14 * i}" font-size="10" fill="#444">'
                   f'{escape(line)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def _count(fails):
    c: dict = {}
    for f in fails:
        c[f] = c.get(f, 0) + 1
    return c


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dom", nargs="+")
    ap.add_argument("--programme", help="programme directory")
    ap.add_argument("-o", "--out", help="output .svg (one input only); default <dom>.plan.svg")
    ap.add_argument("--outdir", help="write <stem>.plan.svg here instead")
    ap.add_argument("--title")
    args = ap.parse_args(argv)
    if not geometry.ORTHOGONAL_DIVISION:
        print("note: HOMEMAKER_ORTHOGONAL_DIVISION is off; +orth artefacts need it",
              file=sys.stderr)
    for p in map(Path, args.dom):
        prog = Path(args.programme) if args.programme else programme_for(p.resolve())
        svg = render(p, prog, args.title or f"{prog.name}: {p.stem}")
        if args.out:
            dest = Path(args.out)
        elif args.outdir:
            dest = Path(args.outdir) / f"{p.stem}.plan.svg"
        else:
            dest = p.with_suffix(".plan.svg")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(svg)
        print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())

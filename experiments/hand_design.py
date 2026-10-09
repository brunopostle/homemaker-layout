"""A kit for drawing a design by hand and having it scored
(`homemaker-py-2g7.1`; the brief is `examples/harbor-house/HAND-BRIEF.md`).

Every non-empty design in the corpus but one was evolved. To know what the
objective makes of a plan an architect would draw, someone has to draw one.
This is the round trip:

    python experiments/hand_design.py --template     # once: the starter drawing
    ...edit examples/harbor-house/hand.svg in Inkscape...
    python experiments/hand_design.py                # compose it, score it, say why
    python experiments/hand_design.py --tune 4000    # then let the walls slide

`--template` writes `hand.boundary.dom` (the plot and two storeys, no rooms)
and `hand.svg`: the plot outline on a locked reference layer, and on each
`storey-N` layer a circulation skeleton -- a corridor and two stair cores --
with the rest of the plot left as outdoor space to be carved into rooms. It
REFUSES to overwrite a drawing that exists; `--force` insists.

The default run composes the drawing as drawn (`homemaker_layout.compose`),
scores it with the orthogonal-division switch on, and prints the room
schedule -- every cell's area against its target, its width, what it fails --
and what the programme asks for that the drawing does not have yet.
`--tune N` then gives the ratios N evaluations of the inner loop, which is
what every evolved design gets: the TOPOLOGY is the hand design, and walls a
few centimetres out should not be what the comparison measures (§39.70).

    python experiments/hand_design.py --programme programme-house --name hand2 --template
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import math
import sys
from pathlib import Path

from homemaker_layout import compose as compose_mod
from homemaker_layout import dom, geometry, innerloop, programme
from homemaker_layout.fitness import Fitness, load_config

REPO = Path(__file__).resolve().parents[1]

# The starter, in metres on the plot-aligned frame (X across, Y along the
# plot's longest side, origin at its first corner). ('X', v, low, high) is a
# cut at X = v. Two storeys with the same skeleton, so the stair cores are the
# same cell on both -- which, with the label `E`, is what a stair needs
# (§39.72, §39.125).
SPINE_W, SPINE_E = 10.6, 13.2          # a 2.6 m band: stairs and corridor
STAIR_S, STAIR_N = 5.6, 26.4           # stair cores at each end of it


def _skeleton(corridor):
    return ("X", SPINE_W, "O",
            ("X", SPINE_E, ("Y", STAIR_S, "E", ("Y", STAIR_N, corridor, "E")), "O"))


# A stair is a cell labelled `E`, the same cell on each storey it climbs. The
# corridor between them is `C` on both floors and in the same place, which
# until §39.125 made it a third staircase and had to be cut in two upstairs.
STARTER = {"harbor-house": (_skeleton("C"), _skeleton("C"))}


def _hand3():
    spec = importlib.util.spec_from_file_location(
        "_hand3", REPO / "experiments" / "build_hand_3storey.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def paths(prog: Path, name: str):
    return prog / f"{name}.boundary.dom", prog / f"{name}.svg", prog / f"{name}.dom"


# --------------------------------------------------------------------------- #
# the starter drawing
# --------------------------------------------------------------------------- #
def write_template(prog: Path, name: str, storeys: int, force: bool) -> int:
    boundary, svg, _ = paths(prog, name)
    if svg.exists() and not force:
        print(f"{svg.relative_to(REPO)} exists: that is somebody's drawing. "
              "Pass --force to replace it with the starter.")
        return 2
    seed = dom.load(str(prog / "init.dom"))
    raw = [[float(x) for x in p] for p in seed.node_file]
    per = seed.perimeter or {}
    lines = ["---", "node:"]
    for x, y in raw:
        lines += ["  -", f"    - {x}", f"    - {y}"]
    lines.append("perimeter:")
    lines += [f"  {k}: {per.get(k) or '~'}" for k in "abcd"]
    lines += ["rotation: 0", f"height: {seed.height or 3}", "elevation: 0.0",
              f"wall_inner: {seed.wall_inner}", f"wall_outer: {seed.wall_outer}",
              f"# boundary for a hand-drawn design: the plot and {storeys} storeys, "
              "no rooms.",
              f"# {name}.svg supplies the walls (experiments/hand_design.py)."]
    indent = ""
    for _ in range(storeys - 1):
        lines += [f"{indent}above:", f"{indent}  rotation: 0",
                  f"{indent}  height: {seed.height or 3}"]
        indent += "  "
    boundary.write_text("\n".join(lines) + "\n")

    h3 = _hand3()
    origin, ex, ey = h3._frame(raw)
    plot = h3._plot_corners(raw, origin, ex, ey)

    def world(q):
        return (origin[0] + q[0] * ex[0] + q[1] * ey[0],
                origin[1] + q[0] * ex[1] + q[1] * ey[1])

    specs = STARTER.get(prog.name)
    xs, ys = [p[0] for p in raw], [p[1] for p in raw]
    pad = 2.0
    vb = (min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad, max(ys) - min(ys) + 2 * pad)
    edges = "abcd"
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<!-- A hand-drawn design for {prog.name}: see HAND-BRIEF.md beside this file.',
           '     Coordinates are PLOT METRES. Draw only on the storey-N layers: straight',
           '     lines for walls, a text label for each cell. SVG y points down, so the',
           '     drawing is the plan mirrored top to bottom; that changes no score. -->',
           '<svg xmlns="http://www.w3.org/2000/svg"',
           '     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"',
           '     xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd"',
           f'     width="{vb[2] * 30:.0f}" height="{vb[3] * 30:.0f}" '
           f'viewBox="{vb[0]:.2f} {vb[1]:.2f} {vb[2]:.2f} {vb[3]:.2f}">',
           '  <g inkscape:groupmode="layer" inkscape:label="plot (reference, not read)" '
           'sodipodi:insensitive="true">',
           '    <polygon points="' + " ".join(f"{x:.3f},{y:.3f}" for x, y in raw)
           + '" fill="#f4f1e8" stroke="#888" stroke-width="0.08"/>']
    for i in range(4):
        a, b = raw[i], raw[(i + 1) % 4]
        kind = per.get(edges[i]) or "street / open"
        out.append(f'    <text x="{(a[0] + b[0]) / 2:.2f}" y="{(a[1] + b[1]) / 2:.2f}" '
                   f'font-size="0.7" fill="#888" text-anchor="middle">'
                   f'side {edges[i]}: {kind}, {math.dist(a, b):.1f} m</text>')
    out.append("  </g>")
    for i in range(storeys):
        ln: list = []
        lb: list = []
        if specs:
            h3._walk(specs[min(i, len(specs) - 1)], plot, ln, lb)
        else:
            lb.append(((sum(p[0] for p in plot) / 4, sum(p[1] for p in plot) / 4), "O"))
        hidden = ' style="display:none"' if i else ""
        out.append(f'  <g inkscape:groupmode="layer" inkscape:label="storey-{i}"{hidden}>')
        for a, b in ln:
            (x1, y1), (x2, y2) = world(a), world(b)
            out.append(f'    <line x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}" '
                       'stroke="black" stroke-width="0.08"/>')
        for p, code in lb:
            x, y = world(p)
            out.append(f'    <text x="{x:.3f}" y="{y:.3f}" font-size="0.8" '
                       f'text-anchor="middle">{code}</text>')
        out.append("  </g>")
    out.append("</svg>")
    svg.write_text("\n".join(out) + "\n")
    print(f"wrote {boundary.relative_to(REPO)} and {svg.relative_to(REPO)}")
    return 0


# --------------------------------------------------------------------------- #
# compose, score, explain
# --------------------------------------------------------------------------- #
def check(prog: Path, name: str, tune: int, tol: float, heights: bool = False) -> int:
    boundary, svg, out = paths(prog, name)
    if not svg.exists():
        print(f"no {svg.relative_to(REPO)}: run with --template first")
        return 2
    geometry.ORTHOGONAL_DIVISION = True
    try:
        root = compose_mod.compose(dom.load(str(boundary)),
                                   compose_mod.parse_svg(str(svg)), tol=tol)
    except (compose_mod.NonSlicible, compose_mod.LabelError,
            compose_mod.InheritedCut) as exc:
        print(f"THE DRAWING DOES NOT COMPOSE:\n  {exc}\n\n"
              "A NonSlicible region has a line that stops short: every wall must run "
              "from one side of its\nregion to the other. A LabelError is a cell with no "
              "label, or two. An InheritedCut is an upper\nstorey drawing a wall "
              "somewhere other than where the storey below has it.")
        return 1
    dom.dump(root, str(out))
    root = dom.load(str(out))
    dom.link(root)
    geometry.clear_cache()
    if tune:
        # --heights: the storeys' heights are tuned with the walls, after a
        # coarse look up and down each one (§39.128) -- a ceiling raised to
        # 3.6 m is what lets a room 5.5 m deep keep its daylight
        res = innerloop.optimise(root, str(prog), budget=tune, method="nm",
                                 heights=heights, height_probe=heights)
        dom.dump(root, str(out))
        root = dom.load(str(out))
        dom.link(root)
        print(f"(walls tuned for {res.n_evals} evaluations: score {res.x0_fitness:.4g} -> "
              f"{res.fitness:.4g}, fails {res.x0_n_fails} -> {res.n_fails})")
        if heights:
            print("(storey heights: " + ", ".join(
                f"{lvl.height:.2f} m" for lvl in dom.levels(root)) + ")")
        print()
    report(root, prog, out)
    return 0


def report(root, prog: Path, out: Path) -> None:
    import copy

    reqs = programme.load_programme_dir(str(prog))
    fit = Fitness(*load_config(prog))
    geometry.clear_cache()
    score, fails = fit.score_with_fails(copy.deepcopy(root))
    geometry.clear_cache()
    by_cell = collections.defaultdict(list)
    general = []
    for f in fails:
        head = f.split()[0]
        (by_cell[head].append(" ".join(f.split()[1:])) if "/" in head else general.append(f))

    have = collections.Counter()
    indoor = 0.0
    print(f"{out.relative_to(REPO)}: {len(dom.levels(root))} storeys\n")
    print(f"{'cell':<12} {'is':<5} {'area':>7} {'wanted':>12} {'width':>6} {'wanted':>7} "
          f"{'long/short':>10}  fails")
    for li, lvl in enumerate(dom.levels(root)):
        for lf in lvl.leaves():
            area = geometry.area(lf)
            a, b = geometry.usable_rectangle(lf)
            w, asp = min(a, b), (max(a, b) / min(a, b) if min(a, b) else 0)
            req = reqs.get(lf.type)
            have[lf.type] += 1
            kind = ""
            if dom.is_outside(lf):
                kind = "garden" if li == 0 else ("terrace" if dom.is_usable(lf) else "(air)")
            else:
                indoor += area
            want_a = f"{req.size:.0f} +-{req.size_sigma:.0f}" if req else kind
            want_w = f"{req.width:.1f}" if req and req.has_width else ""
            if req is None and not dom.is_generic(lf.type or ""):
                want_a = "NOT IN THE BRIEF"
            print(f"{li}/{lf.id or 'root':<10} {lf.type or '?':<5} {area:7.1f} {want_a:>12} "
                  f"{w:6.2f} {want_w:>7} {asp:10.2f}  " + ", ".join(by_cell[f'{li}/{lf.id}']))

    wanted = sum(r.size * r.count for r in reqs.values())
    print(f"\nindoor area {indoor:.0f} m2; the rooms in the brief total {wanted:.0f} m2 and "
          f"the cap on indoor area is {1.2 * wanted:.0f} m2")
    missing = [(c, r.count - have[c]) for c, r in reqs.items() if have[c] < r.count]
    extra = [(c, have[c] - r.count) for c, r in reqs.items() if have[c] > r.count]
    if missing:
        print("still to place: " + ", ".join(f"{c} x{n}" if n > 1 else c for c, n in missing))
    if extra:
        print("more than the brief asks: " + ", ".join(f"{c} x{n}" for c, n in extra))
    print(f"\nscore {score:.6g}   fails {len(fails)}")
    fam = collections.Counter()
    for f in general:
        fam["missing rooms and what they would need" if f.startswith("missing") else f] += 1
    for f, n in fam.most_common():
        print(f"   {f}" + (f"  (x{n})" if n > 1 else ""))
    cells = sum(len(v) for v in by_cell.values())
    if cells:
        c = collections.Counter(x for v in by_cell.values() for x in v)
        print(f"   and {cells} against particular cells (the last column above): "
              + ", ".join(f"{k} x{n}" for k, n in c.most_common()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", default="harbor-house")
    ap.add_argument("--name", default="hand", help="files are <name>.svg / .boundary.dom / .dom")
    ap.add_argument("--template", action="store_true", help="write the starter drawing")
    ap.add_argument("--storeys", type=int, default=2)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--tune", type=int, default=0, metavar="N",
                    help="then tune the wall positions for N evaluations")
    ap.add_argument("--heights", action="store_true",
                    help="with --tune: tune each storey's height too (2.7 m or more)")
    ap.add_argument("--tol", type=float, default=0.15,
                    help="how far short of its region's edge a line may stop, metres")
    a = ap.parse_args(argv)
    prog = REPO / "examples" / a.programme
    if a.template:
        return write_template(prog, a.name, a.storeys, a.force)
    return check(prog, a.name, a.tune, a.tol, a.heights)


if __name__ == "__main__":
    sys.exit(main())

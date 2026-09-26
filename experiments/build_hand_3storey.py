"""The 3-storey programme-house HAND design: draft the trace, compose, score.

`homemaker-py-xhw` asked for exactly one measurement. The owner, reading the
best evolved programme-house layout: "there was a fail on no first floor outdoor
space, but there is a family bathroom on the ground floor and a second bedroom
on the first floor, these could both [be] on a second floor and all have outdoor
space". The bead confirmed the mechanism (level 1's terrace sits over a
two-storey void, so `force_roof_garden` is right to reject it) and left the
question open with two outcomes, both worth having:

  * the owner's 3-storey arrangement scores HIGHER -> a reachability problem,
    and the fix is an operator that adds a storey and migrates rooms into it;
  * it scores LOWER -> an objective problem, and a sharp one.

This builds that arrangement and scores it. It is also the first HUMAN design in
the corpus (`homemaker-py-2g7.1`'s open half): every other non-empty `.dom` here
is evolution output, so nothing has ever measured what a designed plan scores.

    python experiments/build_hand_3storey.py               # compose + score
    python experiments/build_hand_3storey.py --emit-trace  # redraft the SVG
    python experiments/build_hand_3storey.py --budget 20000

WHAT IS HAND-MADE AND WHAT IS NOT. The TOPOLOGY is the design: which storey
carries which room, what stacks over what, where the stair and the two terraces
go. The division RATIOS are then optimised by the project's own inner loop
(`innerloop.optimise`, Nelder-Mead against the full objective), because that is
what every evolved artefact gets too -- comparing a hand-tuned ratio set against
a machine-tuned one would measure the tuning, not the design.

THE DESIGN, and why it is shaped like this. Six rooms (75 m2 declared) on a
51.75 m2 plot: at three storeys the plate totals 155 m2, so ~half the building
is outdoor space by arithmetic, and `area_cap` (1.2x declared, §39.58) caps the
indoor half anyway. Three constraints then fix the massing:

  * a terrace must sit over enclosed space (`dom.is_supported`, by tree ADDRESS
    -- not geometry) or it is air, and must have nothing indoors above it
    ("covered outside above ground"), so the usable footprint shrinks storey by
    storey: L2's terrace must sit over an L1 ROOM, not over L1's terrace;
  * `width_outside` is [3.0, 0.3] and fails below ~2.36 m, `width_circulation`
    [2.4, 0.2] below ~1.97 m, so every terrace and the stair need a real
    dimension; rooms have no width requirement at all (§39.37);
  * the stair needs `_stair_fit` ~= 1.0, which on a 3 m storey wants a ~3.5 m
    run -- a 2.7x2.7 core fails `staircase volume` and takes the whole
    building's value with it (x0.09).

So: a 4 m main zone (l1 on the ground, bedrooms above) against a 2.8 m service
strip holding the ground garden, the stair, and a stack of three bathrooms
(t3/t1/t2 -- one column, which is also how plumbing works). Level 1 puts its
terrace over l1; level 2 puts b2 and its terrace over b1.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from homemaker_layout import compose as compose_mod  # noqa: E402
from homemaker_layout import dom, geometry, innerloop  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PROG = REPO / "examples" / "programme-house"
BOUNDARY = PROG / "hand-3storey.boundary.dom"
SVG = PROG / "hand-3storey.svg"
OUT = PROG / "hand-3storey.dom"

# The trace, in metres on a plot-aligned frame: X along the plot's second-longest
# direction, Y along its longest boundary, origin at the plot's first corner.
# `('X', v, low, high)` is a guillotine cut at X=v with the two sides; a string
# is a room code. Cuts shared between storeys must be traced at the same value:
# the storey below owns that wall (see `compose.InheritedCut`).
SPINE = 4.3    # main zone | service strip
Y_GARDEN = 3.05  # strip: ground garden | (stair, bathrooms)
Y_BATH = 6.6     # strip: stair | bathroom stack
Y_TERR1 = 3.2    # main zone: level 1's terrace | b1
Y_TERR2 = 5.3    # over b1: b2 | level 2's terrace

STOREYS = (
    # ground: living/dining/kitchen, garden, stair, WC
    ("X", SPINE, "l1", ("Y", Y_GARDEN, "O", ("Y", Y_BATH, "C", "t3"))),
    # first: terrace over l1, master bedroom, landing, ensuite over the WC
    ("X", SPINE, ("Y", Y_TERR1, "O", "b1"),
     ("Y", Y_GARDEN, "O", ("Y", Y_BATH, "C", "t1"))),
    # second: void over the terrace, second bedroom + its terrace over b1,
    # landing, guest bathroom over the ensuite
    ("X", SPINE, ("Y", Y_TERR1, "O", ("Y", Y_TERR2, "b2", "O")),
     ("Y", Y_GARDEN, "O", ("Y", Y_BATH, "C", "t2"))),
)


# --------------------------------------------------------------------------- #
# Drafting: the plot-aligned frame, and a guillotine spec -> SVG trace
# --------------------------------------------------------------------------- #

def _frame(raw: list[list[float]]):
    """(origin, X axis, Y axis) of the plot-aligned frame, from the longest edge."""
    longest = max(range(4), key=lambda i: math.dist(raw[i], raw[(i + 1) % 4]))
    a, b = raw[longest], raw[(longest + 1) % 4]
    d = (b[0] - a[0], b[1] - a[1])
    n = math.hypot(*d)
    u = (d[0] / n, d[1] / n)          # along the longest boundary
    return raw[0], (-u[1], u[0]), (-u[0], -u[1])


def _plot_corners(raw, origin, ex, ey):
    local = [(( p[0] - origin[0]) * ex[0] + (p[1] - origin[1]) * ex[1],
              (p[0] - origin[0]) * ey[0] + (p[1] - origin[1]) * ey[1]) for p in raw]
    return [min(local, key=lambda q: q[0] + q[1]),      # SW
            min(local, key=lambda q: -q[0] + q[1]),     # SE
            max(local, key=lambda q: q[0] + q[1]),      # NE
            max(local, key=lambda q: -q[0] + q[1])]     # NW


def _at(a, b, axis, value):
    t = (value - a[axis]) / (b[axis] - a[axis])
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _split(region, kind, value):
    sw, se, ne, nw = region
    if kind == "X":
        p, q = _at(sw, se, 0, value), _at(nw, ne, 0, value)
        return [sw, p, q, nw], [p, se, ne, q], (p, q)
    p, q = _at(sw, nw, 1, value), _at(se, ne, 1, value)
    return [sw, se, q, p], [p, q, ne, nw], (p, q)


def _walk(spec, region, lines, labels):
    if isinstance(spec, str):
        labels.append(((sum(p[0] for p in region) / 4,
                        sum(p[1] for p in region) / 4), spec))
        return
    kind, value, low, high = spec
    r_low, r_high, seg = _split(region, kind, value)
    lines.append(seg)
    _walk(low, r_low, lines, labels)
    _walk(high, r_high, lines, labels)


def emit_trace(path: Path = SVG) -> Path:
    """Write the SVG trace for `STOREYS`, in plot coordinates."""
    raw = [[float(x) for x in p] for p in dom.load(str(BOUNDARY)).node_file]
    origin, ex, ey = _frame(raw)
    plot = _plot_corners(raw, origin, ex, ey)

    def world(q):
        return (origin[0] + q[0] * ex[0] + q[1] * ey[0],
                origin[1] + q[0] * ex[1] + q[1] * ey[1])

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<!-- homemaker-py-xhw / 2g7.1: the 3-storey programme-house hand',
           '     design. Drafted by experiments/build_hand_3storey.py in the',
           '     plot-aligned frame; coordinates are plot metres, the same frame',
           '     as the boundary .dom, so this can be edited in Inkscape over a',
           '     survey. SVG y points down, so it renders flipped about the',
           '     horizontal against a plan drawn the usual way up. -->',
           '<svg xmlns="http://www.w3.org/2000/svg"',
           '     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"',
           '     width="12" height="24" viewBox="-2 8 12 16">']
    for i, spec in enumerate(STOREYS):
        lines: list = []
        labels: list = []
        _walk(spec, plot, lines, labels)
        out.append(f'  <g inkscape:groupmode="layer" inkscape:label="storey-{i}">')
        for a, b in lines:
            (x1, y1), (x2, y2) = world(a), world(b)
            out.append(f'    <line x1="{x1:.6f}" y1="{y1:.6f}" '
                       f'x2="{x2:.6f}" y2="{y2:.6f}" '
                       'stroke="black" stroke-width="0.05"/>')
        for p, code in labels:
            x, y = world(p)
            out.append(f'    <text x="{x:.6f}" y="{y:.6f}" '
                       f'font-size="0.4">{code}</text>')
        out.append("  </g>")
    out.append("</svg>")
    path.write_text("\n".join(out) + "\n")
    return path


# --------------------------------------------------------------------------- #
# Compose + inner loop + report
# --------------------------------------------------------------------------- #

def build(budget: int = 20000, mode: str = "solve",
          out: Path = OUT) -> tuple[Path, float, tuple[str, ...]]:
    """Compose the trace, then fix the ratios and write ``out``.

    ``mode="solve"`` optimises them against the full objective (what an evolved
    candidate gets). ``mode="refine"`` instead slides them to the programme's
    declared target dimensions (`compose.refine`) -- the plan AS ASKED FOR,
    which is a different and also interesting number: the gap between the two
    is what the objective prefers over what the programme requested.
    """
    root = compose_mod.compose(dom.load(str(BOUNDARY)),
                               compose_mod.parse_svg(str(SVG)))
    if mode == "refine":
        compose_mod.refine(root, str(PROG))
        dom.dump(root, str(out))
        reloaded = dom.load(str(out))
        geometry.clear_cache()
        from homemaker_layout.fitness import Fitness
        from homemaker_layout.fitness_cmd import load_config
        conf, cost = load_config(PROG)
        score, fails = Fitness(conf, cost).score_with_fails(reloaded)
        return out, score, fails
    dom.dump(root, str(out))
    reloaded = dom.load(str(out))
    geometry.clear_cache()
    res = innerloop.optimise(reloaded, str(PROG), budget=budget, method="nm")
    dom.dump(reloaded, str(out))
    return out, res.fitness, res.fail_lines


def report(path: Path) -> None:
    from homemaker_layout.fitness import Fitness
    from homemaker_layout.fitness_cmd import load_config

    conf, cost = load_config(PROG)
    fitness = Fitness(conf, cost)
    root = dom.load(str(path))
    geometry.clear_cache()
    score, fails = fitness.score_with_fails(root)
    internal = 0.0
    print(f"{path.name}  (orthogonal={geometry.ORTHOGONAL_DIVISION})")
    for i, lvl in enumerate(dom.levels(root)):
        for leaf in lvl.leaves():
            area = geometry.area(leaf)
            note = ""
            if dom.is_outside(leaf):
                note = ("terrace/garden" if dom.is_usable(leaf) else "void")
            else:
                internal += area
            print(f"  {i}/{leaf.id:<6s} {leaf.type or '?':<3s} {area:6.2f} m2"
                  f"  narrowest {geometry.length_narrowest(leaf):4.2f}"
                  f"  aspect {geometry.aspect(leaf):4.2f}  {note}")
    print(f"  indoor {internal:.1f} m2 (area_cap allows "
          f"{1.2 * 75:.0f})   score {score:.6g}   fails {len(fails)}")
    for line in fails:
        print(f"   FAIL {line}")


# The evolved artefacts to compare against: programme-house's `+orth` corpora,
# which are the ones measured with the orthogonal switch on. The pre-switch
# corpora are a different objective again and are deliberately NOT compared
# (DESIGN.md §39.12 clause 3).
BASELINE = tuple(f"coldstart-{stamp}+orth-500000-s{seed}.dom"
                 for stamp in ("1138ff1", "c836457") for seed in (0, 1, 2))


def baseline(budget: int) -> None:
    """Score the evolved artefacts as committed, AND after the same ratio solve.

    The hand design gets an inner-loop solve at today's objective, so the
    evolved artefacts must get one too or the comparison measures whose ratios
    were tuned for which objective rather than whose plan is better. Their
    committed ratios were optimised under the objective of their own stamp.
    """
    import shutil
    import tempfile

    from homemaker_layout.fitness import Fitness
    from homemaker_layout.fitness_cmd import load_config

    conf, cost = load_config(PROG)
    fitness = Fitness(conf, cost)
    print(f"{'artefact':42s} {'as committed':>22s} {'ratios re-solved':>22s}")
    for name in BASELINE:
        path = PROG / name
        if not path.exists():
            print(f"{name:42s} {'MISSING':>22s}")
            continue
        root = dom.load(str(path))
        geometry.clear_cache()
        score, fails = fitness.score_with_fails(root)
        with tempfile.TemporaryDirectory() as tmp:
            # solve in a scratch copy: never touch a committed artefact
            work = Path(tmp) / name
            shutil.copy(path, work)
            root2 = dom.load(str(work))
            geometry.clear_cache()
            res = innerloop.optimise(root2, str(PROG), budget=budget, method="nm")
        print(f"{name:42s} {score:14.6g} {len(fails):2d}f "
              f"{res.fitness:16.6g} {res.n_fails:2d}f")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit-trace", action="store_true",
                    help="redraft hand-3storey.svg from STOREYS")
    ap.add_argument("--budget", type=int, default=20000,
                    help="inner-loop evaluations for the ratio solve")
    ap.add_argument("--no-build", action="store_true",
                    help="report the committed .dom without recomposing")
    ap.add_argument("--mode", choices=("solve", "refine"), default="solve",
                    help="ratios: optimise against the objective, or slide to "
                         "the programme's declared targets")
    ap.add_argument("--out", type=Path, default=None,
                    help="write somewhere other than the committed artefact")
    ap.add_argument("--baseline", action="store_true",
                    help="score the evolved +orth artefacts, as committed and "
                         "after the same ratio solve, and stop")
    args = ap.parse_args(argv)

    if not geometry.ORTHOGONAL_DIVISION:
        print("note: HOMEMAKER_ORTHOGONAL_DIVISION is not set, so this is the "
              "non-orthogonal objective; the committed artefact was built with "
              "it set to 1 (see DESIGN.md §39.70).", file=sys.stderr)
    if args.baseline:
        baseline(args.budget)
        return 0
    if args.emit_trace:
        print(f"wrote {emit_trace()}")
    out = args.out or OUT
    if not args.no_build:
        out, fitness, fails = build(args.budget, args.mode, out)
        print(f"composed ({args.mode}): {out}  fitness {fitness:.6g}  "
              f"fails {len(fails)}")
    report(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

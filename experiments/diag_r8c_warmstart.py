"""`homemaker-py-r8c`: does `solver.solve_ratios`' target model match the objective?

`solve_ratios` fixes a fixed topology's division ratios from the programme's
declared target dimensions. It is NOT in the search loop -- `driver._evaluate`
warm-starts from the tree's current ratios, or from the shape-curve DP when
`--shapecurve-warmstart` is on (off by default), and neither calls this. Its one
caller in `src/` is `compose.refine`, the path a HUMAN trace takes to a scored
`.dom` (§39.70). So this measures the composer's warm start, not the search's.

Four mismatches between its residual and today's objective, each priced here as
one rung of a ladder (every arm is the arm above plus one change):

  A  today                `min_width_generic=1.2`, width = mean of opposite edge
                          pairs, room width term on
  B  + narrowest          width measured as `geometry.length_narrowest` (the
                          shortest of the four edges), which is what
                          `quality_width` reads. The mean-pair measure is always
                          >= it, so A can believe a leaf clears a threshold the
                          objective sees it miss
  C  + per-class target   generic min width from the conf per class --
                          `width_outside` 3.0 / `width_circulation` 2.4 -- rather
                          than one 1.2 knob BELOW both fail thresholds (2.356 and
                          1.971 m). Honours `quality_width`'s roof-garden
                          exemption: an outside leaf that is uncovered,
                          unsupported and above ground scores 1.0 whatever its
                          width, so constraining it only burns DOF
  D  + no room width      rooms have no width requirement (`width_inside: None`,
                          §39.37), yet A spends a residual per room pulling
                          toward `req.width`

and three arms off the ladder:

  E  A + no room width    today's generic term, room width term dropped -- that
                          last change priced on its own
  F  C at the threshold   C, but aiming generic leaves at the width FAIL
                          THRESHOLD (2.356 / 1.971 m) rather than the conf
                          TARGET (3.0 / 2.4). The target is where `quality_width`
                          reaches 1.0; the threshold is where it stops failing,
                          and every centimetre between them is area taken from
                          rooms that the `0.5**n` cliff does not pay for
  G  F + no room width    F with the room width term dropped, i.e. D at the
                          threshold

Reported per artefact at the solved point (x0), and after `innerloop.optimise`
from it with `--nm BUDGET`. Fail COUNT is the primary metric: most of the corpus
scores 0.0 at today's objective (the artefacts were bred at `c836457+orth` and
the objective has moved since), so the score cannot discriminate there while the
count still can.

    python experiments/diag_r8c_warmstart.py [--programme NAME] [--nm 2000]
"""

from __future__ import annotations

import argparse
import collections
import math
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from homemaker_layout import dom, geometry, innerloop, solver  # noqa: E402
from homemaker_layout.fitness import Fitness, _generic_class  # noqa: E402
from homemaker_layout.fitness_cmd import load_config  # noqa: E402
from homemaker_layout.programme import SpaceReq, load_programme_dir  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("harbor-house", "health-centre", "maple-court", "programme-house")
# (narrowest width measure, generic min-width rule, room width term)
#   "knob"      one `min_width_generic` for every generic leaf (today)
#   "target"    per class, the conf width TARGET (3.0 outside / 2.4 circulation)
#   "threshold" per class, where `quality_width` stops FAILING (2.356 / 1.971)
ARM_FLAGS = {
    "A": (False, "knob", True),
    "B": (True, "knob", True),
    "C": (True, "target", True),
    "D": (True, "target", False),
    "E": (False, "knob", False),
    "F": (True, "threshold", True),
    "G": (True, "threshold", False),
}
ARMS = ("A", "B", "C", "D", "E", "F", "G")


def fail_threshold(params: list[float]) -> float:
    """Width below which `_clipped_gaussian(w, t, s, "above")` drops under 0.1."""
    t, s = params
    return t - s * math.sqrt(2 * math.log(10))


# --------------------------------------------------------------------------- #
# the candidate residual: solver.solve_ratios with the ladder's four switches
# --------------------------------------------------------------------------- #
def generic_width_target(leaf: dom.Node, fit: Fitness, mode: str) -> float | None:
    """Conf min width for a generic leaf, or None where the objective has no
    width rule for it (`quality_width`'s first branch: an uncovered, unsupported
    outside leaf above ground -- a roof garden -- always scores 1.0)."""
    t0 = _generic_class(leaf)
    if t0 not in ("o", "s", "c"):
        return None
    if (t0 in ("o", "s")
            and not dom.is_covered(leaf)
            and not dom.is_supported(leaf)
            and dom.level_of(leaf)):
        return None
    params = fit.conf("width_outside") if t0 in ("o", "s") else fit.conf("width_circulation")
    return float(params[0]) if mode == "target" else fail_threshold(params)


def solve(root: dom.Node, targets: dict[str, SpaceReq], fit: Fitness, arm: str,
          *, strip: bool = True, weight_proportion: float = 0.3,
          min_width_generic: float = 1.2, max_nfev: int = 4000):
    """`solver.solve_ratios(perpendicular=True)` with this arm's switches.

    Arm A reproduces `solver.solve_ratios` exactly (asserted by the arm-A check
    in the bead's write-up); each other arm changes one or more of the three
    flags in `ARM_FLAGS`.
    """
    narrowest, generic_mode, room_width = ARM_FLAGS[arm]

    free = solver.free_branches(root)
    if not free:
        return None
    if strip:
        for b in free:
            b.division = [0.5, 0.5]
    x0 = np.array([b.division[0] for b in free], dtype=float)
    all_leaves = [leaf for lvl in dom.levels(root) for leaf in lvl.leaves()]

    def width(leaf: dom.Node) -> float:
        return geometry.length_narrowest(leaf) if narrowest else solver._width(leaf)

    # Static per-leaf generic targets: the roof-garden test reads is_covered /
    # is_supported, which are tree ADDRESS predicates -- fixed with the topology.
    gmin = {id(lf): (min_width_generic if generic_mode == "knob"
                     else generic_width_target(lf, fit, generic_mode))
            for lf in all_leaves}

    def apply(x: np.ndarray) -> None:
        for j, b in enumerate(free):
            b.division = [float(x[j]), float(x[j])]
        geometry.clear_cache()

    def residuals(x: np.ndarray) -> list[float]:
        apply(x)
        r: list[float] = []
        for leaf in all_leaves:
            req = targets.get(leaf.type)
            if req is not None:
                area = geometry.area(leaf)
                r.append((area - req.size) / req.size)
                if room_width:
                    r.append(min(0.0, (width(leaf) - req.width) / req.width))
                if weight_proportion:
                    asp = solver._aspect(leaf)
                    r.append(weight_proportion * max(0.0, (asp - req.proportion) / req.proportion))
            else:
                t = gmin.get(id(leaf))
                if t:
                    r.append(min(0.0, (width(leaf) - t) / t))
        return r

    res = least_squares(residuals, x0, bounds=(solver._EPS, 1 - solver._EPS),
                        max_nfev=max_nfev, xtol=1e-10, ftol=1e-10)
    apply(res.x)
    return res


# --------------------------------------------------------------------------- #
def fail_family(line: str) -> str:
    """Coarse family of a fail line, for the census."""
    if line.startswith("level "):
        return " ".join(line.split()[2:])
    parts = line.split()
    return parts[-1] if len(parts) < 3 else " ".join(parts[1:])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--programme", action="append", choices=PROGRAMMES,
                    help="restrict to these (default: all four)")
    ap.add_argument("--corpus", default="coldstart-c836457+orth-*.dom",
                    help="glob for the artefacts to take topologies from")
    ap.add_argument("--nm", type=int, default=0,
                    help="run innerloop.optimise for this many evals from each "
                         "arm's point (0: report the solved point only)")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--orth", choices=("on", "off", "auto"), default="auto",
                    help="HOMEMAKER_ORTHOGONAL_DIVISION for the scoring. 'auto' "
                         "reads it from the '+orth' tag in each filename, which "
                         "is right for the coldstart corpus and WRONG for any "
                         "artefact not named that way -- `hand-3storey.dom` is "
                         "a +orth design with no tag in its name (§39.70), so "
                         "pass --orth on for it")
    ap.add_argument("--no-strip", dest="strip", action="store_false",
                    help="slide the artefact's committed ratios instead of "
                         "starting every cut at 0.5 -- what `compose.refine` does")
    args = ap.parse_args(argv)
    programmes = args.programme or list(PROGRAMMES)
    arms = args.arms.split(",")

    print(f"width_outside      fails below {fail_threshold([3.0, 0.3]):.3f} m")
    print(f"width_circulation  fails below {fail_threshold([2.4, 0.2]):.3f} m")
    print(f"min_width_generic  {1.2:.3f} m  (arms A, B)\n")

    head = "%-26s %4s" % ("artefact", "dof")
    for a in arms:
        head += "  %10s" % a
    print(head + "      (score / fails at the solved point)")

    totals = {a: [0, 0.0] for a in arms}          # fails, score
    fams = {a: collections.Counter() for a in arms}
    nm_totals = {a: [0, 0.0] for a in arms}

    for prog_name in programmes:
        prog = REPO / "examples" / prog_name
        conf, cost = load_config(prog)
        targets = load_programme_dir(str(prog))
        for path in sorted(prog.glob(args.corpus)):
            orth = ("+orth" in path.name if args.orth == "auto"
                    else args.orth == "on")
            geometry.ORTHOGONAL_DIVISION = orth
            fit = Fitness(conf, cost)
            tag = f"{prog_name}/{path.stem.split('-')[-1]}"
            row = ""
            nm_row = ""
            dof = None
            for a in arms:
                root = dom.load(str(path))
                geometry.clear_cache()
                if dof is None:
                    dof = len(solver.free_branches(root))
                solve(root, targets, fit, a, strip=args.strip)
                geometry.clear_cache()
                s, fails = Fitness(conf, cost).score_with_fails(root)
                totals[a][0] += len(fails)
                totals[a][1] += s
                for fl in fails:
                    fams[a][fail_family(fl)] += 1
                row += "  %6.4f/%-3d" % (s, len(fails))
                if args.nm:
                    r = innerloop.optimise(root, str(prog), x0=None, budget=args.nm)
                    nm_totals[a][0] += r.n_fails
                    nm_totals[a][1] += r.fitness
                    nm_row += "  %6.4f/%-3d" % (r.fitness, r.n_fails)
            print("%-26s %4d%s" % (tag, dof, row))
            if args.nm:
                print("%-26s %4s%s   <- after NM %d" % ("", "", nm_row, args.nm))

    print()
    print("%-26s %4s" % ("TOTAL", "") + "".join(
        "  %6.4f/%-3d" % (totals[a][1], totals[a][0]) for a in arms))
    if args.nm:
        print("%-26s %4s" % ("TOTAL after NM", "") + "".join(
            "  %6.4f/%-3d" % (nm_totals[a][1], nm_totals[a][0]) for a in arms))

    print("\nfail families at the solved point")
    keys = sorted({k for a in arms for k in fams[a]},
                  key=lambda k: -max(fams[a][k] for a in arms))
    print("%-28s" % "" + "".join("  %5s" % a for a in arms))
    for k in keys:
        print("%-28s" % k[:28] + "".join("  %5d" % fams[a][k] for a in arms))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

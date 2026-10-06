"""`homemaker-py-jak`: is the search building the same outdoor space in worse
shapes?

§39.35 found, over twelve matched runs, the population of outdoor cells flat
and its narrow tail growing (2 -> 9 below the width fail edge), with a paired
delta sitting exactly on the MDD -- unresolved. Its to-do (1) was "re-measure
at the next corpus sweep". There have been three since. This is that
re-measurement, with one ruler for every corpus: today's scorer, the fitted
rectangle's short side as the width (§39.102), and two thresholds that do not
depend on any ruling -- a door's width (1.2 m), and half a metre.

Cells counted: outdoor cells the scorer ASKS about width -- on the ground,
covered, or supported; a roof garden over nothing is waived -- as the scorer
sees them, after `preprocess_building` and `merge_divided`.

The corpora were searched against different objectives (the outdoor width
target itself moved from 3.0 m to 2.3 m at §39.87), so this is a description
of four populations, not an A/B: no column is a control for another.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 PYTHONPATH=src python experiments/diag_jak_outdoor_slivers.py
    ... --self-test
"""

from __future__ import annotations

import argparse
import statistics as st
import sys
from pathlib import Path

from homemaker_layout import dom, geometry
from homemaker_layout.fitness import FAIL_THRESHOLD, Fitness, load_config

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")


def outdoor_cells(root, fit) -> "list[tuple[float, float, bool, int]]":
    """``(width, area, fails on width, storey)`` of every outdoor cell the
    scorer asks about width, on the tree as the scorer evaluates it."""
    geometry.clear_cache()
    geometry.mark_voids(root)
    fit.preprocess_building(root)
    dom.merge_divided(root, allow_sahn=bool(fit.conf("allow_sahn_circulation")))
    geometry.clear_cache()
    out = []
    for li, lvl in enumerate(dom.levels(root)):
        for lf in lvl.leaves():
            if not dom.is_outside(lf) or not dom.is_usable(lf):
                continue
            if not dom.is_covered(lf) and not dom.is_supported(lf) and li:
                continue                    # the roof-garden waiver
            out.append((geometry.usable_width(lf), geometry.area(lf),
                        fit.quality_width(lf) < FAIL_THRESHOLD, li))
    return out


def corpora() -> "list[str]":
    """Objective stamps with an orthogonal coldstart corpus, oldest first by
    the first commit that added one of its files."""
    import subprocess

    stamps = sorted({p.name.split("coldstart-")[1].split("-500000")[0]
                     for name in PROGRAMMES
                     for p in (REPO / "examples" / name).glob("coldstart-*+orth-500000-s*.dom")})

    def born(stamp):
        r = subprocess.run(["git", "log", "--diff-filter=A", "--format=%ct", "--",
                            f"examples/*/coldstart-{stamp}-500000-s0.dom"],
                           cwd=REPO, capture_output=True, text=True)
        return min((int(x) for x in r.stdout.split()), default=0)

    return sorted(stamps, key=born)


def census() -> None:
    print(f"{'corpus':<14} {'designs':>7} {'outdoor cells':>14} {'per design':>11} "
          f"{'fail width':>11} {'< 1.2 m':>8} {'< 0.5 m':>8} {'designs with a sliver < 1.2 m':>30} "
          f"{'narrowest':>10} {'median width':>13}")
    for stamp in corpora():
        cells, designs, with_sliver = [], 0, 0
        for name in PROGRAMMES:
            prog = REPO / "examples" / name
            fit = Fitness(*load_config(prog))
            for p in sorted(prog.glob(f"coldstart-{stamp}-500000-s*.dom")):
                got = outdoor_cells(dom.load(str(p)), fit)
                designs += 1
                with_sliver += any(w < 1.2 for w, *_ in got)
                cells += got
        w = [c[0] for c in cells]
        print(f"{stamp:<14} {designs:7d} {len(cells):14d} {len(cells) / designs:11.1f} "
              f"{sum(c[2] for c in cells):11d} {sum(x < 1.2 for x in w):8d} "
              f"{sum(x < 0.5 for x in w):8d} {with_sliver:30d} {min(w):10.3f} {st.median(w):13.2f}")


def self_test() -> int:
    """A cell 0.3 m wide must be counted and must fail on width; the same
    cell as a roof garden over nothing must not be counted at all."""
    from homemaker_layout import dom_v2

    def doc(*trees):
        return {"format": "homemaker-dom", "version": 2, "frame": {"u": [1.0, 0.0]},
                "plot": [[0, 0], [20, 0], [20, 10], [0, 10]], "wall_outer": 0.0,
                "wall_inner": 0.08,
                "storeys": [{"elevation": 3.0 * i, "height": 3.0, "tree": t}
                            for i, t in enumerate(trees)]}

    fit = Fitness(*load_config(REPO / "examples" / "programme-house"))
    sliver = {"cut": "v", "at": 0.015, "low": {"cell": "O"}, "high": {"cell": "l1"}}
    was = geometry.ORTHOGONAL_DIVISION
    geometry.ORTHOGONAL_DIVISION = False
    try:
        ground = outdoor_cells(dom_v2.from_document(doc(sliver), native=True), fit)
        over_garden = {"cut": "v", "at": 0.5, "low": {"cell": "O"}, "high": {"cell": "l1"}}
        roof = outdoor_cells(dom_v2.from_document(
            doc(over_garden, {"low": {"cell": "O"}, "high": {"cell": "b1"}}), native=True), fit)
    finally:
        geometry.ORTHOGONAL_DIVISION = was
        geometry.clear_cache()
    ok = (len(ground) == 1 and abs(ground[0][0] - 0.3) < 1e-6 and ground[0][2]
          and [c[3] for c in roof] == [0])
    print("self-test", "PASSED" if ok else f"FAILED: {ground} {roof}")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    geometry.ORTHOGONAL_DIVISION = True
    census()
    return 0


if __name__ == "__main__":
    sys.exit(main())

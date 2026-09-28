"""`homemaker-py-ekc`: how exact is the shape-curve DP's verdict, really?

§37.2 validated the DP on harbor-house-l0 and recorded "0 false negatives", and
`driver._evaluate` quotes that number in the comment above the hard prune it
licenses (`homemaker-py-wkh`): a DP verdict of INFEASIBLE discards the topology
outright when the incumbent has zero fails. ekc's option (b) asks for that
false-positive rate to be re-characterised on a less rectangular plot before
`--shapecurve-warmstart` or `--shapecurve-prune` is rolled out wider. This is
that measurement, over the twelve committed corpus artefacts.

Four checks, each isolating one way the DP and the scorer can disagree:

  --width        the DP tests `_dims` -- ((edge0+edge2)/2, (edge1+edge3)/2) --
                 against a `wmin` inverted from the same conf `quality_width`
                 reads with `geometry.length_narrowest`. Mean-of-pairs is never
                 smaller than the shortest edge, so the DP can pass a leaf the
                 scorer fails. Counts leaves in that band.
  --positives    run `solve` and score the point it REALISES. A feasible verdict
                 promises no size/width/proportion fail there; this counts the
                 ones that appear anyway (§37.2's own method).
  --negatives    the dangerous direction. A committed point with no shape fail is
                 a WITNESS that a feasible assignment exists, so an INFEASIBLE
                 verdict on that topology is provably wrong.
  --cause        attribute each false negative. Two distinct causes are separable
                 by re-running with one mechanism neutered:
                   * `dom.merge_divided`, which `Fitness.score_with_fails` applies
                     IN PLACE before evaluating, is not modelled by the DP -- so
                     the DP bounds sibling leaves the scorer fuses into one. Two
                     narrow leaves that each miss `wmin` can be one leaf that
                     clears it comfortably.
                   * `_solve_all_levels` REALISES each storey before checking the
                     one above (it must: an upper storey's boxes are read off the
                     lower storey's realised geometry). That commits level 0 to a
                     single point without knowing what level 1 needs, so a
                     different level-0 choice can be feasible when the DP's is not.

    python experiments/diag_ekc_shapecurve.py [--all] [--width] [--positives]
                                              [--negatives] [--cause]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from homemaker_layout import dom, geometry, shapecurve  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402
from homemaker_layout.fitness_cmd import load_config  # noqa: E402

PROGRAMMES = ("harbor-house", "health-centre", "maple-court", "programme-house")
CORPUS = "coldstart-c836457+orth-*.dom"
SHAPE = ("size", "width", "proportion")


def artefacts():
    """(tag, path, conf, cost) for every corpus artefact, newest objective first."""
    for name in PROGRAMMES:
        prog = REPO / "examples" / name
        conf, cost = load_config(prog)
        for path in sorted(prog.glob(CORPUS)):
            yield f"{name}/{path.stem.split('-')[-1]}", path, conf, cost


def _load(path, orth=True):
    geometry.ORTHOGONAL_DIVISION = orth
    root = dom.load(str(path))
    geometry.clear_cache()
    return root


def shape_fails(fails):
    return [f for f in fails if f.split()[-1] in SHAPE]


# --------------------------------------------------------------------------- #
def check_width() -> None:
    """Leaves where the DP's mean-pair width clears `wmin` and the true
    narrowest edge does not -- the band in which the DP is optimistic."""
    print("=== width measure: DP `_dims` min vs geometry.length_narrowest ===")
    total = constrained = optimistic = 0
    worst = (1.0, "")
    for tag, path, conf, cost in artefacts():
        root = _load(path)
        fit = Fitness(conf, cost)
        fit.preprocess_building(root)
        geometry.clear_cache()
        for lvl in dom.levels(root):
            for leaf in lvl.leaves():
                bounds = shapecurve.leaf_constraints(fit, leaf)
                w, h = shapecurve._dims(leaf)
                dp_min, narrow = min(w, h), geometry.length_narrowest(leaf)
                total += 1
                if bounds.wmin <= 0:
                    continue
                constrained += 1
                if dp_min > 0 and narrow / dp_min < worst[0]:
                    worst = (narrow / dp_min,
                             f"{tag} {leaf.type} dp={dp_min:.2f} narrow={narrow:.2f}")
                if dp_min >= bounds.wmin > narrow:
                    optimistic += 1
    print(f"  leaves {total}, width-constrained {constrained}")
    print(f"  DP passes on width where the scorer fails: {optimistic}")
    print(f"  worst narrowest/dp-min ratio: {worst[0]:.3f}  ({worst[1]})")


def check_positives() -> None:
    """Score the point `solve` realises; a feasible verdict promises no shape fail."""
    print("=== false positives: shape fails at the DP's own realised point ===")
    feasible_n = bad = 0
    for tag, path, conf, cost in artefacts():
        root = _load(path)
        if not shapecurve.eligible(root):
            print(f"  {tag:22s} ineligible")
            continue
        ok, _ = shapecurve.solve(root, Fitness(conf, cost))
        geometry.clear_cache()
        _score, fails = Fitness(conf, cost).score_with_fails(root)
        sf = shape_fails(fails)
        if ok:
            feasible_n += 1
            if sf:
                bad += 1
        print("  %-22s %-11s %d shape fails  %s" % (
            tag, "feasible" if ok else "infeasible", len(sf),
            ", ".join(sorted({f.split()[-1] for f in sf})) or "-"))
    print(f"  feasible verdicts {feasible_n}; with a shape fail at the realised "
          f"point: {bad}")


def check_negatives() -> None:
    """A committed shape-fail-free point is a witness; INFEASIBLE there is wrong."""
    print("=== false negatives: infeasible verdict with a witness ===")
    n = 0
    for tag, path, conf, cost in artefacts():
        root = _load(path)
        _score, fails = Fitness(conf, cost).score_with_fails(root)
        witness = not shape_fails(fails)

        probe = _load(path)
        ok = shapecurve.is_feasible(probe, Fitness(conf, cost))
        bad = witness and not ok
        n += bad
        print("  %-22s committed %-14s DP %-11s %s" % (
            tag, "shape-fail-free" if witness else "has shape fails",
            "feasible" if ok else "infeasible", "<-- FALSE NEGATIVE" if bad else ""))
    print(f"  false negatives: {n} of 12")


def check_cause() -> None:
    """Separate the two mechanisms by neutering each in turn."""
    print("=== attributing the false negatives ===")
    print("  %-22s %7s %7s %-11s %-11s %-11s" % (
        "artefact", "storeys", "merged", "DP as-is", "DP merged", "no-realise"))
    merged_leaves = 0
    for tag, path, conf, cost in artefacts():
        a = _load(path)
        storeys = len(dom.levels(a))
        before = sum(len(l.leaves()) for l in dom.levels(a))
        v_asis = shapecurve.is_feasible(a, Fitness(conf, cost))

        b = _load(path)
        dom.merge_divided(b)
        geometry.clear_cache()
        after = sum(len(l.leaves()) for l in dom.levels(b))
        v_merged = shapecurve.is_feasible(b, Fitness(conf, cost))
        merged_leaves += before - after

        c = _load(path)
        saved = shapecurve.realise
        shapecurve.realise = lambda *a, **k: None
        try:
            v_held = shapecurve.is_feasible(c, Fitness(conf, cost))
        finally:
            shapecurve.realise = saved

        note = ""
        if v_merged and not v_asis:
            note = "  <-- the unmodelled merge"
        elif v_held and not v_asis:
            note = "  <-- the greedy per-storey realisation"
        print("  %-22s %7d %7d %-11s %-11s %-11s%s" % (
            tag, storeys, before - after,
            "feasible" if v_asis else "infeasible",
            "feasible" if v_merged else "infeasible",
            "feasible" if v_held else "infeasible", note))
    print(f"  leaves the scorer merges away, corpus-wide: {merged_leaves}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    for flag in ("width", "positives", "negatives", "cause"):
        ap.add_argument(f"--{flag}", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args(argv)
    run = {k: getattr(args, k) for k in ("width", "positives", "negatives", "cause")}
    if args.all or not any(run.values()):
        run = dict.fromkeys(run, True)
    for name, fn in (("width", check_width), ("positives", check_positives),
                     ("negatives", check_negatives), ("cause", check_cause)):
        if run[name]:
            fn()
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

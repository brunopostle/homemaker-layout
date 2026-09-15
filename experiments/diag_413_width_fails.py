#!/usr/bin/env python3
"""Classify every soft ``width`` fail in the corpus (homemaker-py-413, DESIGN.md
§39.30/§39.31).

The one thing `bk9` made worse. Over the twelve matched runs, rescored §39.12
baseline against `bk9`, soft `width` went 7 -> 13 while `proportion` went
11 -> 7. §39.30 offered a mechanism with no measurement behind it: a corridor
now has no aspect cap (§39.22) and no size cap (§39.23), so a shape that used to
be refused as a bad PROPORTION can now be built and refused as a bad WIDTH
instead -- relabelling, not regression.

This measures it. For every width fail in both arms it reports the failing
leaf's type, generic class, declared usage, realised width/aspect/area, the
width requirement it was judged against, and -- for circulation leaves -- the
COUNTERFACTUAL: what `quality_proportion` and `quality_size` would have scored
under the pre-`bk9` caps (`proportion_circulation = [1.5, 0.5]`,
`size_circulation = [0.0, 14.0]`), i.e. whether that same shape would have been
refused by the removed terms.

The decision rule is the bead's:

* circulation leaves that the removed caps would have refused  -> RELABELLED
* circulation leaves too narrow for a person to use            -> REGRESSION
* habitable rooms                                              -> REGRESSION

Both arms are scored with the CURRENT objective, which is how §39.30/§39.31
produced the 7 -> 13 reading being explained; `verify_results_table.py` must
report the twelve `bk9` rows verified before this means anything.

Usage::

    python experiments/diag_413_width_fails.py [--tsv out.tsv]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from homemaker_layout import dom as dom_mod  # noqa: E402
from homemaker_layout import fitness as fit_mod  # noqa: E402
from homemaker_layout import geometry  # noqa: E402

PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")
SEEDS = (0, 1, 2)
ARMS = {"baseline": "055d710", "bk9": "99c85ec"}

# The caps §39.22/§39.23 removed, as the corpus configs carried them.
OLD_PROPORTION_CIRCULATION = [1.5, 0.5]
OLD_SIZE_CIRCULATION = [0.0, 14.0]

# Below this a corridor is not a space a person can use. 1.97 m is where the
# width factor itself crosses FAIL_THRESHOLD; a door is 1.2 m (`door_width`);
# 0.9 m is the narrowest an accessible route is ever drawn. A fail between
# 1.2 m and 1.97 m is a corridor the objective refuses but a person could still
# walk down; below 1.2 m it is not a corridor at all.
WALKABLE = 1.2


def current_objective() -> str:
    r = subprocess.run(
        ["git", "log", "-1", "--format=%h", "--", "src/homemaker_layout/fitness.py"],
        cwd=REPO, capture_output=True, text=True)
    return r.stdout.strip() or "unknown"


def fail_edge(target: float, sigma: float) -> float:
    """Width at which the clipped gaussian crosses FAIL_THRESHOLD from below."""
    import math
    return target - sigma * math.sqrt(2.0 * math.log(1.0 / fit_mod.FAIL_THRESHOLD))


def leaf_index(root) -> dict:
    """(level index, leaf id) -> leaf, on the tree as `evaluate` left it.

    Fail strings are emitted in phase 2, after `merge_divided`, as
    "{level_id}/{leaf.id} width" with level_id the enumeration index of
    `dom.levels(root)` -- so this must be built from the SAME post-evaluation
    tree, not a fresh load.
    """
    out = {}
    for li, lvl in enumerate(dom_mod.levels(root)):
        for leaf in lvl.leaves():
            out[(li, leaf.id)] = leaf
    return out


def classify(rec: dict) -> str:
    """The bead's decision rule, applied to one width fail.

    The bead expected two answers (corridor or habitable room) and there is a
    third the corpus actually produces: an OUTSIDE leaf. `quality_width` waives
    open-air outdoor space above ground, so an outside leaf can only reach the
    width factor by being covered, supported, or on the ground floor -- and the
    removed caps never applied to it either way, so it is neither relabelling
    nor anything the `hxi` ruling bears on.
    """
    if rec["klass"] == "o":
        return "OUTSIDE (untouched by the removed caps)"
    if rec["klass"] != "c":
        return "REGRESSION (habitable room)"
    if rec["old_proportion_fail"] or rec["old_size_fail"]:
        return "RELABELLED (removed cap refused it)"
    if rec["width"] < WALKABLE:
        return "REGRESSION (unusable corridor)"
    return "NEW (corridor the old objective accepted)"


def census(fit, root, graphs, programme: str, seed: int, arm: str) -> list[dict]:
    """Every circulation leaf, and every outside leaf the width factor applies
    to, whether or not it failed anything.

    The fail set alone cannot answer the `hxi` question. A width fail is a
    corridor the objective REFUSED; the ruling is about whether an uncapped
    corridor is a shape worth building, which is a question about the whole
    population. §39.22 characterised it for the baseline (111 leaves, median
    aspect 1.67, 2 width fails) -- this is the same table for both arms.
    """
    out = []
    for li, lvl in enumerate(dom_mod.levels(root)):
        for leaf in lvl.leaves():
            klass = fit_mod._generic_class(leaf)
            if klass not in ("c", "o"):
                continue
            if klass == "o" and not (
                    dom_mod.is_covered(leaf) or dom_mod.is_supported(leaf)
                    or not dom_mod.level_of(leaf)):
                continue   # open-air above ground: `quality_width` waives it
            G = graphs[li]
            out.append({
                "programme": programme, "seed": seed, "arm": arm,
                "klass": klass, "level": li, "lid": leaf.id,
                "width": geometry.length_narrowest(leaf),
                "aspect": geometry.aspect(leaf),
                "area": geometry.area(leaf),
                "q_width": fit.quality_width(leaf),
                "q_proportion": fit.quality_proportion(leaf),
                "q_size": fit.quality_size(leaf),
                "q_crinkliness": fit.quality_uncrinkliness(
                    leaf, G, geometry.boundary_groups(lvl)),
                "old_proportion": fit_mod._clipped_gaussian(
                    geometry.aspect(leaf), OLD_PROPORTION_CIRCULATION[0],
                    OLD_PROPORTION_CIRCULATION[1], "below"),
                "old_size": fit_mod.gaussian(
                    geometry.area(leaf), 1.0, *OLD_SIZE_CIRCULATION),
            })
    return out


def outdoor_fraction(fit, root) -> tuple[float, int, int]:
    """(outdoor fraction of usable area, outside leaves, width-eligible ones).

    §39.25 turned `force_roof_garden` ON and `ratio_outside` OFF, and recorded
    that as the one change in §39.22-§39.25 whose risk was NOT measured:
    "nothing here proves the outdoor fraction will not drift upward once the
    search is free to raise it... the re-baseline (bk9) is what shows that, and
    the fraction is worth recording in it explicitly." It never was. This is
    that record.

    Width-eligible = the waiver in `quality_width` does not apply, i.e. the leaf
    is on the ground floor, covered, or supported — the only outside leaves that
    can produce a width fail at all.
    """
    area_all, areas = fit._areas(root)
    frac = (sum(v for k, v in areas.items() if k in dom_mod.GENERIC_OUTSIDE)
            / area_all) if area_all else 0.0
    n_out = n_elig = 0
    for lvl in dom_mod.levels(root):
        for leaf in lvl.leaves():
            if fit_mod._generic_class(leaf) != "o":
                continue
            n_out += 1
            if (dom_mod.is_covered(leaf) or dom_mod.is_supported(leaf)
                    or not dom_mod.level_of(leaf)):
                n_elig += 1
    return frac, n_out, n_elig


def collect(programme: str, seed: int, arm: str) -> list[dict]:
    pdir = REPO / "examples" / programme
    src = pdir / f"coldstart-{ARMS[arm]}-500000-s{seed}.dom"
    if not src.exists():
        raise SystemExit(f"missing artefact: {src}")

    conf, cost = fit_mod.load_config(pdir)
    fit = fit_mod.Fitness(conf, cost)
    root = dom_mod.load(str(src))
    _, fails = fit.score_with_fails(root)

    from homemaker_layout import graph as graph_mod
    graphs = graph_mod.build_graphs(root, fit.conf("door_width") or 1.2)

    leaves = leaf_index(root)
    recs = []
    for f in fails:
        if not f.endswith(" width"):
            continue
        where = f[: -len(" width")]
        li, _, lid = where.partition("/")
        leaf = leaves.get((int(li), lid))
        if leaf is None:                       # should not happen; say so loudly
            raise SystemExit(f"{programme} s{seed} {arm}: no leaf for fail {f!r}")

        klass = fit_mod._generic_class(leaf)
        if klass in ("o", "s"):
            params = fit.conf("width_outside")
        elif klass == "c":
            params = fit.conf("width_circulation")
        else:
            params = fit.get_space_params(leaf.type, "width")

        width = geometry.length_narrowest(leaf)
        aspect = geometry.aspect(leaf)
        area = geometry.area(leaf)

        # Counterfactual under the removed caps, for circulation only.
        old_prop = old_size = None
        if klass == "c":
            old_prop = fit_mod._clipped_gaussian(
                aspect, OLD_PROPORTION_CIRCULATION[0],
                OLD_PROPORTION_CIRCULATION[1], "below")
            old_size = fit_mod.gaussian(
                area, 1.0, OLD_SIZE_CIRCULATION[0], OLD_SIZE_CIRCULATION[1])

        rec = {
            "programme": programme, "seed": seed, "arm": arm,
            "level": int(li), "lid": lid,
            "type": leaf.type, "klass": klass or "room",
            "usage": fit.usage_of(leaf) or "-",
            "width": width, "aspect": aspect, "area": area,
            "w_target": params[0], "w_sigma": params[1],
            "w_edge": fail_edge(params[0], params[1]),
            "q_width": fit.quality_width(leaf),
            "old_proportion": old_prop, "old_size": old_size,
            "old_proportion_fail": (old_prop is not None
                                    and old_prop < fit_mod.FAIL_THRESHOLD),
            "old_size_fail": (old_size is not None
                              and old_size < fit_mod.FAIL_THRESHOLD),
            "also_fails_proportion": f"{where} proportion" in fails,
            "also_fails_size": f"{where} size" in fails,
            "also_fails_crinkliness": f"{where} crinkliness" in fails,
            "covered": dom_mod.is_covered(leaf),
            "supported": dom_mod.is_supported(leaf),
        }
        rec["verdict"] = classify(rec)
        recs.append(rec)
    frac, n_out, n_elig = outdoor_fraction(fit, root)
    run = {"programme": programme, "seed": seed, "arm": arm,
           "outdoor_fraction": frac, "outside_leaves": n_out,
           "width_eligible": n_elig, "width_fails": len(recs)}
    return recs, census(fit, root, graphs, programme, seed, arm), run


COLUMNS = ("arm", "programme", "seed", "level", "lid", "type", "klass", "usage",
           "width", "w_target", "w_edge", "q_width", "aspect", "area",
           "old_proportion", "old_size", "old_proportion_fail", "old_size_fail",
           "also_fails_crinkliness", "covered", "supported", "verdict")


def fmt(v) -> str:
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tsv", type=Path,
                    default=REPO / "experiments" / "results" / "width_fails_413.tsv")
    ap.add_argument("--circ-tsv", type=Path,
                    default=REPO / "experiments" / "results" / "circulation_census_413.tsv")
    ap.add_argument("--runs-tsv", type=Path,
                    default=REPO / "experiments" / "results" / "outdoor_fraction_413.tsv")
    args = ap.parse_args()

    print(f"objective {current_objective()} — both arms rescored with it\n")

    rows: list[dict] = []
    circ: list[dict] = []
    runs: list[dict] = []
    for arm in ("baseline", "bk9"):
        for programme in PROGRAMMES:
            for seed in SEEDS:
                r, c, run = collect(programme, seed, arm)
                rows.extend(r)
                circ.extend(c)
                runs.append(run)

    args.tsv.parent.mkdir(parents=True, exist_ok=True)
    with args.tsv.open("w") as fh:
        fh.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            fh.write("\t".join(fmt(r[c]) for c in COLUMNS) + "\n")

    for arm in ("baseline", "bk9"):
        sub = [r for r in rows if r["arm"] == arm]
        print(f"=== {arm} ({ARMS[arm]}) — {len(sub)} width fails ===")
        print(f"{'programme':16} {'s':>1} {'leaf':14} {'type':5} {'cls':4} "
              f"{'usage':8} {'width':>6} {'targ':>5} {'edge':>5} "
              f"{'aspect':>6} {'area':>7} {'oldprop':>7} {'oldsize':>7}  verdict")
        for r in sorted(sub, key=lambda r: (r["programme"], r["seed"])):
            op = "-" if r["old_proportion"] is None else f"{r['old_proportion']:.3f}"
            os_ = "-" if r["old_size"] is None else f"{r['old_size']:.3f}"
            print(f"{r['programme']:16} {r['seed']:>1} "
                  f"{r['level']}/{r['lid']:12.12} {r['type']:5} {r['klass']:4} "
                  f"{r['usage']:8} {r['width']:6.2f} {r['w_target']:5.2f} "
                  f"{r['w_edge']:5.2f} {r['aspect']:6.2f} {r['area']:7.2f} "
                  f"{op:>7} {os_:>7}  {r['verdict']}")

        by_class: dict[str, int] = {}
        by_verdict: dict[str, int] = {}
        for r in sub:
            by_class[r["klass"]] = by_class.get(r["klass"], 0) + 1
            by_verdict[r["verdict"]] = by_verdict.get(r["verdict"], 0) + 1
        print(f"  by class:   " + ", ".join(f"{k}={v}" for k, v in sorted(by_class.items())))
        print(f"  by verdict: " + ", ".join(f"{k}={v}" for k, v in sorted(by_verdict.items())))
        print()

    # --- the width fail delta, per programme, so a +6 total can be read ---
    print("=== width fails per programme (baseline -> bk9) ===")
    print(f"{'programme':16} {'base':>5} {'bk9':>5} {'delta':>6}   by class (bk9)")
    for programme in PROGRAMMES:
        b = [r for r in rows if r["arm"] == "baseline" and r["programme"] == programme]
        k = [r for r in rows if r["arm"] == "bk9" and r["programme"] == programme]
        cls: dict[str, int] = {}
        for r in k:
            cls[r["klass"]] = cls.get(r["klass"], 0) + 1
        print(f"{programme:16} {len(b):>5} {len(k):>5} {len(k)-len(b):>+6}   "
              + ", ".join(f"{x}={y}" for x, y in sorted(cls.items())))
    print()

    print("=== width fails by leaf class (the +6, decomposed) ===")
    print(f"{'class':22} {'base':>5} {'bk9':>5} {'delta':>6}")
    for klass, label in (("c", "circulation"), ("o", "outside"), ("room", "habitable room")):
        b = sum(1 for r in rows if r["arm"] == "baseline" and r["klass"] == klass)
        k = sum(1 for r in rows if r["arm"] == "bk9" and r["klass"] == klass)
        print(f"{label:22} {b:>5} {k:>5} {k-b:>+6}")
    print()

    # --- the circulation population: what the hxi ruling is actually about ---
    def q(vals, p):
        vals = sorted(vals)
        return vals[min(len(vals) - 1, int(p * len(vals)))] if vals else float("nan")

    print("=== every circulation leaf, both arms (§39.22's table, re-measured) ===")
    print(f"{'arm':10} {'n':>4} {'width p25':>10} {'median':>7} {'p75':>7} "
          f"{'aspect med':>11} {'area med':>9} {'w<1.97':>7} {'w<1.2':>6}")
    for arm in ("baseline", "bk9"):
        sub = [c for c in circ if c["arm"] == arm and c["klass"] == "c"]
        w = [c["width"] for c in sub]
        print(f"{arm:10} {len(sub):>4} {q(w, .25):>10.2f} {q(w, .5):>7.2f} "
              f"{q(w, .75):>7.2f} {q([c['aspect'] for c in sub], .5):>11.2f} "
              f"{q([c['area'] for c in sub], .5):>9.2f} "
              f"{sum(1 for x in w if x < 1.97):>7} {sum(1 for x in w if x < WALKABLE):>6}")
    print()
    print(f"{'arm':10} " + " ".join(f"{k:>14}" for k in
          ("width", "proportion", "size", "crinkliness")) + "   (mean quality / fails)")
    for arm in ("baseline", "bk9"):
        sub = [c for c in circ if c["arm"] == arm and c["klass"] == "c"]
        cells = []
        for key in ("q_width", "q_proportion", "q_size", "q_crinkliness"):
            vals = [c[key] for c in sub]
            nf = sum(1 for v in vals if v < fit_mod.FAIL_THRESHOLD)
            cells.append(f"{sum(vals)/len(vals):.3f} / {nf:>3}")
        print(f"{arm:10} " + " ".join(f"{c:>14}" for c in cells))
    print()

    print("=== what the removed caps WOULD have refused, over every corridor ===")
    print("(the aspect/size caps §39.22/§39.23 took out, re-applied to both "
          "populations)")
    print(f"{'arm':10} {'n':>4} {'old-prop fails':>15} {'old-size fails':>15} "
          f"{'either':>8}")
    for arm in ("baseline", "bk9"):
        sub = [c for c in circ if c["arm"] == arm and c["klass"] == "c"]
        pf = sum(1 for c in sub if c["old_proportion"] < fit_mod.FAIL_THRESHOLD)
        sf = sum(1 for c in sub if c["old_size"] < fit_mod.FAIL_THRESHOLD)
        ef = sum(1 for c in sub if c["old_proportion"] < fit_mod.FAIL_THRESHOLD
                 or c["old_size"] < fit_mod.FAIL_THRESHOLD)
        print(f"{arm:10} {len(sub):>4} {pf:>15} {sf:>15} {ef:>8}")
    print()

    # --- the hxi ruling's own justification, tested ---
    print("=== is crinkliness catching the corridors the aspect cap used to? ===")
    print("(the ruling: \"no cap on the proportion of a corridor... the "
          "crinkliness rule is\n there to prevent these becoming unpleasant "
          "spaces\" — §39.22)")
    print(f"{'arm':10} {'corridor aspect':>16} {'n':>4} {'crink fails':>12} "
          f"{'rate':>7} {'mean crink q':>13}")
    for arm in ("baseline", "bk9"):
        sub = [c for c in circ if c["arm"] == arm and c["klass"] == "c"]
        for label, keep in (("<= 2.57 (cap would pass)", lambda c: c["aspect"] <= 2.57),
                            ("> 2.57 (cap refused)", lambda c: c["aspect"] > 2.57)):
            g = [c for c in sub if keep(c)]
            if not g:
                continue
            nf = sum(1 for c in g if c["q_crinkliness"] < fit_mod.FAIL_THRESHOLD)
            print(f"{arm:10} {label:>16.16} {len(g):>4} {nf:>12} "
                  f"{nf/len(g):>7.1%} "
                  f"{sum(c['q_crinkliness'] for c in g)/len(g):>13.3f}")
    print()

    # --- the outside population, where the +5 actually lives ---
    print("=== width-eligible outside leaves (ground, covered or supported) ===")
    print(f"{'arm':10} {'n':>4} {'width p25':>10} {'median':>7} {'p75':>7} "
          f"{'w<2.36':>7} {'w<1.2':>6} {'area<2m2':>9}")
    for arm in ("baseline", "bk9"):
        sub = [c for c in circ if c["arm"] == arm and c["klass"] == "o"]
        w = [c["width"] for c in sub]
        print(f"{arm:10} {len(sub):>4} {q(w, .25):>10.2f} {q(w, .5):>7.2f} "
              f"{q(w, .75):>7.2f} {sum(1 for x in w if x < 2.36):>7} "
              f"{sum(1 for x in w if x < WALKABLE):>6} "
              f"{sum(1 for c in sub if c['area'] < 2.0):>9}")
    print()

    # --- paired per-run deltas, against what 12 runs can resolve (§38.22) ---
    # `ab_report.paired_report` is the house convention for this; using it here
    # keeps the MDD comparable with every other A/B in the project.
    from ab_report import paired_report

    print("=== paired per-run width-fail deltas, by class ===")
    print("(mean_diff is baseline - bk9, so NEGATIVE means bk9 has MORE width "
          "fails)")
    print(f"{'class':16} {'base':>5} {'bk9':>5} {'mean d':>7} {'sd':>6} "
          f"{'MDD':>6} {'worse/better':>13}   verdict")
    for klass, label in (("c", "circulation"), ("o", "outside"),
                         ("room", "habitable room"), (None, "all")):
        def per_run(arm):
            return [sum(1 for r in rows if r["arm"] == arm
                        and r["programme"] == programme and r["seed"] == seed
                        and (klass is None or r["klass"] == klass))
                    for programme in PROGRAMMES for seed in SEEDS]
        a, b = per_run("baseline"), per_run("bk9")
        rep = paired_report(a, b, "baseline", "bk9")
        if rep["identical"]:
            verdict = "IDENTICAL on every run"
        elif rep["underpowered"]:
            verdict = "UNDERPOWERED — below its own MDD"
        else:
            verdict = "resolvable"
        print(f"{label:16} {sum(a):>5} {sum(b):>5} {rep['mean_diff']:>+7.2f} "
              f"{rep['sd']:>6.2f} {rep['mdd']:>6.2f} "
              f"{rep['losses_b']:>6}/{rep['wins_b']:<6}   {verdict}")
    print()

    # --- §39.25's unrecorded risk: did the outdoor fraction drift up? ---
    print("=== outdoor fraction per run (the §39.25 record that was never made) ===")
    print(f"{'programme':16} {'s':>1} {'base frac':>10} {'bk9 frac':>9} "
          f"{'delta':>7}   {'base out/elig':>14} {'bk9 out/elig':>13}")
    for programme in PROGRAMMES:
        for seed in SEEDS:
            b = next(r for r in runs if r["arm"] == "baseline"
                     and r["programme"] == programme and r["seed"] == seed)
            k = next(r for r in runs if r["arm"] == "bk9"
                     and r["programme"] == programme and r["seed"] == seed)
            print(f"{programme:16} {seed:>1} {b['outdoor_fraction']:>10.3f} "
                  f"{k['outdoor_fraction']:>9.3f} "
                  f"{k['outdoor_fraction'] - b['outdoor_fraction']:>+7.3f}   "
                  f"{b['outside_leaves']:>6}/{b['width_eligible']:<7} "
                  f"{k['outside_leaves']:>5}/{k['width_eligible']:<7}")
    for label, key in (("mean outdoor fraction", "outdoor_fraction"),
                       ("total outside leaves", "outside_leaves"),
                       ("total width-eligible", "width_eligible")):
        b = [r[key] for r in runs if r["arm"] == "baseline"]
        k = [r[key] for r in runs if r["arm"] == "bk9"]
        if key == "outdoor_fraction":
            print(f"{label:24} baseline {sum(b)/len(b):.3f}   "
                  f"bk9 {sum(k)/len(k):.3f}   {sum(k)/len(k) - sum(b)/len(b):+.3f}")
        else:
            print(f"{label:24} baseline {sum(b):>5}   bk9 {sum(k):>5}   "
                  f"{sum(k) - sum(b):>+5}")
    print()

    args.runs_tsv.parent.mkdir(parents=True, exist_ok=True)
    rcols = ("arm", "programme", "seed", "outdoor_fraction", "outside_leaves",
             "width_eligible", "width_fails")
    with args.runs_tsv.open("w") as fh:
        fh.write("\t".join(rcols) + "\n")
        for r in runs:
            fh.write("\t".join(fmt(r[k]) for k in rcols) + "\n")

    args.circ_tsv.parent.mkdir(parents=True, exist_ok=True)
    ccols = ("arm", "programme", "seed", "klass", "level", "lid", "width", "aspect", "area",
             "q_width", "q_proportion", "q_size", "q_crinkliness",
             "old_proportion", "old_size")
    with args.circ_tsv.open("w") as fh:
        fh.write("\t".join(ccols) + "\n")
        for c in circ:
            fh.write("\t".join(fmt(c[k]) for k in ccols) + "\n")

    print(f"wrote {args.tsv.relative_to(REPO)}")
    print(f"wrote {args.circ_tsv.relative_to(REPO)}")
    print(f"wrote {args.runs_tsv.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

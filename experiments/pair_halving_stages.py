"""Pair one stage of two successive-halving races, candidate by candidate.

A stage-0 run is the same `seed.dom` and rng seed in both races whenever the
field is the same (`successive_halving.seed_int` hashes the candidate's name
and stage), so two races that differ in one search flag give a clean pair per
candidate at stage 0. Later stages pair only the candidates both kept, and
their inputs differ. §39.178 paired the harbor-house guard race this way by
hand; this is that pairing as a tool (`homemaker-py-1d5p`).

    python experiments/pair_halving_stages.py CONTROL/stages.tsv TREATED/stages.tsv \
        --stage 0 --labels any connected

Positive mean difference means the TREATED race ended with fewer fails.

`--family crinkliness` (repeatable) also pairs one fail family. The table's
`families` column keeps only each run's six commonest, so a family is counted
by RE-SCORING each stage's `out.dom`, which needs both work directories:

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/pair_halving_stages.py \
        CONTROL/stages.tsv TREATED/stages.tsv --programme harbor-house \
        --works ~/control-work ~/treated-work --family crinkliness --family level
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ab_report", Path(__file__).resolve().parent / "ab_report.py")
ab_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ab_report)


def read_stage(path, stage: int) -> dict:
    with open(path) as f:
        return {r["candidate"]: r for r in csv.DictReader(f, delimiter="\t")
                if int(r["stage"]) == stage}


def family_counts(work: Path, stage: int, names, programme: str) -> dict:
    """{candidate: Counter of fail families} for one stage's `out.dom` files."""
    import copy, sys
    from collections import Counter
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from successive_halving import REPO, family, load_config
    from homemaker_layout import dom, geometry
    from homemaker_layout.fitness import Fitness
    if not geometry.ORTHOGONAL_DIVISION:
        raise SystemExit("--family re-scores: set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    fit = Fitness(*load_config(REPO / "examples" / programme))
    out = {}
    for c in names:
        r = dom.load(str(work / f"s{stage}" / c / "out.dom")); dom.link(r); geometry.clear_cache()
        _, fails = fit.score_with_fails(copy.deepcopy(r))
        out[c] = Counter(family(f) for f in fails)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("control")
    ap.add_argument("treated")
    ap.add_argument("--stage", type=int, default=0)
    ap.add_argument("--labels", nargs=2, default=("control", "treated"))
    ap.add_argument("--family", action="append", default=[],
                    help="also pair this fail family, re-scored (repeatable)")
    ap.add_argument("--works", nargs=2, type=Path, metavar=("CONTROL", "TREATED"),
                    help="the two races' work directories, for --family")
    ap.add_argument("--programme", help="for --family")
    args = ap.parse_args(argv)
    if args.family and not (args.works and args.programme):
        ap.error("--family needs --works and --programme")

    a, b = read_stage(args.control, args.stage), read_stage(args.treated, args.stage)
    both = sorted(set(a) & set(b))
    only = sorted(set(a) ^ set(b))
    print(f"stage {args.stage}: {len(both)} candidates in both races"
          + (f"; {len(only)} in one only: {' '.join(only)}" if only else ""))
    if len(both) < 2:
        print("too few pairs to report")
        return 1
    for col in ("fails", "structural"):
        r = ab_report.paired_report([float(a[c][col]) for c in both],
                                    [float(b[c][col]) for c in both],
                                    *args.labels)
        print(f"\n{col}:")
        print(ab_report.format_report(r))
    if args.family:
        fa, fb = (family_counts(w, args.stage, both, args.programme) for w in args.works)
        for c in both:   # the re-score must reproduce the table, or it is not the same run
            for fx, t, w in ((fa, a, args.works[0]), (fb, b, args.works[1])):
                if sum(fx[c].values()) != int(t[c]["fails"]):
                    raise SystemExit(f"{w}: {c} re-scores to {sum(fx[c].values())} fails, "
                                     f"the table says {t[c]['fails']}")
    for fam in args.family:
        r = ab_report.paired_report([float(fa[c][fam]) for c in both],
                                    [float(fb[c][fam]) for c in both], *args.labels)
        print(f"\n{fam} fails:")
        print(ab_report.format_report(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

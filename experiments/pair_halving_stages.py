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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("control")
    ap.add_argument("treated")
    ap.add_argument("--stage", type=int, default=0)
    ap.add_argument("--labels", nargs=2, default=("control", "treated"))
    args = ap.parse_args(argv)

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

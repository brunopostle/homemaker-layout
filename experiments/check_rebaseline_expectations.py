"""Check a re-baseline against the expectations written before it ran (DESIGN.md §39.157).

The figures beside each verdict are the evidence; read them, not only the PASS.
`decompose_coldstart.py --objective NEW --against OLD` is the companion: it has
the per-programme deltas, the MDDs and the full family census.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/check_rebaseline_expectations.py \\
        --objective 0d79403+orth --against 4428262+orth

Fail lists are re-scored from each committed artefact with TODAY's code, which
is the new objective; §39.157 showed the old corpus re-scores unchanged under
it, and the script repeats that check before anything else is read.
"""
from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "experiments"))

from homemaker_layout import dom  # noqa: E402
from homemaker_layout.fitness import Fitness, load_config  # noqa: E402

from decompose_coldstart import family  # noqa: E402

TABLE = REPO / "experiments" / "results" / "coldstart_baseline.tsv"
PROGRAMMES = ("programme-house", "health-centre", "harbor-house", "maple-court")


def rows(objective: str) -> "dict[tuple[str, int], dict]":
    with open(TABLE) as f:
        return {(r["programme"], int(r["seed"])): r
                for r in csv.DictReader(f, delimiter="\t") if r["objective"] == objective}


def fails_of(prog: str, dom_name: str) -> "list[str]":
    here = os.getcwd()
    p = REPO / "examples" / prog
    os.chdir(p)
    try:
        return Fitness(*load_config(p)).score_with_fails(dom.load(dom_name))[1]
    finally:
        os.chdir(here)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--objective", required=True)
    ap.add_argument("--against", required=True)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--partial", action="store_true",
                    help="report what is there; every verdict is then PROVISIONAL")
    a = ap.parse_args(argv)
    if os.environ.get("HOMEMAKER_ORTHOGONAL_DIVISION") != "1" and "+orth" in a.objective:
        sys.exit("a +orth objective: set HOMEMAKER_ORTHOGONAL_DIVISION=1")

    new, old = rows(a.objective), rows(a.against)
    want = {(p, s) for p in PROGRAMMES for s in range(a.seeds)}
    missing = sorted(want - set(new))
    if missing and not a.partial:
        print(f"{len(missing)} of {len(want)} runs missing at {a.objective} "
              f"(e.g. {missing[0]}); --partial to read what is there")
        return 1
    tag = " (PROVISIONAL)" if missing else ""

    # old re-scores as committed: the premise of reading the two side by side
    drift = [(k, int(r["fails"]), len(fails_of(k[0], r["dom"])))
             for k, r in sorted(old.items())]
    drift = [d for d in drift if d[1] != d[2]]
    if drift:
        print(f"!! {len(drift)} {a.against} rows no longer reproduce under today's code: {drift[:3]}")

    fl = {k: fails_of(k[0], r["dom"]) for k, r in new.items()}
    fl_old = {k: fails_of(k[0], r["dom"]) for k, r in old.items()}
    verdicts = []

    print(f"\n(1) mean fails inside {a.against}'s range{tag}")
    ok1 = True
    for p in PROGRAMMES:
        o = [int(r["fails"]) for (q, _), r in old.items() if q == p]
        n = [int(r["fails"]) for (q, _), r in new.items() if q == p]
        if not n:
            continue
        m = statistics.mean(n)
        inside = min(o) <= m <= max(o)
        ok1 &= inside
        print(f"    {p:16s} old {sorted(o)}  new {sorted(n)}  mean {m:.1f}  "
              f"{'inside' if inside else 'OUTSIDE'}")
    verdicts.append(("1 fails within range", ok1))

    print(f"\n(2) programme-house median score >= {a.against}'s{tag}")
    o = statistics.median(float(r["score"]) for (q, _), r in old.items() if q == "programme-house")
    n_ = [float(r["score"]) for (q, _), r in new.items() if q == "programme-house"]
    if n_:
        n = statistics.median(n_)
        print(f"    old {o:.3f}  new {n:.3f}  ({', '.join(f'{x:.3f}' for x in sorted(n_))})")
        verdicts.append(("2 programme-house score", n >= o))

    print(f"\n(3) `too few stairs` on harbor-house and maple-court runs{tag}")
    def stairs(d):
        return sum(1 for (p, _), f in d.items() if p in ("harbor-house", "maple-court")
                   and any("too few stairs" in x for x in f))
    big_new = sum(1 for (p, _) in fl if p in ("harbor-house", "maple-court"))
    big_old = sum(1 for (p, _) in fl_old if p in ("harbor-house", "maple-court"))
    print(f"    old {stairs(fl_old)}/{big_old}  new {stairs(fl)}/{big_new}")
    verdicts.append(("3 too few stairs persists",
                     big_new and stairs(fl) / big_new >= stairs(fl_old) / big_old))

    print(f"\n(4) crinkliness the largest family{tag}")
    for name, d in ((a.against, fl_old), (a.objective, fl)):
        c = Counter(family(x) for f in d.values() for x in f)
        tot = sum(c.values()) or 1
        top = ", ".join(f"{k} {v} ({100 * v / tot:.0f}%)" for k, v in c.most_common(4))
        print(f"    {name:14s} {tot:4d} fails: {top}")
    c = Counter(family(x) for f in fl.values() for x in f)
    verdicts.append(("4 crinkliness largest", bool(c) and c.most_common(1)[0][0] == "crinkliness"))

    print(f"\n(5) run-hours within 10% of {a.against}'s, slightly lower{tag}")
    def hours(d, keys):
        return sum(float(d[k]["elapsed_s"]) for k in keys) / 3600
    keys = sorted(set(new) & set(old))
    if keys:
        ho, hn = hours(old, keys), hours(new, keys)
        print(f"    over the {len(keys)} runs in both: old {ho:.1f} h  new {hn:.1f} h  "
              f"({100 * (hn - ho) / ho:+.1f}%)")
        verdicts.append(("5 run-hours", abs(hn - ho) <= 0.1 * ho))

    print(f"\nverdicts{tag}:")
    for v, ok in verdicts:
        print(f"    {'HELD  ' if ok else 'MISSED'} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

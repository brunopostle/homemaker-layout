#!/usr/bin/env python3
"""Pair Phase 3's report cards by (programme, start k) across arms
(`homemaker-py-5fje.6`, DESIGN.md §39.219). Prints, per contrast, every
column's arm means, wins/losses and paired mean difference with its MDD,
over all twelve pairs, and per programme. A card is a vector: nothing here is
summed across columns.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/report_card.py \\
        experiments/results/phase3-q2/*--*.dom --tsv experiments/results/phase3-q2/cards.tsv
    python experiments/pair_phase3_q2.py experiments/results/phase3-q2/cards.tsv
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ab_report import paired_report  # noqa: E402

COLS = ["fails", "missing", "token", "shortfall_m2", "surplus_m2", "ratio_med",
        "ratio_min", "ratio_big5", "sliver", "sliver_cells", "long", "unlit", "deep", "adj_share",
        "no_door", "disconnected", "stair_storeys", "circ_pieces", "circ_share",
        "wall_per_m2", "cost"]
CONTRASTS = [("A0-fails", "A0-score"), ("P1-fails", "P1-score"),
             ("A0-fails", "P1-fails"), ("A0-score", "P1-score"),
             ("A0-fails", "P1-score"),
             ("A0-fails", "A0-tiers"), ("P1-fails", "P1-tiers"),
             ("P1-fails", "P1u-fails"), ("P1-score", "P1u-score"),
             ("P1-tiers", "P1u-tiers")]
NAME = re.compile(r"(?P<arm>[^/]+?)--(?P<prog>[a-z-]+)--(?P<k>\d)\.dom$")


def load(path):
    cards = {}
    fails = {}
    res = Path(path).parent / "results.tsv"
    if res.exists():
        for r in csv.DictReader(res.open(), delimiter="\t"):
            fails[(r["arm"], r["programme"], r["k"])] = float(r["fails"])
    for r in csv.DictReader(open(path), delimiter="\t"):
        m = NAME.search(r["design"])
        key = (m["arm"], m["prog"], m["k"])
        row = {c: float(v) for c, v in r.items()
               if c not in ("programme", "design") and v not in ("", "-", "nan")}
        row["disconnected"] = row["storeys"] - row["connected"]
        row["fails"] = fails.get(key, float("nan"))
        cards[key] = row
    return cards


def main(path):
    cards = load(path)
    progs = sorted({p for _, p, _ in cards})
    for a, b in CONTRASTS:
        keys = sorted((p, k) for (arm, p, k) in cards if arm == a and (b, p, k) in cards)
        if len(keys) < 2:
            continue
        print(f"\n## {a} -> {b}  ({len(keys)} pairs)")
        print(f"{'column':14s} {'mean '+a:>14s} {'mean '+b:>14s} {'b>a':>4s} {'b<a':>4s} "
              f"{'diff b-a':>10s} {'MDD':>9s}   per programme (mean b-a)")
        for c in COLS:
            xa = [cards[(a, p, k)].get(c, float("nan")) for p, k in keys]
            xb = [cards[(b, p, k)].get(c, float("nan")) for p, k in keys]
            if any(x != x for x in xa + xb):
                continue
            r = paired_report(xa, xb, a, b)
            per = "  ".join(
                f"{p[:6]} {sum(cards[(b, p, k)][c] - cards[(a, p, k)][c] for q, k in keys if q == p) / max(1, sum(1 for q, _ in keys if q == p)):+.3g}"
                for p in progs)
            flag = "" if r["degenerate"] or r["underpowered"] else " *"
            print(f"{c:14s} {r['mean_a']:14.4g} {r['mean_b']:14.4g} {r['losses_b']:4d} "
                  f"{r['wins_b']:4d} {-r['mean_diff']:+10.3g} {r['mdd']:9.3g}{flag:2s} {per}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "experiments/results/phase3-q2/cards.tsv")

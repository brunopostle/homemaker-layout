#!/usr/bin/env python3
"""Pair each Phase 3 design with its twin from a later re-run of the same arm,
start and rng seed (`homemaker-py-5fje.6`, DESIGN.md §39.226). Only the
objective differs between twins, so this asks what an objective change did,
arm by arm. Both card files should be built with TODAY's code; fails, hard and
soft are re-scored here with today's code too, and `fails_rec` is the count as
each run recorded it.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/report_card.py \\
        experiments/results/phase3-q2/{A0,P1}-{fails,score}--*.dom \\
        --tsv experiments/results/phase3-sliver/cards-phase3-twins.tsv
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/pair_phase3_twins.py \\
        experiments/results/phase3-sliver/cards-phase3-twins.tsv \\
        experiments/results/phase3-sliver/cards.tsv
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ab_report import paired_report  # noqa: E402


def _mod(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _rows(cards_path, results_dir, rec, q2):
    """Cards keyed (arm, programme, k), with fails/hard/soft re-scored today."""
    pp = _mod("pair_phase3_q2")
    cards = pp.load(cards_path)
    recorded = pp.load(Path(results_dir) / "cards.tsv") if rec else cards
    for (arm, prog, k), row in cards.items():
        row["fails_rec"] = recorded.get((arm, prog, k), {}).get("fails", float("nan"))
        n, hard, soft, _, _ = q2.score(Path(results_dir) / f"{arm}--{prog}--{k}.dom", prog, arm)
        row["fails"], row["hard"], row["soft"] = n, hard, soft
    return cards, pp.COLS


def main(old_cards, new_cards):
    q2 = _mod("run_phase3_q2")
    dir_of = lambda path: Path(re.sub(r"/[^/]+$", "", open(path).readlines()[1].split("\t")[1]))
    old, cols = _rows(old_cards, dir_of(old_cards), True, q2)
    new, _ = _rows(new_cards, dir_of(new_cards), False, q2)
    arms = sorted({a for a, _, _ in new})
    print("sliver rooms / sliver cells per arm")
    for a in arms:
        tot = lambda d, c: int(sum(r[c] for (x, _, _), r in d.items() if x == a))
        print(f"  {a:10s} old {tot(old, 'sliver')}/{tot(old, 'sliver_cells')}"
              f"   new {tot(new, 'sliver')}/{tot(new, 'sliver_cells')}")
    for a in arms:
        keys = sorted((p, k) for (x, p, k) in new if x == a and (x, p, k) in old)
        print(f"\n## {a}: old twin -> new run ({len(keys)} pairs)")
        print(f"  {'column':14s} {'old':>10s} {'new':>10s} {'new-old':>10s} {'MDD':>9s}")
        for c in ["fails_rec", "fails", "hard", "soft"] + [c for c in cols if c != "fails"]:
            xa = [old[(a, p, k)].get(c, float("nan")) for p, k in keys]
            xb = [new[(a, p, k)].get(c, float("nan")) for p, k in keys]
            if len(keys) < 2 or any(x != x for x in xa + xb):
                continue
            r = paired_report(xa, xb)
            flag = "" if r["degenerate"] or r["underpowered"] else " *"
            print(f"  {c:14s} {r['mean_a']:10.4g} {r['mean_b']:10.4g} "
                  f"{-r['mean_diff']:+10.3g} {r['mdd']:9.3g}{flag}")


if __name__ == "__main__":
    main(*sys.argv[1:3])

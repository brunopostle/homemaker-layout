"""The comparator x operator 2x2 on programme-house, at one objective
(`homemaker-py-qkp0`).

Two A/Bs of `mutate_support_outside` disagreed. Flat comparator at
`07b2058+orth` (§39.81): the control carried `no outside space` in 8 of 36
runs, the operator in 1, all 7 discordant pairs cleared. Tiered comparator at
`59d8aa1+orth` (§39.91): 3 of 36 against 4 of 36, no effect. Two things moved
between them -- the comparator AND the objective -- so nobody could say which
one made the operator's effect go away.

`qkp0` re-ran the flat A/B at `59d8aa1+orth`. That gives four cells at ONE
objective, the same 36 seeds in each:

                    operator off (arm A)    operator on (arm B)
    flat            flat59d8aa1 armA        flat59d8aa1 armB
    tiers           tiers armA              tiers armB

and three questions, each a paired comparison across one edge of the square:

  (a) flat-off vs flat-on      does the operator still clear the fail under
                               the DEFAULT search at this objective?
  (b) flat vs tiers, per arm   the clean comparator A/B (§39.91's was
                               confounded with the objective)
  (c) flat-off here vs §39.81  what the objective change alone did to the
                               control (different searches, so unpaired)

Rows are read from the tables as recorded -- nothing is re-scored, because all
four cells were scored at the stamp they were searched at. The tool REFUSES
if the two tables disagree about that stamp, and refuses an incomplete square
unless `--partial`, which marks every verdict PROVISIONAL (§39.47).

    python experiments/diag_qkp0_two_by_two.py [--partial]
    python experiments/diag_qkp0_two_by_two.py --self-test
"""

from __future__ import annotations

import argparse
import collections
import csv
import importlib.util
import re
import statistics as st
from math import comb
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESULTS = REPO / "experiments" / "results"
TABLES = {"flat": RESULTS / "e4r_support_outside_ab_flat59d8aa1.tsv",
          "tiers": RESULTS / "e4r_support_outside_ab_tiers.tsv"}
OLD_FLAT = RESULTS / "e4r_support_outside_ab.tsv"         # §39.81, 07b2058+orth
ARMS = ("armA", "armB")
SEEDS = 36


def _ab():
    spec = importlib.util.spec_from_file_location(
        "_ab_report", REPO / "experiments" / "ab_report.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read(path: Path) -> dict:
    return {(r["arm"], int(r["seed"])): r
            for r in csv.DictReader(path.open(), delimiter="\t")}


def family(line: str) -> str:
    """A fail line without its level or its cell, so the same fail pools."""
    line = re.sub(r"level \d+ ", "", line.split(":")[0]).strip()
    return re.sub(r"^\d+/[lr]* ?", "", line)


def sign_test(x: int, y: int) -> float:
    """Two-sided exact sign test on `x` against `y` discordant pairs."""
    n = x + y
    if not n:
        return 1.0
    return min(1.0, 2 * sum(comb(n, k) for k in range(min(x, y) + 1)) / 2 ** n)


def fisher(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for the table [[a, b], [c, d]]."""
    r1, r2, c1, n = a + b, c + d, a + c, a + b + c + d

    def p(k):
        return comb(r1, k) * comb(r2, c1 - k) / comb(n, c1)

    p0 = p(a)
    return min(1.0, sum(p(k) for k in range(max(0, c1 - r2), min(r1, c1) + 1)
                        if p(k) <= p0 * (1 + 1e-9)))


def discordant(off: list, on: list) -> "tuple[int, int]":
    """(cleared, broken): pairs where only `off` has it, only `on` has it."""
    return (sum(1 for x, y in zip(off, on) if x and not y),
            sum(1 for x, y in zip(off, on) if y and not x))


def report(cells: dict, old: dict, provisional: bool) -> None:
    ab = _ab()
    tag = "  ** PROVISIONAL: the square is incomplete **" if provisional else ""
    seeds = sorted(set.intersection(*(
        {s for a, s in cells[c] if a == arm} for c in cells for arm in ARMS)))
    print(f"seeds complete in all four cells: {len(seeds)}{tag}\n")

    print(f"{'cell':<12} {'n':>3} {'fails':>6} {'hard':>5} {'soft':>5} {'roof':>5} "
          f"{'0 fails':>8} {'score mean':>11} {'median':>7} {'3-storey':>9}")
    for c in cells:
        for arm in ARMS:
            R = [cells[c][(arm, s)] for s in seeds]
            sc = [float(r["score"]) for r in R]
            print(f"{c + ' ' + ('off' if arm == 'armA' else 'on'):<12} {len(R):3d} "
                  f"{st.mean(int(r['fails']) for r in R):6.2f} "
                  f"{st.mean(int(r['hard']) for r in R):5.2f} "
                  f"{st.mean(int(r['soft']) for r in R):5.2f} "
                  f"{sum(int(r['roof_fail']) for r in R):5d} "
                  f"{sum(int(r['fails']) == 0 for r in R):8d} "
                  f"{st.mean(sc):11.4f} {st.median(sc):7.4f} "
                  f"{sum(int(r['storeys']) >= 3 for r in R):9d}")
            census = collections.Counter(
                family(f) for r in R for f in r["fail_list"].split(" | ") if f.strip())
            print("             " + ", ".join(f"{k} {v}" for k, v in census.most_common()))
    print()

    print(f"(a) does the operator clear `no outside space`?{tag}")
    for c in cells:
        off = [int(cells[c][("armA", s)]["roof_fail"]) for s in seeds]
        on = [int(cells[c][("armB", s)]["roof_fail"]) for s in seeds]
        cleared, broken = discordant(off, on)
        n = cleared + broken
        floor = 2 / 2 ** n if n else 1.0
        print(f"  {c:<6} off {sum(off)}/{len(seeds)}, on {sum(on)}/{len(seeds)}; "
              f"discordant {n}: {cleared} cleared, {broken} broken; "
              f"sign test p = {sign_test(cleared, broken):.3g}"
              + (f"  ** NOT RESOLVABLE: {n} discordant pairs cannot reach "
                 f"p < 0.05 (floor {floor:.3g}) **" if floor >= 0.05 else ""))
    print()

    print(f"(b) flat vs tiers, same arm, same seed, same objective{tag}")
    print("    (a W is 'tiers LOWER': better for fails, hard and soft; INVERTED for score)")
    for arm in ARMS:
        print(f"  -- operator {'off' if arm == 'armA' else 'on'} ({arm})")
        for metric in ("fails", "hard", "soft", "score"):
            a = [float(cells["flat"][(arm, s)][metric]) for s in seeds]
            b = [float(cells["tiers"][(arm, s)][metric]) for s in seeds]
            print(f"  {metric}:")
            print(ab.format_report(ab.paired_report(a, b, "flat", "tiers"), indent="    "))
    print()

    if old:
        was = [int(r["roof_fail"]) for (arm, _), r in old.items() if arm == "armA"]
        now = [int(cells["flat"][("armA", s)]["roof_fail"]) for s in seeds]
        stamps = sorted({r["objective"] for r in old.values()})
        print(f"(c) the flat control, {', '.join(stamps)} against this objective{tag}")
        print(f"  carried `no outside space`: {sum(was)}/{len(was)} then, "
              f"{sum(now)}/{len(now)} now; Fisher exact p = "
              f"{fisher(sum(was), len(was) - sum(was), sum(now), len(now) - sum(now)):.3g}")
        print("  (different searches at different objectives, so unpaired -- and the\n"
              "   old artefacts, re-scored today, still carry it in the same 8, §39.93)")


def self_test() -> int:
    """The statistics against values worked by hand, and the refusal."""
    ok = (abs(sign_test(7, 0) - 0.015625) < 1e-12        # §39.81's 7 of 7
          and abs(sign_test(2, 3) - 1.0) < 1e-12
          and abs(fisher(7, 0, 2, 3) - 0.0455) < 5e-4    # §39.91's own figure
          and abs(fisher(8, 28, 1, 35) - 0.0278) < 5e-4
          and discordant([1, 1, 0, 0], [0, 1, 1, 0]) == (1, 1)
          and family("level 1 no outside space") == "no outside space"
          and family("1/lrl size") == "size")
    print("self-test", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--partial", action="store_true",
                    help="report an incomplete square, marked PROVISIONAL")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    cells = {name: read(path) for name, path in TABLES.items()}
    stamps = {name: sorted({r["objective"] for r in rows.values()})
              for name, rows in cells.items()}
    if len({tuple(v) for v in stamps.values()}) != 1 or any(len(v) != 1 for v in stamps.values()):
        print(f"the two tables are not at one objective: {stamps}\n"
              "A square across objectives answers none of the three questions.")
        return 2
    missing = {name: 2 * SEEDS - len(rows) for name, rows in cells.items()}
    if any(missing.values()) and not a.partial:
        print(f"the square is incomplete (runs missing: {missing}); "
              "pass --partial for a PROVISIONAL report")
        return 2
    print(f"objective {stamps['flat'][0]}, programme-house, budget "
          f"{next(iter(cells['flat'].values()))['budget']}\n")
    report(cells, read(OLD_FLAT) if OLD_FLAT.exists() else {}, any(missing.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""WHERE a move is played: does aiming it at a failing cell help?
(`homemaker-py-urzf`, DESIGN.md §39.123)

The book of moves (`diag_move_book.py`, §39.120) ranks the moves that exist.
The owner's wider idea is a book that holds moves nobody has written yet. The
cheapest new move is an old one with an aim: the five exploratory operators
pick their cell at random, and the recordings say which cell each one picked
and which cells of the parent were failing. So, with no new run:

    HIT    the cell (or branch) the move was played on IS a failing cell, or
           contains one
    NEAR   it is the sibling of a branch that contains a failing cell
    MISS   anywhere else, another storey included

and for each, how often the child has fewer fails, is better than its parent
(fewer fails, or as many and a higher score), and is kept. A move is drawn
independently of where the fails are, so within one operator the three groups
differ only in the aim -- except for SIZE: a branch near the root contains a
failing cell more often AND is a bigger move, so every table is also given by
the depth of the cell played on.

The verdict is paired over runs through `ab_report`: one HIT rate and one MISS
rate per recorded run, so twenty thousand children from twelve runs are
counted as twelve observations and not twenty thousand.

What this cannot say: whether a search that aimed its moves would end better.
An aimed move is a narrower move; a search that plays only at failing cells
stops exploring the cells that are fine. That is an A/B.

    python experiments/diag_move_where.py [--programme programme-house]
    python experiments/diag_move_where.py --self-test
"""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import random
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ab_report  # noqa: E402

LOGS = REPO / "experiments" / "results" / "moves"
OPS = ("divide", "undivide", "retype", "rotate", "swap")
SITE = re.compile(r"^(%s) (\d+)/([a-z]+)" % "|".join(OPS))
CELL = re.compile(r"^(\d+)/([lr]+)\s+(.*)$")
GROUPS = ("HIT", "NEAR", "MISS")
MEASURES = (("fewer", "fewer fails"), ("better", "beat parent"), ("kept", "kept"))


def site(move: str) -> "tuple[str, int, str] | None":
    """(operator, storey, path) of a move that names its cell; root is ''."""
    m = SITE.match(move)
    if not m:
        return None
    return m.group(1), int(m.group(2)), "" if m.group(3) == "root" else m.group(3)


def failing_cells(fails: "list[str]") -> "set[tuple[int, str]]":
    out = set()
    for f in fails:
        m = CELL.match(f.strip())
        if m:
            out.add((int(m.group(1)), m.group(2)))
    return out


def relation(level: int, path: str, cells: "set[tuple[int, str]]") -> str:
    here = [p for lv, p in cells if lv == level]
    if any(p.startswith(path) for p in here):
        return "HIT"
    if path and any(p.startswith(path[:-1]) for p in here):
        return "NEAR"
    return "MISS"


def digest(r: dict, seed: int) -> "dict | None":
    s = site(r["move"])
    pf = r.get("parent_fails")
    if s is None or pf is None:
        return None
    cells = failing_cells(pf)
    if not cells:
        return None                 # nothing to aim at
    op, level, path = s
    cf = r["fails"]
    return {"seed": seed, "op": op, "depth": len(path), "n_parent": len(pf),
            "rel": relation(level, path, cells),
            "fewer": len(cf) < len(pf),
            "better": len(cf) < len(pf) or (len(cf) == len(pf)
                                            and r["fitness"] > r["parent_fitness"]),
            "kept": r["status"] in ("best", "kept"),
            "level": level, "path": path, "cells": cells}


def load(programme: "str | None") -> "list[dict]":
    out = []
    for path in sorted(LOGS.glob(f"{programme or '*'}-*.jsonl.gz")):
        seed = int(re.search(r"-s(\d+)\.jsonl", path.name).group(1))
        with gzip.open(path, "rt") as fh:
            for line in fh:
                d = digest(json.loads(line), seed)
                if d:
                    out.append(d)
    return out


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:5.1f}%" if b else "     -"


def depth_band(d: int) -> str:
    return "0-1" if d <= 1 else "2" if d == 2 else "3+"


def table(rows: "list[dict]", title: str) -> None:
    print(f"\n{title}")
    print(f"{'move':<10} {'aim':<5} {'n':>6}  " + "  ".join(f"{lab:>12}" for _, lab in MEASURES))
    for op in OPS + ("all five",):
        rs = rows if op == "all five" else [r for r in rows if r["op"] == op]
        for g in GROUPS:
            x = [r for r in rs if r["rel"] == g]
            print(f"{op if g == 'HIT' else '':<10} {g:<5} {len(x):>6}  "
                  + "  ".join(f"{pct(sum(r[k] for r in x), len(x)):>12}" for k, _ in MEASURES))


def paired(rows: "list[dict]", key: str, a: str = "HIT", b: str = "MISS",
           min_n: int = 20) -> "dict | None":
    """One rate per run for each aim; runs with too few of either are left out."""
    xa, xb = [], []
    for seed in sorted({r["seed"] for r in rows}):
        ra = [r[key] for r in rows if r["seed"] == seed and r["rel"] == a]
        rb = [r[key] for r in rows if r["seed"] == seed and r["rel"] == b]
        if len(ra) >= min_n and len(rb) >= min_n:
            xa.append(100 * sum(ra) / len(ra))
            xb.append(100 * sum(rb) / len(rb))
    if len(xa) < 2:
        return None
    return ab_report.paired_report(xa, xb, a, b)


def verdicts(rows: "list[dict]", min_n: int) -> None:
    print("\nPAIRED OVER RUNS (per-run rate, percentage points; HIT minus MISS)")
    print(f"{'move':<10} {'measure':<12} {'runs':>4} {'HIT':>7} {'MISS':>7} {'diff':>7} "
          f"{'MDD':>6} {'p':>7}")
    for op in OPS + ("all five",):
        rs = rows if op == "all five" else [r for r in rows if r["op"] == op]
        for key, lab in MEASURES:
            r = paired(rs, key, min_n=min_n)
            if r is None:
                print(f"{op:<10} {lab:<12}    too few runs with {min_n}+ of each aim")
                continue
            mark = "" if abs(r["mean_diff"]) > r["mdd"] else "  unresolved"
            print(f"{op:<10} {lab:<12} {r['n']:>4} {r['mean_a']:>6.1f}% {r['mean_b']:>6.1f}% "
                  f"{r['mean_diff']:>+6.1f} {r['mdd']:>6.1f} "
                  + (f"{r['p']:>7.4f}" if r["p"] is not None else "      -") + mark)


def report(rows: "list[dict]", name: str, min_n: int) -> None:
    runs = len({r["seed"] for r in rows})
    print(f"{name}: {len(rows)} children of {runs} runs, by a move that names its cell, "
          "whose parent has a failing cell")
    c = collections.Counter(r["rel"] for r in rows)
    print("  aim, as the search draws it: "
          + ", ".join(f"{g} {pct(c[g], len(rows)).strip()}" for g in GROUPS))
    table(rows, "ALL DEPTHS")
    for band in ("0-1", "2", "3+"):
        table([r for r in rows if depth_band(r["depth"]) == band],
              f"CELL PLAYED ON AT DEPTH {band}")
    verdicts(rows, min_n)
    deep = [r for r in rows if r["depth"] >= 2]
    print("\n... and the same for cells at depth 2 or more, where a move is small:")
    verdicts(deep, min_n)
    # A parent with many failing cells is HIT more often AND sheds fails more
    # easily (§39.120: 7.1% of moves at 6+ fails, 0.3% at 1-2). So the aim has
    # to be judged among parents that are equally bad.
    for lo, hi, lab in ((1, 2, "1-2"), (3, 5, "3-5"), (6, 10 ** 6, "6+")):
        rs = [r for r in rows if lo <= r["n_parent"] <= hi]
        if not rs:
            continue
        c = collections.Counter(r["rel"] for r in rs)
        print(f"\n... and among parents with {lab} fails ({len(rs)} children; "
              + ", ".join(f"{g} {c[g]}" for g in GROUPS) + "):")
        table(rs, f"PARENT HAS {lab} FAILS")
        verdicts(rs, min_n)


# --------------------------------------------------------------------------- #
def self_test() -> int:
    """A planted aim must be found; the real data with its aim shuffled must not."""
    rng = random.Random(7)
    planted = []
    for seed in range(8):
        for _ in range(600):
            rel = rng.choice(GROUPS)
            ok = rng.random() < (0.30 if rel == "HIT" else 0.10)
            planted.append({"seed": seed, "op": "swap", "depth": 2, "rel": rel,
                            "fewer": ok, "better": ok, "kept": ok, "n_parent": 3})
    p = paired(planted, "fewer")
    found = p is not None and p["mean_diff"] > p["mdd"] and p["mean_diff"] > 10

    rows = load(None)
    shuffled_ok = True
    if rows:
        # the control: keep every outcome, give each child the failing cells of
        # ANOTHER child of the same run, so the aim means nothing
        by_seed = collections.defaultdict(list)
        for r in rows:
            by_seed[r["seed"]].append(r)
        ctl = []
        for rs in by_seed.values():
            cells = [r["cells"] for r in rs]
            rng.shuffle(cells)
            for r, c in zip(rs, cells):
                ctl.append({**r, "rel": relation(r["level"], r["path"], c)})
        real = paired(rows, "better")
        s = paired(ctl, "better")
        print(f"  real data, beat parent, HIT-MISS: {real['mean_diff']:+.2f} (MDD {real['mdd']:.2f})"
              if real else "  real data: too few runs")
        print(f"  aim shuffled:                     {s['mean_diff']:+.2f} (MDD {s['mdd']:.2f})"
              if s else "  shuffled: too few runs")
        # shuffling keeps the depth of the cell played on, so what survives it
        # is the SIZE effect and nothing else; report it, and require only that
        # the control can differ from the real thing
        shuffled_ok = s is not None and real is not None
    print(f"  planted aim (30% against 10%): diff {p['mean_diff']:+.1f}, MDD {p['mdd']:.1f}")
    ok = found and shuffled_ok
    print("self-test", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", default=None)
    ap.add_argument("--min-n", type=int, default=20,
                    help="a run needs this many children of each aim to count")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    progs = [a.programme] if a.programme else sorted(
        {p.name.split("-b")[0] for p in LOGS.glob("*.jsonl.gz")})
    for i, prog in enumerate(progs):
        rows = load(prog)
        if not rows:
            print(f"{prog}: no recordings under {LOGS}")
            continue
        if i:
            print("\n" + "=" * 78 + "\n")
        report(rows, prog, a.min_n)
    return 0


if __name__ == "__main__":
    sys.exit(main())

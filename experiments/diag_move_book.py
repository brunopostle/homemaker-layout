"""A book of moves: which operator succeeds on which failure pattern?
(`homemaker-py-urzf`, DESIGN.md §39.119)

The owner's idea: operators are like chess moves, and by tracking which tend
to succeed we can choose them by the state of the design and its particular
failures. This reads the move logs `experiments/record_moves.py` collects --
one record per child of a real search -- and asks, in order:

1. THE MOVES: how often each is drawn, declines, removes a fail, is kept.
2. BY HOW BAD THE PARENT IS: does the useful set change as a design improves?
3. THE BOOK: for each family of fail a parent carries, which moves reduce
   THAT family, how often, and against what base rate.
4. WASTED DRAWS: how many draws go to a move that declines, and what a
   declined draw is worth (the child is its parent, re-tuned).
5. WHAT A BOOK WOULD BUY: choose, for each state, the move the book ranks
   first, and estimate its rate of removing a fail -- on runs the book was
   NOT built from (odd seeds judge a book built on even seeds). The search
   draws moves independently of the state, so within a state the logged rate
   of a move is an unbiased estimate of what choosing it would get.

A FAMILY is a fail line with its storey, cell and room code removed: `size`,
`crinkliness`, `no outside space`, `adjacency`, `too few stairs`... A STATE,
for section 5, is how bad the parent is and which of its families is the
first on a fixed list of structural ones -- coarse on purpose, because exact
patterns hardly ever repeat.

What this cannot say: whether a search that CHOSE moves this way would end
better. Credit here goes to the move that finishes; a move that sets up a
later repair earns nothing, and a policy built on this table would stop
playing it. That is an A/B, with an exploration floor in the B arm.

    python experiments/diag_move_book.py [--programme programme-house] [--min-n 30]
    python experiments/diag_move_book.py --self-test
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
LOGS = REPO / "experiments" / "results" / "moves"
# structural families first: the one a state is named after
ORDER = ("missing room", "too few stairs", "staircase volume", "not connected",
         "inaccessible usable space", "no outside space", "wrong level", "adjacency",
         "access", "covered outside above ground", "unsupported covered outside",
         "excess internal area", "crinkliness", "size", "width", "proportion")


def family(line: str) -> str:
    """A fail line without its storey, its cell or its room code."""
    s = line.strip()
    if s.startswith("missing"):
        return "missing room"
    s = re.sub(r"^\d+/[lr]*\s+", "", s)
    s = re.sub(r"^level \d+\s+", "", s)
    s = re.sub(r"^\d+\s+", "", s)
    if "not adjacent to" in s:
        return "adjacency"
    if "wrong level" in s:
        return "wrong level"
    return re.sub(r"\s*\(\d+, min \d+\)", "", s)


def regime(n: int) -> str:
    return "6+" if n >= 6 else "3-5" if n >= 3 else "1-2" if n >= 1 else "0"


def state(parent_fails: "list[str]") -> str:
    fams = {family(f) for f in parent_fails}
    lead = next((f for f in ORDER if f in fams), "none")
    return f"{regime(len(parent_fails))} fails, {lead}"


def load(programme: "str | None") -> "list[dict]":
    out = []
    for path in sorted(LOGS.glob("*.jsonl.gz")):
        if programme and not path.name.startswith(programme + "-b"):
            continue
        seed = int(re.search(r"-s(\d+)\.jsonl", path.name).group(1))
        with gzip.open(path, "rt") as fh:
            for line in fh:
                r = json.loads(line)
                if r.get("parent_fails") is None:
                    continue                    # seeds and constructed designs
                out.append(digest(r, seed))
    return out


def digest(r: dict, seed: int) -> dict:
    pf, cf = r["parent_fails"], r["fails"]
    pc, cc = (collections.Counter(family(f) for f in x) for x in (pf, cf))
    return {"seed": seed, "op": r["move"].split()[0], "declined": "noop" in r["move"],
            "status": r["status"], "used": r["used"],
            "n_parent": len(pf), "d": len(cf) - len(pf),
            "families": pc, "reduced": {f for f in pc if cc[f] < pc[f]},
            "state": state(pf),
            "better": len(cf) < len(pf) or (len(cf) == len(pf)
                                            and r["fitness"] > r["parent_fitness"])}


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:5.1f}%" if b else "    -"


# --------------------------------------------------------------------------- #
def moves(rows) -> None:
    print(f"\n1. THE MOVES ({len(rows)} children with a parent)\n")
    print(f"{'move':<20} {'drawn':>6} {'share':>6} {'declined':>9} | of those APPLIED: "
          f"{'fewer fails':>11} {'more fails':>11} {'beat parent':>12} {'kept':>7}")
    by = collections.defaultdict(list)
    for r in rows:
        by[r["op"]].append(r)
    for op, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        ap = [r for r in rs if not r["declined"]]
        print(f"{op:<20} {len(rs):6d} {pct(len(rs), len(rows))} {pct(len(rs) - len(ap), len(rs)):>9} | "
              f"{'':18} {pct(sum(r['d'] < 0 for r in ap), len(ap)):>11} "
              f"{pct(sum(r['d'] > 0 for r in ap), len(ap)):>11} "
              f"{pct(sum(r['better'] for r in ap), len(ap)):>12} "
              f"{pct(sum(r['status'] in ('kept', 'best') for r in ap), len(ap)):>7}")


def by_regime(rows, min_n: int) -> None:
    print("\n2. BY HOW BAD THE PARENT IS: share of APPLIED moves that removed a fail\n")
    regimes = ("6+", "3-5", "1-2")
    ops = sorted({r["op"] for r in rows})
    print(f"{'move':<20}" + "".join(f"{x + ' fails':>18}" for x in regimes))
    cell = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        if not r["declined"]:
            c = cell[r["op"], regime(r["n_parent"])]
            c[0] += r["d"] < 0
            c[1] += 1
    base = {g: [sum(cell[o, g][0] for o in ops), sum(cell[o, g][1] for o in ops)] for g in regimes}
    print(f"{'(any applied move)':<20}" + "".join(
        f"{pct(*base[g]):>10} n={base[g][1]:<5}" for g in regimes))
    for op in sorted(ops, key=lambda o: -sum(cell[o, g][0] for g in regimes)):
        if all(cell[op, g][1] < min_n for g in regimes):
            continue
        print(f"{op:<20}" + "".join(
            (f"{pct(*cell[op, g]):>10} n={cell[op, g][1]:<5}" if cell[op, g][1] >= min_n
             else f"{'':>10} n={cell[op, g][1]:<5}") for g in regimes))


def book(rows, min_n: int) -> None:
    print(f"\n3. THE BOOK: a parent carries this fail; which APPLIED move reduces it? "
          f"(moves tried at least {min_n} times on it)\n")
    fams = collections.Counter(f for r in rows for f in r["families"])
    for fam in sorted(fams, key=lambda f: (ORDER.index(f) if f in ORDER else 99)):
        on = [r for r in rows if fam in r["families"] and not r["declined"]]
        if len(on) < min_n:
            continue
        base = sum(fam in r["reduced"] for r in on)
        by = collections.defaultdict(list)
        for r in on:
            by[r["op"]].append(r)
        ranked = sorted(((sum(fam in r["reduced"] for r in rs) / len(rs), op, rs)
                         for op, rs in by.items() if len(rs) >= min_n), reverse=True)
        print(f"{fam}: carried by {fams[fam]} parents; any applied move reduces it "
              f"{pct(base, len(on)).strip()} of the time")
        for rate, op, rs in ranked[:4]:
            hit = sum(fam in r["reduced"] for r in rs)
            net = sum(r["d"] < 0 for r in rs)
            print(f"    {op:<20} {100 * rate:5.1f}%  ({hit} of {len(rs)})   "
                  f"and the child has fewer fails in all: {pct(net, len(rs)).strip()}")
        if ranked and ranked[-1][0] == 0 and len(ranked) > 4:
            never = [op for rate, op, rs in ranked if rate == 0]
            print(f"    never, in {min_n}+ tries each: {', '.join(sorted(never))}")


def wasted(rows) -> None:
    print("\n4. WASTED DRAWS: a move that declines returns its parent, which is then "
          "tuned for the full budget\n")
    print(f"{'parent has':<12} {'draws':>7} {'declined':>9} | "
          f"{'declined: beat parent':>22} {'applied: beat parent':>21} {'applied: fewer fails':>21}")
    for g in ("6+", "3-5", "1-2", "0", "all"):
        rs = [r for r in rows if g == "all" or regime(r["n_parent"]) == g]
        de = [r for r in rs if r["declined"]]
        ap = [r for r in rs if not r["declined"]]
        print(f"{g + ' fails':<12} {len(rs):7d} {pct(len(de), len(rs)):>9} | "
              f"{pct(sum(r['better'] for r in de), len(de)):>22} "
              f"{pct(sum(r['better'] for r in ap), len(ap)):>21} "
              f"{pct(sum(r['d'] < 0 for r in ap), len(ap)):>21}")
    evals = sum(r["used"] for r in rows)
    print(f"\nevaluations spent on declined draws: {pct(sum(r['used'] for r in rows if r['declined']), evals).strip()} "
          f"of {evals}")


def policy(rows, min_n: int) -> "tuple[float, float, float] | None":
    """Build the book on even seeds, judge it on odd ones. Returns
    ``(rate as drawn, rate with the book's first choice, share of test draws
    in a state the book has an opinion on)``."""
    train = [r for r in rows if r["seed"] % 2 == 0]
    test = [r for r in rows if r["seed"] % 2 == 1]
    if not train or not test:
        return None

    def table(rs):
        t = collections.defaultdict(lambda: [0, 0])
        for r in rs:
            if not r["declined"]:
                c = t[r["state"], r["op"]]
                c[0] += r["d"] < 0
                c[1] += 1
        return t

    tr, te = table(train), table(test)
    choice = {}
    for s in {k[0] for k in tr}:
        cands = [(tr[s, op][0] / tr[s, op][1], op) for (s2, op) in tr
                 if s2 == s and tr[s, op][1] >= min_n]
        if cands:
            choice[s] = max(cands)[1]
    drawn = [r for r in test]                       # as the search draws: declines included
    as_drawn = sum(r["d"] < 0 for r in drawn) / len(drawn)
    got = n = covered = 0.0
    for r in drawn:                                 # each test draw stands for its state
        s = r["state"]
        op = choice.get(s)
        if op is not None and te[s, op][1] > 0:
            got += te[s, op][0] / te[s, op][1]
            covered += 1
        else:
            got += r["d"] < 0                       # no opinion: what the draw got
        n += 1
    return as_drawn, got / n, covered / n, choice


def show_policy(rows, min_n: int) -> None:
    print("\n5. WHAT A BOOK WOULD BUY: its first choice per state, judged on runs it "
          "was not built from\n")
    res = policy(rows, min_n)
    if res is None:
        print("   needs logs from both even and odd seeds")
        return
    as_drawn, with_book, covered, choice = res
    print(f"   share of draws that remove a fail, as the search draws them: {100 * as_drawn:.2f}%")
    print(f"   choosing the book's first move for the state:              {100 * with_book:.2f}%  "
          f"({with_book / as_drawn:.1f}x)" if as_drawn else "")
    print(f"   test draws in a state the book has an opinion on:          {100 * covered:.0f}%")
    print("\n   the book's first choice, by state:")
    for s in sorted(choice):
        print(f"     {s:<42} {choice[s]}")
    print("\n   Greedy and optimistic: one move per state for ever is not a search. It "
          "bounds what\n   weighting by state could add; the A/B is what says whether "
          "a search keeps it.")


def self_test() -> int:
    """A made-up log in which ONE move clears ONE family half the time and
    everything else never does. The book must put that move first for that
    family, the policy must choose it, and a shuffled copy -- moves reassigned
    at random -- must show no such thing."""
    rng = random.Random(1)
    ops = ["alpha", "beta", "gamma", "delta"]

    def rec(seed, op):
        pf = ["level 1 no outside space", "0/lr size", "1/rl size"]
        cf = list(pf)
        if op == "beta" and rng.random() < 0.5:
            cf.remove("level 1 no outside space")
        elif rng.random() < 0.03:
            cf.remove("0/lr size")
        return digest({"move": f"{op} x", "status": "kept", "used": 80, "fitness": 1.0,
                       "parent_fitness": 1.0, "fails": cf, "parent_fails": pf}, seed)

    rows = [rec(seed, rng.choice(ops)) for seed in range(8) for _ in range(400)]
    as_drawn, with_book, _, choice = policy(rows, 30)
    shuffled = [dict(r, op=rng.choice(ops)) for r in rows]
    s_drawn, s_book, _, _ = policy(shuffled, 30)
    ok = (choice["3-5 fails, no outside space"] == "beta" and with_book > 2.5 * as_drawn
          and s_book < 1.5 * s_drawn
          and family("2/lrl crinkliness") == "crinkliness"
          and family("(t1) not adjacent to b1") == "adjacency"
          and family("too few stairs (0, min 1)") == "too few stairs"
          and family("missing required space: r#1") == "missing room")
    print("self-test", "PASSED" if ok else "FAILED",
          f"-- planted move found ({100 * as_drawn:.1f}% -> {100 * with_book:.1f}%); "
          f"shuffled: {100 * s_drawn:.1f}% -> {100 * s_book:.1f}%")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme")
    ap.add_argument("--min-n", type=int, default=30,
                    help="tries a move needs in a cell before its rate is shown or used")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    rows = load(a.programme)
    if not rows:
        print(f"no move logs under {LOGS.relative_to(REPO)}; run experiments/record_moves.py")
        return 1
    seeds = sorted({r["seed"] for r in rows})
    print(f"{a.programme or 'all programmes'}: {len(seeds)} recorded runs, seeds {seeds[0]}-{seeds[-1]}")
    moves(rows)
    by_regime(rows, a.min_n)
    book(rows, a.min_n)
    wasted(rows)
    show_policy(rows, a.min_n)
    return 0


if __name__ == "__main__":
    sys.exit(main())

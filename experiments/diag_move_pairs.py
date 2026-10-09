"""Two moves with no judging between: which pairs are worth storing as one?
(`homemaker-py-urzf`, DESIGN.md §39.124)

The owner's idea for the book of moves: mine multi-step mutations that led to
success and compile them into stored moves. Mining the search's own lineages
finds only sequences in which every step survived admission -- which the
search can already make. A compound worth storing is one whose FIRST step
makes the design worse, so that the search rejects it and never plays the
second. Those have to be tried on purpose (§39.75's `--from-broken` lesson).

So: on stuck designs -- finished 500k runs that still carry a fail -- play
move A, then move B on A's child with no tuning and no judging between, then
tune the result exactly as the search tunes one child (`driver._evaluate`, 80
evaluations). A pair costs what one child costs. Beside it, each move alone,
and `retune` (the parent given 80 more evaluations, which is what a declined
draw is, §39.120).

A pair is interesting if it leaves FEWER FAILS THAN THE PARENT more often than
either of its moves alone. With ~200 ordered pairs something will look good by
chance, so the census is in two halves that share no parent:

    --screen     even-numbered parents: every ordered pair, a few draws each
    --confirm    odd-numbered parents: the screen's best pairs and their
                 singles, many draws each
    --report     the screen's ranking, and the confirm half's verdict

What it cannot say: whether a search holding the compound as a move ends
better. That is an A/B.

    PYTHONPATH=src HOMEMAKER_ORTHOGONAL_DIVISION=1 \\
        python experiments/diag_move_pairs.py --screen  [--jobs 2]
        python experiments/diag_move_pairs.py --confirm [--jobs 2]
        python experiments/diag_move_pairs.py --report
        python experiments/diag_move_pairs.py --self-test
"""

from __future__ import annotations

import argparse
import collections
import copy
import csv
import hashlib
import importlib.util
import json
import math
import multiprocessing
import os
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MAIN = Path(os.environ.get("HOMEMAKER_MAIN", REPO.parent / "homemaker-layout"))
OUT = REPO / "experiments" / "results" / "move_pairs"
# every move a default search plays, less crossover (two parents) and
# core_undivide (declines every time, §39.120)
OPS = ("divide", "undivide", "retype", "swap", "rotate", "core_divide", "level_fix",
       "level_compound_fix", "place_missing", "level_retype", "level_add",
       "level_delete", "support_outside", "repair_shaft")
# the three `operators.mutate` hands the programme to, and no others
REQS_OPS = ("level_fix", "level_compound_fix", "place_missing")
TRIES = 6          # a move that declines is drawn again, this many times


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "experiments" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parents(programme: str, table: str) -> "list[dict]":
    """Finished runs that still carry a fail: the designs a search is stuck on."""
    out = []
    with open(MAIN / "experiments" / "results" / f"{table}.tsv") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            if r["programme"] == programme and int(r["fails"]) > 0:
                out.append({"dom": r["dom"], "seed": int(r["seed"]), "arm": r["arm"],
                            "fails": int(r["fails"]), "fail_list": r["fail_list"]})
    return sorted(out, key=lambda r: r["dom"])


def _rng(*key):
    import numpy as np
    return np.random.default_rng(int.from_bytes(
        hashlib.blake2b("/".join(map(str, key)).encode(), digest_size=8).digest(), "little"))


_CTX: dict = {}


def _ctx(programme: str) -> dict:
    if programme not in _CTX:
        from homemaker_layout import driver, geometry, programme as programme_mod
        geometry.ORTHOGONAL_DIVISION = True
        shaft = _load("diag_8b2u_fixed_shaft")
        prog = MAIN / "examples" / programme
        reqs = programme_mod.load_programme_dir(str(prog))
        ov = driver._overrides_for(shaft.SEARCH.get("leaf_sharing", False), False, None, False,
                                   shaft.SEARCH.get("collapse_insearch", True), False)
        _CTX[programme] = {"prog": prog, "reqs": reqs, "types": sorted(reqs) + ["C", "O"],
                           "search": shaft.SEARCH,
                           "fit": driver._fitness_for(str(prog), **{
                               k: v for k, v in shaft.SEARCH.items()
                               if k in ("leaf_sharing", "collapse_insearch")}),
                           "overrides": ov}
    return _CTX[programme]


def play(name: str, root, rng, c: dict):
    """One move, drawn again if it declines. Returns the child, or None."""
    from homemaker_layout import operators
    for _ in range(TRIES):
        kw = {"reqs": c["reqs"]} if name in REQS_OPS else {}
        child, desc = operators.MUTATIONS[name](root, rng, c["types"], **kw)
        if "noop" not in desc:
            return child
    return None


def one(task: dict) -> dict:
    """Play a task's moves on its parent and tune the result as the search would."""
    from homemaker_layout import dom, driver, geometry, innerloop
    t0 = time.process_time()
    c = _ctx(task["programme"])
    parent = dom.load(str(MAIN / "experiments" / "results" / task["dir"] / task["dom"]))
    dom.link(parent)
    geometry.clear_cache()
    ratios = innerloop.ratio_map(parent)
    rng = _rng(task["dom"], task["a"], task["b"], task["draw"])
    row = dict(task)
    child, mid = parent, None
    for step, name in (("a", task["a"]), ("b", task["b"])):
        if name in (None, "retune"):
            continue
        child = play(name, child, rng, c)
        if child is None:
            row.update(status=f"{step} declined", fails=None, fitness=None,
                       cpu=time.process_time() - t0)
            return row
        dom.link(child)
        geometry.clear_cache()
        if step == "a" and task["b"]:
            # how deep the valley is: the first move's child as it stands,
            # one score and no tuning
            mid = len(c["fit"].score_with_fails(copy.deepcopy(child))[1])
    dom.link(child)
    geometry.clear_cache()
    x0 = innerloop.warm_x0(child, {**innerloop.ratio_map(child), **ratios})
    root = copy.deepcopy(child)
    dom.link(root)
    geometry.clear_cache()
    ind, _ = driver._evaluate(root, str(c["prog"]), x0, 80, {}, "pairs", **c["search"])
    row.update(status="ok", fails=ind.n_fails, fitness=ind.fitness, mid=mid,
               cpu=time.process_time() - t0)
    return row


def tasks(half: str, a) -> "list[dict]":
    ps = [p for i, p in enumerate(parents(a.programme, a.table))
          if i % 2 == (0 if half == "screen" else 1)]
    out = []

    def add(p, x, y, n):
        for d in range(n):
            out.append({"half": half, "programme": a.programme, "dir": a.dir, "dom": p["dom"],
                        "parent_fails": p["fails"], "a": x, "b": y, "draw": d})

    if half == "screen":
        for p in ps:
            add(p, "retune", None, a.single_draws)
            for x in OPS:
                add(p, x, None, a.single_draws)
                for y in OPS:
                    add(p, x, y, a.pair_draws)
    else:
        best = [k for k, _ in ranking(load("screen", a.programme))[: a.top]]
        singles = {x for pair in best for x in pair}
        for p in ps:
            add(p, "retune", None, a.confirm_draws)
            for x in sorted(singles):
                add(p, x, None, a.confirm_draws)
            for x, y in best:
                add(p, x, y, a.confirm_draws)
    return out


def _key(r) -> tuple:
    return r["dom"], r["a"], r["b"], r["draw"]


def path_of(half: str, programme: str) -> Path:
    return OUT / f"{programme}-{half}.jsonl"


def load(half: str, programme: str) -> "list[dict]":
    p = path_of(half, programme)
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()] \
        if p.exists() else []


def run(half: str, a) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    todo = tasks(half, a)
    done = {_key(r) for r in load(half, a.programme)}
    todo = [t for t in todo if _key(t) not in done]
    print(f"{half}: {len(done)} done, {len(todo)} to do, {a.jobs} job(s)", flush=True)
    if not todo:
        return 0
    random.Random(1).shuffle(todo)       # an interrupted run is still a fair sample
    t0, n = time.time(), 0
    with open(path_of(half, a.programme), "a") as fh, \
            multiprocessing.Pool(a.jobs) as pool:
        for row in pool.imap_unordered(one, todo, chunksize=4):
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            n += 1
            if n % 200 == 0:
                rate = (time.time() - t0) / n
                print(f"  {n}/{len(todo)}  {rate:.1f}s each, "
                      f"{rate * (len(todo) - n) / 3600:.1f} h to go", flush=True)
    print(f"=== {time.strftime('%F %T')} {half} complete", flush=True)
    return 0


# --------------------------------------------------------------------------- #
def rates(rows: "list[dict]") -> dict:
    """{(a, b): [n applied, n fewer fails, n declined, mean mid-minus-parent]}"""
    out = collections.defaultdict(lambda: [0, 0, 0, []])
    for r in rows:
        k = (r["a"], r["b"])
        if r["status"] != "ok":
            out[k][2] += 1
            continue
        out[k][0] += 1
        out[k][1] += r["fails"] < r["parent_fails"]
        if r.get("mid") is not None:
            out[k][3].append(r["mid"] - r["parent_fails"])
    return out


def ranking(rows: "list[dict]", min_n: int = 8) -> "list[tuple[tuple, float]]":
    """Pairs by how far their rate of removing a fail exceeds the better single."""
    rt = rates(rows)

    def rate(k):
        n, w = rt[k][0], rt[k][1]
        return w / n if n else 0.0

    out = []
    for (x, y), v in rt.items():
        if y is None or v[0] < min_n:
            continue
        out.append(((x, y), rate((x, y)) - max(rate((x, None)), rate((y, None)))))
    return sorted(out, key=lambda t: -t[1])


def _wilson(w: int, n: int) -> str:
    if not n:
        return "      -"
    z, p = 1.96, w / n
    d = 1 + z * z / n
    mid, half = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{100 * (mid - half):4.1f}-{100 * (mid + half):4.1f}%"


def per_parent(rows: "list[dict]", k: tuple) -> dict:
    """{parent: share of applied draws that removed a fail} for one arm."""
    by = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        if (r["a"], r["b"]) == k and r["status"] == "ok":
            by[r["dom"]][0] += 1
            by[r["dom"]][1] += r["fails"] < r["parent_fails"]
    return {d: 100 * w / n for d, (n, w) in by.items() if n}


def report(a) -> int:
    ab = _load("ab_report")
    scr, con = load("screen", a.programme), load("confirm", a.programme)
    if not scr:
        print("no screen yet")
        return 1
    rt = rates(scr)
    cpu = sum(r["cpu"] for r in scr)
    print(f"{a.programme}: SCREEN, {len({r['dom'] for r in scr})} stuck parents, "
          f"{len(scr)} children, {cpu / 3600:.1f} CPU-hours\n")
    print(f"{'alone':<20} {'applied':>7} {'declined':>8} {'fewer fails':>12}")
    for k in sorted((k for k in rt if k[1] is None), key=lambda k: -rt[k][1] / max(1, rt[k][0])):
        n, w, dcl, _ = rt[k]
        print(f"{k[0]:<20} {n:>7} {dcl:>8} {100 * w / max(1, n):>11.1f}%")
    pairs = [k for k in rt if k[1] is not None]
    n_all = sum(rt[k][0] for k in pairs)
    w_all = sum(rt[k][1] for k in pairs)
    print(f"\nany pair: {n_all} applied, fewer fails {100 * w_all / max(1, n_all):.1f}%")
    print(f"\n{'pair (first, then)':<36} {'applied':>7} {'fewer fails':>12} {'better single':>14} "
          f"{'margin':>7} {'after the first move':>21}")
    rank = ranking(scr)
    for (x, y), m in rank[: a.top]:
        n, w, _, mid = rt[(x, y)]
        best = max(rt[(x, None)][1] / max(1, rt[(x, None)][0]),
                   rt[(y, None)][1] / max(1, rt[(y, None)][0]))
        print(f"{x + ', ' + y:<36} {n:>7} {100 * w / n:>11.1f}% {100 * best:>13.1f}% "
              f"{100 * m:>+6.1f} {sum(mid) / max(1, len(mid)):>+14.1f} fails")
    print(f"\n({len(rank)} pairs ranked; the margin of the best of that many is flattered by "
          "the choosing, which is what the other half is for)")
    if not con:
        print("\nno confirm half yet")
        return 0
    print(f"\n{a.programme}: CONFIRM, {len({r['dom'] for r in con})} OTHER parents, "
          f"{len(con)} children\n")
    rc = rates(con)
    print(f"{'alone':<20} {'applied':>7} {'fewer fails':>12}   95% interval")
    for k in sorted((k for k in rc if k[1] is None), key=lambda k: -rc[k][1] / max(1, rc[k][0])):
        n, w = rc[k][0], rc[k][1]
        print(f"{k[0]:<20} {n:>7} {100 * w / max(1, n):>11.1f}%   {_wilson(w, n)}")
    print(f"\n{'pair':<36} {'applied':>7} {'fewer fails':>12}   95% interval   "
          "against its better single, paired over parents")
    for k in sorted((k for k in rc if k[1] is not None), key=lambda k: -rc[k][1] / max(1, rc[k][0])):
        n, w = rc[k][0], rc[k][1]
        sx, sy = rc[(k[0], None)], rc[(k[1], None)]
        better = (k[0], None) if sx[1] / max(1, sx[0]) >= sy[1] / max(1, sy[0]) else (k[1], None)
        pp, ps = per_parent(con, k), per_parent(con, better)
        both = sorted(set(pp) & set(ps))
        verdict = "too few parents"
        if len(both) >= 2:
            r = ab.paired_report([pp[d] for d in both], [ps[d] for d in both], "pair", better[0])
            verdict = (f"{r['mean_diff']:+.1f} points (MDD {r['mdd']:.1f}, N={r['n']})"
                       + ("" if abs(r["mean_diff"]) > r["mdd"] else "  unresolved"))
        print(f"{k[0] + ', ' + k[1]:<36} {n:>7} {100 * w / max(1, n):>11.1f}%   "
              f"{_wilson(w, n)}   {verdict}")
    return 0


def self_test() -> int:
    """A planted pair must top the ranking; with none planted, the best
    margin of a screen must NOT survive on a second sample."""
    rng = random.Random(3)

    def fake(planted: bool, seed: int) -> "list[dict]":
        rng.seed(seed)
        rows = []
        for d in range(20):
            for x in OPS:
                for i in range(6):
                    rows.append({"dom": f"p{d}", "a": x, "b": None, "draw": i, "status": "ok",
                                 "parent_fails": 2, "fails": 1 if rng.random() < 0.03 else 2})
                for y in OPS:
                    hit = 0.30 if planted and (x, y) == ("swap", "undivide") else 0.03
                    for i in range(2):
                        rows.append({"dom": f"p{d}", "a": x, "b": y, "draw": i, "status": "ok",
                                     "parent_fails": 2, "mid": 3,
                                     "fails": 1 if rng.random() < hit else 2})
        return rows

    found = ranking(fake(True, 1))[0][0] == ("swap", "undivide")
    k, m1 = ranking(fake(False, 2))[0]
    again = dict(ranking(fake(False, 4)))[k]
    ok = found and m1 > 0.03 and again < m1 / 2
    print(f"  planted pair ranked first: {found}")
    print(f"  nothing planted: the screen's best pair shows {100 * m1:+.1f} points, "
          f"and {100 * again:+.1f} on a second sample")
    print("self-test", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", default="programme-house")
    ap.add_argument("--table", default="child20_ab", help="results table naming the parents")
    ap.add_argument("--dir", default="child20-ab", help="its artefact directory")
    ap.add_argument("--screen", action="store_true")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--pair-draws", type=int, default=2, help="per pair per parent, screen")
    ap.add_argument("--single-draws", type=int, default=6, help="per move per parent, screen")
    ap.add_argument("--confirm-draws", type=int, default=12)
    ap.add_argument("--top", type=int, default=12, help="pairs carried to the confirm half")
    ap.add_argument("--limit", type=int, help="run only this many tasks (smoke)")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.limit:
        global tasks
        full = tasks
        tasks = lambda half, a: random.Random(2).sample(full(half, a), a.limit)  # noqa: E731
    if a.screen:
        return run("screen", a)
    if a.confirm:
        return run("confirm", a)
    return report(a)


if __name__ == "__main__":
    sys.exit(main())

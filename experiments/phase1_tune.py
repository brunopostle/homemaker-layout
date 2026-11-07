"""Phase 1 of the aggregation review: tuned twins (`homemaker-py-5fje.4`,
DESIGN.md §39.201, §39.208).

Each design's walls are re-tuned under each candidate score, topology fixed,
every arm from the design's own ratios at the same budget, so A0 is the
control for "more tuning". This is `diag_aggregation_tune.py`'s method made
to run at scale: one task per (design, arm), in parallel, resumable (a tuned
design already on disk is not tuned again), and judged on the report card
(§39.205), never on any arm's own score.

Arms (``--arms``): A0 today's score; P1 at phi 1e-3; P1u, P1 unfloored
(phi 1e-20, so a room far from its brief still has a gradient back).

    # tune (default designs: the 25 race finalists, the 12 c836457+orth
    # cold-start designs and the hand-drawn programme-house)
    HOMEMAKER_ORTHOGONAL_DIVISION=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \\
        python experiments/phase1_tune.py tune --budget 3000 --jobs 8
    # the paired report card
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/phase1_tune.py report

Tuned designs go to ``--out`` (default experiments/results/phase1/) as
``<dir>--<stem>--<arm>.dom``, with the report card of every design, as found
and tuned, in ``cards.tsv`` there.
"""
import argparse
import copy
import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
OUT = HERE / "results" / "phase1"
ARMS = {"A0": ("A0", None), "P1": ("P1", 1e-3), "P1u": ("P1", 1e-20)}
RERANK = HERE / "results" / "aggregation" / "rerank-phi1e-3.tsv"
HAND = "examples/programme-house/hand-3storey.dom"
# columns compared between twins; the sign says which way is better for the
# reader, nothing is summed
COLS = ["token", "sliver", "missing", "shortfall_m2", "surplus_m2", "ratio_big5",
        "adj_share", "no_door", "unlit", "deep", "connected", "stair_storeys",
        "circ_share", "inside_m2", "wall_per_m2", "cost"]


def default_designs():
    rows = [line.split("\t")[1] for line in RERANK.read_text().splitlines()[1:] if line.strip()]
    finalists = [p for p in rows if p.startswith("experiments/")]
    cold = [p for p in rows if "coldstart-c836457+orth-500000" in p]
    return finalists + cold + [HAND]


def name(path, arm):
    p = Path(path)
    return f"{p.parent.name}--{p.stem}--{arm}.dom"


def tune_one(task):
    path, arm, budget, out = task
    dest = Path(out) / name(path, arm)
    if dest.exists():
        return path, arm, None
    from diag_aggregation import arms
    import report_card as rc
    from homemaker_layout import dom, fitness, innerloop

    which, phi = ARMS[arm]
    prog, fit, reqs = rc.Programmes()(path)
    d = rc.REPO / "examples" / prog
    root = dom.load(str(rc.REPO / path))
    dom.link(root)
    real = fitness.Fitness.score_with_fails

    def score_with_fails(self, r):
        fitness.Fitness.score_with_fails = real
        try:
            got = arms(self, reqs, r, phi)
        finally:
            fitness.Fitness.score_with_fails = score_with_fails
        return got[which], got["fail_lines"]

    t = time.process_time()
    if which != "A0":
        fitness.Fitness.score_with_fails = score_with_fails
    try:
        innerloop.optimise(root, d, budget=budget, method="nm")
    finally:
        fitness.Fitness.score_with_fails = real
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(dom.dumps(root))
    tmp.rename(dest)
    return path, arm, time.process_time() - t


def tune(a):
    from homemaker_layout import geometry
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    designs = a.designs or default_designs()
    arms = a.arms.split(",")
    tasks = [(p, arm, a.budget, str(out)) for p in designs for arm in arms]
    (out / "run.json").write_text(json.dumps(dict(budget=a.budget, arms=arms, designs=designs),
                                             indent=1) + "\n")
    todo = [t for t in tasks if not (out / name(t[0], t[1])).exists()]
    print(f"{len(tasks)} tasks, {len(todo)} to run, {a.jobs} at a time", flush=True)
    with Pool(a.jobs, maxtasksperchild=1) as pool:
        for n, (path, arm, cpu) in enumerate(pool.imap_unordered(tune_one, todo), 1):
            print(f"[{n}/{len(todo)}] {arm:4s} {cpu:7.0f} s cpu  {path}", flush=True)
    return 0


def report(a):
    import statistics
    from ab_report import paired_report
    import report_card as rc
    from homemaker_layout import geometry
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    out = Path(a.out)
    run = json.loads((out / "run.json").read_text())
    progs = rc.Programmes()
    cards = {}
    lines = ["design\tarm\tprogramme\t" + "\t".join(rc.DESIGN_COLS)]
    for path in run["designs"]:
        prog = progs(path)[0]
        for arm in ["found"] + run["arms"]:
            f = rc.REPO / path if arm == "found" else out / name(path, arm)
            if not f.exists():
                continue
            row, _ = rc.card_of(progs, f, prog)
            cards[path, arm] = (prog, row)
            lines.append(f"{path}\t{arm}\t{prog}\t" + "\t".join(rc.fmt(row[c]) for c in rc.DESIGN_COLS))
    (out / "cards.tsv").write_text("\n".join(lines) + "\n")
    for arm in [x for x in run["arms"] if x != "A0"]:
        both = [p for p in run["designs"] if (p, "A0") in cards and (p, arm) in cards]
        print(f"\n== {arm}-tuned against A0-tuned twins, {len(both)} designs"
              " (diff = A0 minus " + arm + "; '+' means lower under " + arm + ")")
        print(f"  {'column':14s} {'A0 med':>9s} {arm + ' med':>9s} {'lower':>6s} {'higher':>6s}"
              f" {'mean diff':>10s} {'MDD':>9s}  verdict")
        for c in COLS:
            x = [cards[p, "A0"][1][c] for p in both]
            y = [cards[p, arm][1][c] for p in both]
            lower = sum(b < aa for aa, b in zip(x, y))
            higher = sum(b > aa for aa, b in zip(x, y))
            r = paired_report(x, y, "A0", arm)
            sig = "resolved" if abs(r["mean_diff"]) > r["mdd"] else "within MDD"
            print(f"  {c:14s} {statistics.median(x):9.4g} {statistics.median(y):9.4g} "
                  f"{lower:6d} {higher:6d} {r['mean_diff']:10.4g} {r['mdd']:9.3g}  {sig}")
        by = {}
        for p in both:
            by.setdefault(cards[p, "A0"][0], []).append(p)
        print("  by programme, medians A0 -> " + arm + ":")
        for prog, ps in sorted(by.items()):
            print(f"    {prog:16s} n={len(ps):2d}  " + "  ".join(
                f"{c} {statistics.median(cards[p, 'A0'][1][c] for p in ps):.3g}->"
                f"{statistics.median(cards[p, arm][1][c] for p in ps):.3g}"
                for c in ("token", "sliver", "missing", "adj_share", "circ_share", "connected")))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tune")
    t.add_argument("designs", nargs="*")
    t.add_argument("--arms", default="A0,P1,P1u")
    t.add_argument("--budget", type=int, default=3000)
    t.add_argument("--jobs", type=int, default=os.cpu_count())
    t.add_argument("--out", default=str(OUT))
    r = sub.add_parser("report")
    r.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    return {"tune": tune, "report": report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())

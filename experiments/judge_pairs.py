"""Blind pairwise judging: two plans of one programme, the owner picks the
better (`homemaker-py-5fje.3`, DESIGN.md §39.201 instrument 3, §39.206).

The owner's time is the scarce resource, so a round asks only pairs on which
the candidate scores DISAGREE, the more confidently the better: a pair every
candidate orders the same way can drop none of them. Each candidate's verdict
is the sign of its log score ratio, scaled by that candidate's spread of log
scores within the programme so that A0's and P1's confidences compare; a
pair's strength is the smaller of two opposing confidences. Pairs are taken
strongest first, programmes in turn, each design in at most ``--per-design``
pairs, and none already judged in an earlier round.

    # build a round (default designs: the report card's 98)
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/judge_pairs.py build --round 1
    # answer it (opens each pair in the browser, asks in the terminal)
    python experiments/judge_pairs.py ask --round 1
    # what the answers say, any time
    python experiments/judge_pairs.py report

Blind means the drawings carry no score, no fail list, no file name and no
design name: each room shows its code, its name, its built area and the area
the brief asks for. Which design is on the left is drawn at random when it is
asked. Answers are appended to `experiments/results/judging/answers.tsv`, so a
round can be stopped (q) and resumed, and later rounds add to the same file.

Tuned twins of one topology (Phase 1) are the cleanest pairs: same plan,
different walls. Pass their paths as the designs of a round; nothing else
changes.
"""
import argparse
import datetime
import html
import json
import math
import random
import statistics
import sys
import webbrowser
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
OUT = HERE / "results" / "judging"
ANSWERS = OUT / "answers.tsv"
COLS = ["when", "round", "pair", "left", "answer", "better", "note"]
DEFAULT_DESIGNS = HERE / "results" / "aggregation" / "report-card.tsv"
# (label, arm in diag_aggregation.arms, phi)
CANDIDATES = [("A0", "A0", 1e-3), ("P1", "P1", 1e-3)]
# report-card columns compared in the report, against the owner's choices
FACTS = ["missing", "token", "shortfall_m2", "surplus_m2", "deep", "unlit",
         "adj_met", "no_door", "connected", "stair_storeys", "circ_share",
         "narrowest", "wall_per_m2", "cost"]


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #

def score_all(designs, candidates):
    """{path: {"programme", "scores": {label: score}, "card": {...}}}"""
    from diag_aggregation import arms
    import report_card as rc
    from homemaker_layout import dom, geometry

    progs = rc.Programmes()
    out = {}
    for path in designs:
        p = progs(path)
        if p is None:
            print(f"# skipped, no programme in path: {path}", file=sys.stderr)
            continue
        prog, fit, reqs = p
        scores = {}
        for lab, arm, phi in candidates:
            root = dom.load(str(rc.REPO / path))
            dom.link(root)
            geometry.clear_cache()
            scores[lab] = arms(fit, reqs, root, phi)[arm]
        card, _ = rc.card_of(progs, rc.REPO / path, prog)
        out[path] = dict(programme=prog, scores=scores, card=card)
    return out


def judged_before():
    """Unordered design pairs already in any round's pairs.json."""
    seen = set()
    for f in OUT.glob("round-*/pairs.json"):
        for p in json.loads(f.read_text()):
            seen.add(frozenset((p["a"], p["b"])))
    return seen


def choose(scored, labels, n_pairs, per_design, exclude=frozenset()):
    """The pairs to ask, strongest disagreement first, programmes in turn."""
    by_prog = {}
    for path, d in scored.items():
        by_prog.setdefault(d["programme"], []).append(path)
    cands = {}
    for prog, paths in by_prog.items():
        logs = {lab: {p: math.log(max(scored[p]["scores"][lab], 1e-300)) for p in paths}
                for lab in labels}
        spread = {lab: statistics.pstdev(logs[lab].values()) or 1.0 for lab in labels}
        rows = []
        for a, b in combinations(sorted(paths), 2):
            if frozenset((a, b)) in exclude:
                continue
            z = {lab: (logs[lab][a] - logs[lab][b]) / spread[lab] for lab in labels}
            best = 0.0
            for x, y in combinations(labels, 2):
                if z[x] * z[y] < 0:
                    best = max(best, min(abs(z[x]), abs(z[y])))
            if best > 0:
                rows.append((best, a, b, z))
        rows.sort(key=lambda r: -r[0])
        cands[prog] = rows
    used, chosen = {}, []
    progs = sorted(cands)
    while len(chosen) < n_pairs and any(cands.values()):
        for prog in progs:
            rows = cands[prog]
            while rows:
                s, a, b, z = rows.pop(0)
                if used.get(a, 0) < per_design and used.get(b, 0) < per_design:
                    used[a] = used.get(a, 0) + 1
                    used[b] = used.get(b, 0) + 1
                    chosen.append((prog, s, a, b, z))
                    break
            if len(chosen) >= n_pairs:
                break
    return chosen


def build(a):
    from homemaker_layout import geometry
    import plan_svg
    import report_card as rc

    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    designs = a.designs or [line.split("\t")[1] for line in
                            DEFAULT_DESIGNS.read_text().splitlines()[1:] if line.strip()]
    out = OUT / f"round-{a.round}"
    if (out / "pairs.json").exists() and not a.force:
        sys.exit(f"{out / 'pairs.json'} exists; --force to rebuild (answers keep their pair ids)")
    labels = [c[0] for c in CANDIDATES]
    print(f"scoring {len(designs)} designs under {', '.join(labels)}", file=sys.stderr)
    scored = score_all(designs, CANDIDATES)
    exclude = judged_before() - (set() if not (out / "pairs.json").exists() else {
        frozenset((p["a"], p["b"])) for p in json.loads((out / "pairs.json").read_text())})
    chosen = choose(scored, labels, a.pairs, a.per_design, exclude)
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, (prog, strength, pa, pb, z) in enumerate(chosen, 1):
        pid = f"R{a.round}-{i:02d}"
        side = {}
        for s, path in (("a", pa), ("b", pb)):
            svg = plan_svg.render(rc.REPO / path, rc.REPO / "examples" / prog, f"{prog}",
                                  blind=True, note="each room: built area of the area the brief asks")
            (out / f"{pid}-{s}.svg").write_text(svg)
            side[s] = dict(path=path, svg=f"{pid}-{s}.svg",
                           scores=scored[path]["scores"], card=scored[path]["card"])
        manifest.append(dict(
            id=pid, round=a.round, programme=prog, a=pa, b=pb, strength=strength, z=z,
            better={lab: ("A" if z[lab] > 0 else "B") for lab in labels},
            sides=side))
        print(f"{pid} {prog:16s} strength {strength:5.2f}  "
              + "  ".join(f"{lab} prefers {'A' if z[lab] > 0 else 'B'} ({z[lab]:+.2f})"
                          for lab in labels)
              + f"\n      A {pa}\n      B {pb}")
    (out / "pairs.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"\nwrote {len(manifest)} pairs to {out / 'pairs.json'}. To answer:\n"
          f"    python experiments/judge_pairs.py ask --round {a.round}")
    return 0


# --------------------------------------------------------------------------- #
# ask
# --------------------------------------------------------------------------- #

def load_pairs():
    pairs = {}
    for f in sorted(OUT.glob("round-*/pairs.json")):
        for p in json.loads(f.read_text()):
            p["dir"] = f.parent
            pairs[p["id"]] = p
    return pairs


def load_answers():
    got = {}
    if ANSWERS.exists():
        for line in ANSWERS.read_text().splitlines()[1:]:
            row = dict(zip(COLS, line.split("\t")))
            if row.get("better") in ("A", "B", "="):
                got[row["pair"]] = row          # newest wins
    return got


def page(p, left, n, total):
    right = "b" if left == "a" else "a"
    cells = "".join(
        f'<div class="side"><h2>{lab}</h2><img src="{html.escape(p["sides"][s]["svg"])}"></div>'
        for lab, s in (("LEFT", left), ("RIGHT", right)))
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>pair {n} of {total}</title><style>
body {{ font-family: Helvetica, Arial, sans-serif; margin: 1em; }}
.q {{ font-size: 1.3em; max-width: 70em; }}
.side {{ border: 1px solid #aaa; padding: .5em; margin-bottom: 1em; }}
.side img {{ width: 100%; }}
</style></head><body>
<p class="q"><b>Pair {n} of {total}</b> ({html.escape(p['programme'])}). Two designs for the same
brief. <b>Which is the better building?</b> Or are they about as good as each other?</p>
<p>Answer in the terminal. Each room shows its built area and the area the brief asks for.</p>
{cells}</body></html>"""


def ask(a):
    pairs = load_pairs()
    todo = [p for p in pairs.values()
            if (a.round is None or str(p["round"]) == str(a.round)) and p["id"] not in load_answers()]
    rng = random.Random()
    rng.shuffle(todo)
    total = len(todo)
    if not total:
        print("nothing left to ask in that round")
    if not ANSWERS.exists():
        OUT.mkdir(parents=True, exist_ok=True)
        ANSWERS.write_text("\t".join(COLS) + "\n")
    for n, p in enumerate(todo, 1):
        left = rng.choice("ab")
        cur = p["dir"] / "current.html"
        cur.write_text(page(p, left, n, total))
        if not a.no_browser:
            webbrowser.open(cur.as_uri())
        print(f"\npair {n} of {total} ({p['programme']})   page: {cur}")
        while True:
            try:
                ans = input("  Which is better?  l = left, r = right, e = about equal, "
                            "s = skip, q = quit > ").strip().lower()
            except EOFError:
                ans = "q"
            if ans in ("l", "r", "e", "s", "q"):
                break
        if ans == "q":
            print("\nStopped; run again to carry on where you left off.")
            break
        if ans == "s":
            better = "skip"
        elif ans == "e":
            better = "="
        else:
            side = left if ans == "l" else ("b" if left == "a" else "a")
            better = side.upper()
        try:
            note = input("  Note (optional, Enter for none) > ").strip().replace("\t", " ")
        except EOFError:
            note = ""
        with ANSWERS.open("a") as f:
            f.write("\t".join([datetime.datetime.now().isoformat(timespec="seconds"),
                               str(p["round"]), p["id"], left, ans, better, note]) + "\n")
    report(a)
    return 0


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #

def binom_two_sided(k, n):
    """Exact two-sided sign-test p for k of n at 1/2."""
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def report(a):
    pairs, got = load_pairs(), load_answers()
    rows = [(pairs[k], r) for k, r in got.items() if k in pairs
            and (a.round is None or str(pairs[k]["round"]) == str(a.round))]
    if not rows:
        print("no answers yet")
        return 0
    decisive = [(p, r) for p, r in rows if r["better"] in ("A", "B")]
    print(f"\n== {len(rows)} pairs answered: {len(decisive)} decisive, "
          f"{len(rows) - len(decisive)} 'about equal'")
    labels = list(rows[0][0]["better"])
    for lab in labels:
        k = sum(p["better"][lab] == r["better"] for p, r in decisive)
        print(f"  {lab:4s} agrees on {k} of {len(decisive)}"
              f"   (sign test against chance, two-sided p = {binom_two_sided(k, len(decisive)):.3g})")
    progs = sorted({p["programme"] for p, _ in decisive})
    if len(progs) > 1:
        for prog in progs:
            sub = [(p, r) for p, r in decisive if p["programme"] == prog]
            print(f"    {prog:16s} " + "  ".join(
                f"{lab} {sum(p['better'][lab] == r['better'] for p, r in sub)}/{len(sub)}"
                for lab in labels))
    print("\n  report-card facts, over the decisive answers: how often the plan chosen"
          " has the larger value (ties left out)")
    for c in FACTS:
        more = less = 0
        for p, r in decisive:
            win, lose = (("a", "b") if r["better"] == "A" else ("b", "a"))
            x, y = p["sides"][win]["card"].get(c), p["sides"][lose]["card"].get(c)
            if x is None or y is None or x == y:
                continue
            more += x > y
            less += x < y
        if more + less:
            print(f"    {c:14s} larger in {more} of {more + less}"
                  f"   (p = {binom_two_sided(more, more + less):.3g})")
    notes = [(p["id"], r["note"]) for p, r in rows if r.get("note")]
    if notes:
        print("\n  notes:")
        for pid, note in notes:
            print(f"    {pid}: {note}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="choose and draw a round's pairs")
    b.add_argument("designs", nargs="*", help="default: the designs of report-card.tsv")
    b.add_argument("--round", required=True)
    b.add_argument("--pairs", type=int, default=30)
    b.add_argument("--per-design", type=int, default=2)
    b.add_argument("--force", action="store_true")
    k = sub.add_parser("ask", help="put a round's pairs to the judge")
    k.add_argument("--round")
    k.add_argument("--no-browser", action="store_true")
    r = sub.add_parser("report", help="what the answers say")
    r.add_argument("--round")
    a = ap.parse_args()
    return {"build": build, "ask": ask, "report": report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())

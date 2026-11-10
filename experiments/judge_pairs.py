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

Tuned twins of one topology (Phase 1, §39.208) are the cleanest pairs: same
plan, different walls. ``build --twins`` reads ``experiments/phase1_tune.py``'s
run and pairs each design's A0-tuned twin with its P1- or P1u-tuned twin,
keeping, as above, only pairs on which A0 and P1 disagree, one pair per
design. The report then also says which tuning the judge chose:

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/judge_pairs.py build --round 1 --twins

Phase 3's arms (§39.220) are judged by ``build --arms``: every paired start
(programme, k) of each contrast, the files ``<arm>--<programme>--<k>.dom`` of
``--arms-dir``. Nothing is filtered on the scores, because the question is
which ARM gives the better building and a filtered sample would answer a
different one. Only pairs whose two files are byte-identical are dropped (a
run that the arm did not change has nothing to judge). The report says which
arm the judge chose, per contrast:

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/judge_pairs.py build --round 2 \
        --arms A0-fails:P1-fails,A0-fails:A0-tiers,P1-fails:P1-score
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
FACTS = ["missing", "token", "sliver", "shortfall_m2", "surplus_m2", "deep", "unlit",
         "adj_share", "no_door", "connected", "stair_storeys", "circ_share",
         "narrowest", "wall_per_m2", "cost"]


def fact(card, c):
    """A report-card value; ``adj_share`` is derived for cards frozen in a
    round's pairs.json before the column existed. ``sliver`` cannot be, and
    reads None on those."""
    if c == "adj_share" and c not in card:
        return card["adj_met"] / card["adj_asked"] if card.get("adj_asked") else None
    return card.get(c)


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #

def score_all(designs, candidates, progs_of=None):
    """{path: {"programme", "scores": {label: score}, "card": {...}}}.
    ``progs_of`` maps a path to its programme where the path does not say."""
    from diag_aggregation import arms
    import report_card as rc
    from homemaker_layout import dom, geometry

    progs = rc.Programmes()
    out = {}
    for path in designs:
        p = progs(path, (progs_of or {}).get(path))
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
    return _take(cands, n_pairs, per_design)


def _take(cands, n_pairs, per_design, key=lambda path: path):
    """Strongest first, programmes in turn, each ``key`` in at most
    ``per_design`` pairs. ``cands``: {prog: [(strength, a, b, z)]}."""
    cands = {prog: list(rows) for prog, rows in cands.items()}
    used, chosen = {}, []
    progs = sorted(cands)
    while len(chosen) < n_pairs and any(cands.values()):
        for prog in progs:
            rows = cands[prog]
            while rows:
                s, a, b, z = rows.pop(0)
                ka, kb = key(a), key(b)
                if used.get(ka, 0) < per_design and used.get(kb, 0) < per_design:
                    used[ka] = used.get(ka, 0) + 1
                    if kb != ka:
                        used[kb] = used.get(kb, 0) + 1
                    chosen.append((prog, s, a, b, z))
                    break
            if len(chosen) >= n_pairs:
                break
    return chosen


def choose_twins(scored, twins, labels, n_pairs, arm_pairs):
    """Pairs of twins of one design, ``twins`` {path: (design, arm)}: for each
    design and each (x, y) in ``arm_pairs``, its x twin against its y twin,
    kept only where the candidates disagree; one pair per design, the arm
    pairs taken in turn over a programme's designs."""
    by_design = {}
    for path, (design, arm) in twins.items():
        if path in scored:
            by_design.setdefault(design, {})[arm] = path
    cands = {}
    for prog in sorted({d["programme"] for d in scored.values()}):
        paths = [p for p in scored if scored[p]["programme"] == prog]
        logs = {lab: {p: math.log(max(scored[p]["scores"][lab], 1e-300)) for p in paths}
                for lab in labels}
        spread = {lab: statistics.pstdev(logs[lab].values()) or 1.0 for lab in labels}
        rows = []
        mine = sorted(d for d, arms_ in by_design.items()
                      if any(scored[p]["programme"] == prog for p in arms_.values()))
        for i, design in enumerate(mine):
            arms_ = by_design[design]
            # alternate the arm pairs over a programme's designs, so each is
            # asked about equally; another pair only where the first agrees
            order = arm_pairs[i % len(arm_pairs):] + arm_pairs[:i % len(arm_pairs)]
            for x, y in order:
                a, b = arms_.get(x), arms_.get(y)
                if a is None or b is None:
                    continue
                z = {lab: (logs[lab][a] - logs[lab][b]) / spread[lab] for lab in labels}
                best = 0.0
                for u, v in combinations(labels, 2):
                    if z[u] * z[v] < 0:
                        best = max(best, min(abs(z[u]), abs(z[v])))
                if best > 0:
                    rows.append((best, a, b, z))
                    break
        rows.sort(key=lambda r: -r[0])
        cands[prog] = rows
    return _take(cands, n_pairs, 1, key=lambda path: twins[path][0])


def choose_arms(scored, runs, labels, contrasts):
    """Every paired start of each contrast. ``runs`` {path: (arm, programme,
    k)}; ``contrasts`` [(x, y)]. Pairs come back interleaved -- contrast by
    contrast, then programme by programme -- so a round stopped early still
    covers every contrast. Byte-identical pairs are left out."""
    by = {(arm, prog, k): path for path, (arm, prog, k) in runs.items() if path in scored}
    starts = sorted({(prog, k) for _, prog, k in by})
    per = []
    for x, y in contrasts:
        rows = []
        for prog, k in starts:
            a, b = by.get((x, prog, k)), by.get((y, prog, k))
            if a is None or b is None:
                continue
            if _same_bytes(a, b):
                continue
            z = {}
            for lab in labels:
                ps = [p for p in scored if scored[p]["programme"] == prog]
                logs = [math.log(max(scored[p]["scores"][lab], 1e-300)) for p in ps]
                spread = statistics.pstdev(logs) or 1.0
                z[lab] = (math.log(max(scored[a]["scores"][lab], 1e-300))
                          - math.log(max(scored[b]["scores"][lab], 1e-300))) / spread
            rows.append((prog, 0.0, a, b, z))
        per.append(rows)
    out = []
    while any(per):
        for rows in per:
            if rows:
                out.append(rows.pop(0))
    return out


def _same_bytes(a, b):
    import report_card as rc
    pa, pb = Path(a), Path(b)
    pa = pa if pa.is_absolute() else rc.REPO / pa
    pb = pb if pb.is_absolute() else rc.REPO / pb
    return pa.read_bytes() == pb.read_bytes()


def build(a):
    from homemaker_layout import geometry
    import plan_svg
    import report_card as rc

    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    twins, progs_of = {}, {}
    if a.twins and a.arms:
        sys.exit("--twins and --arms are two different rounds; give one")
    if a.twins:
        import phase1_tune
        run = json.loads((Path(a.twins_dir) / "run.json").read_text())
        progs = rc.Programmes()
        for design in run["designs"]:
            prog = progs(design)[0]
            for arm in run["arms"]:
                f = Path(a.twins_dir) / phase1_tune.name(design, arm)
                if f.exists():
                    path = str(f.resolve().relative_to(rc.REPO))
                    twins[path] = (design, arm)
                    progs_of[path] = prog
        designs = list(twins)
    elif a.arms:
        import re
        pat = re.compile(r"(?P<arm>[^/]+?)--(?P<prog>[a-z-]+)--(?P<k>\d+)\.dom$")
        contrasts = [tuple(c.split(":")) for c in a.arms.split(",")]
        wanted = {x for c in contrasts for x in c}
        for f in sorted(Path(a.arms_dir).glob("*--*--*.dom")):
            m = pat.search(f.name)
            if m and m["arm"] in wanted:
                path = str(f.resolve().relative_to(rc.REPO))
                twins[path] = (m["arm"], m["prog"], m["k"])
                progs_of[path] = m["prog"]
        designs = list(twins)
    else:
        designs = a.designs or [line.split("\t")[1] for line in
                                DEFAULT_DESIGNS.read_text().splitlines()[1:] if line.strip()]
    out = OUT / f"round-{a.round}"
    if (out / "pairs.json").exists() and not a.force:
        sys.exit(f"{out / 'pairs.json'} exists; --force to rebuild (answers keep their pair ids)")
    labels = [c[0] for c in CANDIDATES]
    print(f"scoring {len(designs)} designs under {', '.join(labels)}", file=sys.stderr)
    scored = score_all(designs, CANDIDATES, progs_of)
    if a.twins:
        arm_pairs = [tuple(x.split("-")) for x in a.twins.split(",")]
        chosen = choose_twins(scored, twins, labels, a.pairs, arm_pairs)
    elif a.arms:
        chosen = choose_arms(scored, twins, labels, contrasts)
    else:
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
        if a.twins:
            manifest[-1].update(design=twins[pa][0], arms=dict(a=twins[pa][1], b=twins[pb][1]))
        elif a.arms:
            manifest[-1].update(design=f"{prog}--{twins[pa][2]}",
                                arms=dict(a=twins[pa][0], b=twins[pb][0]))
        print(f"{pid} {prog:16s} "
              + (f"{twins[pa][0]} vs {twins[pb][0]}  " if a.arms else f"strength {strength:5.2f}  ")
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
            x, y = fact(p["sides"][win]["card"], c), fact(p["sides"][lose]["card"], c)
            if x is None or y is None or x == y:
                continue
            more += x > y
            less += x < y
        if more + less:
            print(f"    {c:14s} larger in {more} of {more + less}"
                  f"   (p = {binom_two_sided(more, more + less):.3g})")
    twin = [(p, r) for p, r in rows if "arms" in p]
    if twin:
        print("\n  arms: which one the judge chose")
        tally = {}
        for p, r in twin:
            match = tuple(sorted(p["arms"].values()))
            t = tally.setdefault(match, {"=": 0})
            if r["better"] in ("A", "B"):
                arm = p["arms"][r["better"].lower()]
                t[arm] = t.get(arm, 0) + 1
            else:
                t["="] += 1
        for match, t in sorted(tally.items()):
            k = t.get(match[0], 0)
            n = sum(t.get(x, 0) for x in match)
            print(f"    {' vs '.join(match):22s} " + "  ".join(f"{x} {t.get(x, 0)}" for x in match)
                  + f"  about equal {t['=']}"
                  + (f"   (p = {binom_two_sided(k, n):.3g})" if n else ""))
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
    b.add_argument("--twins", nargs="?", const="A0-P1,A0-P1u", default=None,
                   help="pair Phase 1's tuned twins of one design; the arm pairs to "
                        "consider (default: A0-P1,A0-P1u)")
    b.add_argument("--twins-dir", default=str(HERE / "results" / "phase1"))
    b.add_argument("--arms", default=None,
                   help="judge whole arms: contrasts x:y,... over the paired starts of "
                        "--arms-dir, e.g. A0-fails:P1-fails")
    b.add_argument("--arms-dir", default=str(HERE / "results" / "phase3-q2"))
    k = sub.add_parser("ask", help="put a round's pairs to the judge")
    k.add_argument("--round")
    k.add_argument("--no-browser", action="store_true")
    r = sub.add_parser("report", help="what the answers say")
    r.add_argument("--round")
    a = ap.parse_args()
    return {"build": build, "ask": ask, "report": report}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())

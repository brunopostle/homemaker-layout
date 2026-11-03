"""Put the ordering questionnaire to the owner, one item at a time
(`homemaker-py-5fje.2`, DESIGN.md §39.201-§39.203).

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/ask_questionnaire.py

Reads `experiments/results/questionnaire/items.json` (built and pre-tested by
`questionnaire.py`; only items the candidate scores disagree on are asked).
For each comparison it writes a page with the two plans side by side, opens
it in the browser, and asks in the terminal which is worse. Which version is
on the left is random. Scores and fail lists are never shown.

A "ladder" item is asked as a bisection: each answer picks the next rung, so
a ladder of seven rungs takes about three answers.

Answers are appended to `answers.tsv` beside the items as they are given, so
it can be stopped (q) and resumed; `--again` asks everything afresh (the old
answers stay in the file, the newest per comparison counts). At the end, and
with `--report` at any time, it prints which candidate scores agree with the
answers so far.
"""
import argparse
import datetime
import html
import json
import random
import sys
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent / "results" / "questionnaire"
COLS = ["when", "item", "rung", "value", "left", "answer", "worse", "note"]


def load_answers(path, since=""):
    got = {}
    if path.exists():
        for line in path.read_text().splitlines()[1:]:
            row = dict(zip(COLS, line.split("\t")))
            if row.get("worse") in ("A", "B", "=") and row["when"] >= since:
                got[(row["item"], int(row["rung"]))] = row   # newest wins
    return got


def page(item, rung, n, left):
    right = "b" if left == "a" else "a"
    sides = [(lab, rung[s]) for lab, s in (("LEFT", left), ("RIGHT", right))]
    extra = ""
    if item["kind"] == "ladder":
        extra = f"<p>Step {n + 1} of a ladder of {len(item['rungs'])}.</p>"
    cells = "".join(
        f'<div class="side"><h2>{lab}</h2><p class="desc">{html.escape(r["desc"])}</p>'
        f'<img src="{html.escape(r["svg"])}"></div>' for lab, r in sides)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{item['id']}</title><style>
body {{ font-family: Helvetica, Arial, sans-serif; margin: 1em; }}
.q {{ font-size: 1.3em; max-width: 70em; }}
.side {{ border: 1px solid #aaa; padding: .5em; margin-bottom: 1em; }}
.side img {{ width: 100%; }}
.desc {{ font-size: 1.1em; color: #a00; }}
</style></head><body>
<p class="q"><b>{item['id']}.</b> {html.escape(item['question'])}</p>{extra}
<p>Answer in the terminal: which plan is worse, LEFT or RIGHT, or are they equally bad?
The red outline marks what each version changes; each room shows its built area and the
area the brief asks for.</p>
{cells}</body></html>"""


def ask(item, n, answers_path, rng, open_browser):
    rung = item["rungs"][n]
    left = rng.choice("ab")
    out = HERE / "current.html"
    out.write_text(page(item, rung, n, left))
    if open_browser:
        webbrowser.open(out.as_uri())
    print(f"\n{item['id']}" + (f", step {n + 1}" if item["kind"] == "ladder" else "")
          + f": {item['question']}")
    print(f"  (page: {out})")
    while True:
        try:
            a = input("  Which is worse?  l = left, r = right, e = equally bad, "
                      "s = skip, q = quit > ").strip().lower()
        except EOFError:
            a = "q"
        if a in ("l", "r", "e", "s", "q"):
            break
    if a == "q":
        return "quit"
    if a == "s":
        worse = "skip"
    elif a == "e":
        worse = "="
    else:
        side = left if a == "l" else ("b" if left == "a" else "a")
        worse = side.upper()
    try:
        note = input("  Note (optional, Enter for none) > ").strip().replace("\t", " ")
    except EOFError:
        note = ""
    if not answers_path.exists():
        answers_path.write_text("\t".join(COLS) + "\n")
    with answers_path.open("a") as f:
        f.write("\t".join([datetime.datetime.now().isoformat(timespec="seconds"),
                           item["id"], str(n), "" if rung.get("value") is None else str(rung["value"]), left, a,
                           worse, note]) + "\n")
    return worse


def run_ladder(item, done, answers_path, rng, open_browser):
    """Find the first rung where B stops being the worse one."""
    lo, hi = -1, len(item["rungs"])
    while hi - lo > 1:
        mid = (lo + hi) // 2
        key = (item["id"], mid)
        worse = done[key]["worse"] if key in done else ask(item, mid, answers_path, rng,
                                                           open_browser)
        if worse == "quit":
            return "quit"
        if worse == "skip":
            return None
        if worse == "B":
            lo = mid
        else:
            hi = mid
    return hi


def switch_point(worse_list):
    """For a candidate's per-rung verdicts: the first rung where B is not worse."""
    for i, w in enumerate(worse_list):
        if w != "B":
            return i
    return len(worse_list)


def fmt(values, i):
    """A switch point as the rung value it happens at, or 'never'."""
    return values[i] if i < len(values) else "never"


def report(items, done):
    labels = list(items[0]["rungs"][0]["worse"]) if items else []
    agree = {lab: [] for lab in labels}
    print("\n== What the answers so far say")
    for item in items:
        if item["kind"] == "pair":
            row = done.get((item["id"], 0))
            if not row:
                continue
            print(f"  {item['id']}: you said {'equal' if row['worse'] == '=' else row['worse'] + ' worse'}"
                  f"  (A: {item['rungs'][0]['a']['desc']}; B: {item['rungs'][0]['b']['desc']})")
            for lab in labels:
                agree[lab].append((item["id"], item["rungs"][0]["worse"][lab] == row["worse"]))
        else:
            got = {r: done[(item["id"], r)]["worse"] for r in range(len(item["rungs"]))
                   if (item["id"], r) in done}
            if not got:
                continue
            values = [r["value"] for r in item["rungs"]]
            print(f"  {item['id']} ({item['measure']}): your answers at "
                  + ", ".join(f"{values[r]}: {w}" for r, w in sorted(got.items())))
            below = max([r for r, w in got.items() if w == "B"], default=None)
            above = min([r for r, w in got.items() if w != "B"], default=None)
            print(f"      you switch between {values[below] if below is not None else 'the start'}"
                  f" and {values[above] if above is not None else 'the end'}; the candidates switch at: "
                  + "; ".join(f"{lab} {fmt(values, switch_point([r['worse'][lab] for r in item['rungs']]))}"
                              for lab in labels))
            for lab in labels:
                theirs = [r["worse"][lab] for r in item["rungs"]]
                ok = all((theirs[r] == "B") == (w == "B") for r, w in got.items())
                agree[lab].append((item["id"], ok))
    asked = [i for i in items if any(k[0] == i["id"] for k in done)]
    print("\n  each score's verdict (A/B worse, = level; 'at x' where a ladder switches),"
          " * where it differs from yours")
    print("  " + " " * 22 + "".join(f"{i['id']:>11}" for i in asked))
    for lab in labels:
        cells = []
        for i in asked:
            if i["kind"] == "pair":
                v = i["rungs"][0]["worse"][lab]
                ok = dict(agree[lab]).get(i["id"])
            else:
                v = "at " + str(fmt([r["value"] for r in i["rungs"]],
                                    switch_point([r["worse"][lab] for r in i["rungs"]])))
                ok = dict(agree[lab]).get(i["id"])
            cells.append(f"{v + ('' if ok else '*'):>11}")
        print(f"  {lab:22s}" + "".join(cells))
    print("\n  candidate score        agrees on")
    for lab in labels:
        yes = [i for i, ok in agree[lab] if ok]
        no = [i for i, ok in agree[lab] if not ok]
        print(f"  {lab:22s} {len(yes)} of {len(agree[lab])}"
              + (f"   disagrees on {', '.join(no)}" if no else ""))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--report", action="store_true", help="only print what the answers say")
    ap.add_argument("--again", action="store_true", help="ask everything afresh")
    ap.add_argument("--no-browser", action="store_true", help="do not open pages")
    ap.add_argument("--answers", default=str(HERE / "answers.tsv"), help=argparse.SUPPRESS)
    a = ap.parse_args()
    items = [i for i in json.loads((HERE / "items.json").read_text()) if i["useful"]]
    answers_path = Path(a.answers)
    since = datetime.datetime.now().isoformat(timespec="seconds") if a.again else ""
    done = load_answers(answers_path, since)
    rng = random.Random()
    if not a.report:
        print(f"{len(items)} items. Each opens a page in your browser; answer here.")
        for item in items:
            if item["kind"] == "pair":
                if (item["id"], 0) in done:
                    continue
                w = ask(item, 0, answers_path, rng, not a.no_browser)
            else:
                w = run_ladder(item, done, answers_path, rng, not a.no_browser)
            if w == "quit":
                print("\nStopped; run again to carry on where you left off.")
                break
            done = load_answers(answers_path, since)
    report(items, load_answers(answers_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())

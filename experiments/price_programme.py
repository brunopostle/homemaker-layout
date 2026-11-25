"""Price a programme change before landing it: every design scored under the
live programme and under a draft, and what each gains or loses
(DESIGN.md §39.265; the pattern of §39.249's pricing).

A change to a programme moves the score of every design of it, so a ruling
is priced on the committed designs first: how many it touches, by how many
lines, and which lines. Scored with the search's overrides, both sides.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/price_programme.py \\
        examples/health-centre experiments/proposals/health-centre-r2a9

With no design paths it prices every committed design of the programme: its
`+orth` cold corpora and every race's finals, winners and drawings whose
directory names the programme (deduplicated by content).

--self-test: a draft identical to the live programme must move nothing, and
one with a requirement no design can meet (an adjacency to a code that is
never built) must add a line to every design.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import re
import shutil
import sys
import tempfile
from pathlib import Path

from homemaker_layout import dom, driver, geometry

REPO = Path(__file__).resolve().parents[1]
SEARCH = dict(leaf_sharing=True, collapse_insearch=True)
SHORT = {"health-centre": "health", "harbor-house": "harbor", "maple-court": "maple",
         "programme-house": "programme-house"}


def default_designs(prog: str) -> list[Path]:
    found = sorted((REPO / "examples" / prog).glob("coldstart-*+orth-*.dom"))
    res = REPO / "experiments" / "results"
    key = SHORT.get(prog, prog)
    for pat in ("*/final-*.dom", "*/winner*.dom", "*/drawings/*.dom"):
        found += sorted(p for p in res.glob(pat) if key in p.parent.as_posix().split("results/")[-1])
    seen, out = set(), []
    for p in found:
        h = hashlib.sha1(p.read_bytes()).hexdigest()
        if h not in seen:
            seen.add(h)
            out.append(p)
    return out


def family(line: str) -> str:
    f = re.sub(r"^\d+/[lr]*\s", "", line)
    f = re.sub(r"^level \d+", "level N", f)
    return f


def price(base: Path, draft: Path, designs, collapse: bool = True) -> list[dict]:
    """``collapse=False`` scores the labels as stored. With it (the search's
    default) the scorer relabels cells to the rooms they fit best, partly by
    adjacency, so a new adjacency requirement can move labels across the
    plan and cost lines that have nothing to do with it (§39.265)."""
    kw = dict(SEARCH, collapse_insearch=collapse)
    fb = driver._fitness_for(str(base), **kw)
    fd = driver._fitness_for(str(draft), **kw)
    rows = []
    for p in designs:
        out = {}
        for name, fit in (("base", fb), ("draft", fd)):
            root = dom.load(str(p))
            dom.link(root)
            geometry.clear_cache()
            out[name] = fit.score_with_fails(root)
        (sb, lb), (sd, ld) = out["base"], out["draft"]
        cb, cd = collections.Counter(lb), collections.Counter(ld)
        rows.append(dict(design=str(Path(p).resolve().relative_to(REPO)),
                         base=len(lb), draft=len(ld), ratio=sd / sb if sb else float("nan"),
                         gained=sorted((cd - cb).elements()), lost=sorted((cb - cd).elements())))
    return rows


def self_test(base: Path) -> int:
    designs = default_designs(base.name)[:6]
    with tempfile.TemporaryDirectory() as t:
        same = Path(t) / base.name
        shutil.copytree(base, same, ignore=shutil.ignore_patterns("*.dom", "*.log"))
        moved = [r for r in price(base, same, designs) if r["gained"] or r["lost"]]
        assert not moved, f"an identical draft moved {len(moved)} designs"
        # a second directory: `driver._fitness_for` is cached by path, so
        # editing `same` in place would be scored with its first scorer
        bad = Path(t) / "unmeetable" / base.name
        shutil.copytree(same, bad)
        text = (bad / "patterns.config").read_text()
        code = re.search(r"^  ([a-z]\w*):", text, re.M).group(1)
        text = re.sub(rf"(^  {code}:\n(?:    .*\n)*?    adjacency:\n)", r"\1      - zz9\n",
                      text, count=1, flags=re.M)
        text = text.replace("\nspaces:\n", "\nspaces:\n  zz9:\n    usage: none\n    name: Never built\n"
                            "    size:\n      - 4.0\n      - 1.0\n", 1)
        (bad / "patterns.config").write_text(text)
        rows = price(base, bad, designs)
        assert all(r["gained"] for r in rows), "an unmeetable requirement moved nothing"
    print(f"self-test passed on {len(designs)} designs: identical draft moves none; "
          f"an unmeetable one moves all")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("base", help="the live programme directory")
    ap.add_argument("draft", nargs="?", help="the draft programme directory")
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--no-collapse", action="store_true",
                    help="score the labels as stored (the search relabels; see price())")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    base = Path(a.base)
    if a.self_test:
        return self_test(base)
    designs = [Path(p) for p in a.designs] or default_designs(base.name)
    rows = price(base, Path(a.draft), designs, collapse=not a.no_collapse)
    touched = [r for r in rows if r["gained"] or r["lost"]]
    print("design\tbase\tdraft\tscore_x\tgained\tlost")
    for r in rows:
        print(f"{r['design']}\t{r['base']}\t{r['draft']}\t{r['ratio']:.3g}\t"
              f"{'; '.join(r['gained'])}\t{'; '.join(r['lost'])}")
    fam = collections.Counter(family(g) for r in rows for g in r["gained"])
    lost = collections.Counter(family(g) for r in rows for g in r["lost"])
    print(f"\n{len(rows)} designs; {len(touched)} touched; lines "
          f"+{sum(len(r['gained']) for r in rows)} / -{sum(len(r['lost']) for r in rows)}")
    print("gained by family:", dict(fam.most_common()))
    print("lost by family:", dict(lost.most_common()))
    races = [r for r in rows if "coldstart" not in r["design"]]
    if races:
        best = min(races, key=lambda r: r["base"])
        print(f"best race design {best['design']}: {best['base']} -> {best['draft']} fails")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

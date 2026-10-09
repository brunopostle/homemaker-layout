"""Relabel the staircases of committed designs `C` -> `E`, and prove no score moves
(`homemaker-py-y4p4.1`, DESIGN.md §39.125).

Until §39.125 a stair was INFERRED: a ground-floor `C` cell whose exact path
was a `C` cell on every storey. Now it is a cell LABELLED `E`. Every design
written before the change has its stairs spelt the old way, and under the new
scorer would have none. This is the upgrade, in three steps that are run by
two different checkouts on purpose:

    # 1. under the OLD code (main, before the merge): what each design scores
    #    and which cells the old rule read as stairs
    PYTHONPATH=<old>/src python experiments/relabel_stairs.py --survey old.json

    # 2. under the NEW code: relabel in memory, and require the same score and
    #    the same fail list, design for design (with the one new RULE of
    #    §39.125 -- a stair joins storeys -- switched off, so that relabelling
    #    is the only thing being judged); then say what that rule changes
    PYTHONPATH=<new>/src python experiments/relabel_stairs.py --verify old.json

    # 3. write the files: the `type:` scalars and nothing else, byte for byte
    PYTHONPATH=<new>/src python experiments/relabel_stairs.py --write old.json

`--self-test` is the negative control for step 2: a design relabelled one
cell short must NOT pass.
"""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("programme-house2", "programme-house", "health-centre", "harbor-house-l0",
              "harbor-house", "maple-court", "y51-sweep-10", "y51-sweep-14",
              "y51-sweep-18", "y51-sweep-22")


def designs() -> "list[Path]":
    out = subprocess.run(["git", "ls-files", "*.dom"], cwd=REPO, capture_output=True,
                         text=True, check=True).stdout.split()
    return [REPO / p for p in sorted(out)]


def programme_of(path: Path) -> "Path | None":
    if (path.parent / "patterns.config").exists():
        return path.parent
    for name in PROGRAMMES:
        if name in path.name and (REPO / "examples" / name / "patterns.config").exists():
            return REPO / "examples" / name
    # the e4r and xhw experiments were programme-house and do not say so
    if path.name.startswith(("e4r-", "xhw-")):
        return REPO / "examples" / "programme-house"
    return None


def is_v2(path: Path) -> bool:
    return any(line.startswith("format:") for line in path.read_text().splitlines()[:5])


def _load(path: Path):
    from homemaker_layout import dom, geometry
    root = dom.load(str(path), native=True) if is_v2(path) else dom.load(str(path))
    dom.link(root)
    geometry.clear_cache()
    return root


def _fitness(prog: Path):
    from homemaker_layout import fitness as F
    if prog not in _fitness.cache:
        conf, cost = F.load_config(str(prog))
        _fitness.cache[prog] = F.Fitness(conf, cost)
    return _fitness.cache[prog]


_fitness.cache = {}


def _score(root, prog: Path, stairs: "list | None" = None):
    """(score, sorted fail lines); `stairs` collects the ids of the cells the
    scorer fitted a stair to (the MERGED tree's ids)."""
    fit = _fitness(prog)
    orig = fit._stair_fit
    if stairs is not None:
        def spy(leaf, corners):
            stairs.append(leaf.id or "")
            return orig(leaf, corners)
        fit._stair_fit = spy
    try:
        s, fails = fit.score_with_fails(copy.deepcopy(root))
    finally:
        if stairs is not None:
            del fit._stair_fit
    return s, sorted(fails)


def _orth(on: bool) -> None:
    from homemaker_layout import geometry
    geometry.ORTHOGONAL_DIVISION = on
    geometry.clear_cache()


def survey(out: Path) -> int:
    rows, skipped = {}, []
    for p in designs():
        prog = programme_of(p)
        rel = str(p.relative_to(REPO))
        if prog is None:
            skipped.append(rel)
            continue
        row = {}
        for on in (False, True):
            _orth(on)
            try:
                stairs: list = []
                s, fails = _score(_load(p), prog, stairs)
                row["orth" if on else "skew"] = {"score": s, "fails": fails,
                                                 "stairs": sorted(stairs)}
            except Exception as e:           # a v2 design the quad tree cannot hold, etc.
                row["orth" if on else "skew"] = {"error": f"{type(e).__name__}: {e}"[:200]}
        rows[rel] = row
    out.write_text(json.dumps({"designs": rows, "skipped": skipped}, indent=0))
    n = sum(1 for r in rows.values() for v in r.values() if "error" not in v)
    print(f"surveyed {len(rows)} designs ({n} scores); skipped {len(skipped)} with no programme")
    return 0


def stair_paths(row: dict) -> "list[str] | None":
    """The cells to relabel, or None if the two geometries disagree."""
    sets = [tuple(v["stairs"]) for v in row.values() if "error" not in v]
    if not sets:
        return []
    return list(sets[0]) if len(set(sets)) == 1 else None


def relabel(root, paths: "list[str]") -> "list[str]":
    """Label every leaf under each path, on every storey, `E`. Returns
    complaints: a leaf there that is not `C`."""
    from homemaker_layout import dom
    bad = []
    for li, lvl in enumerate(dom.levels(root)):
        for p in paths:
            node = lvl.by_id(p) if p else lvl
            if node is None:
                bad.append(f"storey {li}: no node at {p!r}")
                continue
            stack = [node]
            while stack:
                n = stack.pop()
                if n.divided:
                    stack += [n.left, n.right]
                elif n.type == "C":
                    n.type = "E"
                else:
                    bad.append(f"storey {li} {n.id!r}: {n.type!r}, not C")
    return bad


def verify(src: Path, short: bool = False) -> int:
    from homemaker_layout import graph
    data = json.loads(src.read_text())["designs"]
    moved, ambiguous, complaints, checked, relabelled, joined = [], [], [], 0, 0, []
    for rel, row in data.items():
        paths = stair_paths(row)
        if paths is None:
            ambiguous.append(rel)
            continue
        if short and paths:
            paths = paths[:-1] if len(paths) > 1 else []     # the negative control
        prog = programme_of(REPO / rel)
        for key, on in (("skew", False), ("orth", True)):
            old = row[key]
            if "error" in old:
                continue
            _orth(on)
            root = _load(REPO / rel)
            bad = relabel(root, paths)
            if bad:
                complaints.append((rel, bad[:3]))
                break
            graph.STAIRS_JOIN_STOREYS = False
            try:
                s, fails = _score(root, prog)
            finally:
                graph.STAIRS_JOIN_STOREYS = True
            checked += 1
            if s != old["score"] or fails != old["fails"]:
                moved.append((rel, key, old["score"], s,
                              sorted(set(old["fails"]) ^ set(fails))[:4]))
            s2, fails2 = _score(root, prog)
            if fails2 != fails:
                joined.append((rel, key, len(fails), len(fails2),
                               sorted(set(fails) - set(fails2))[:4]))
        relabelled += bool(paths)
    if short:
        return len(moved)
    print(f"{checked} scores of {len(data)} designs re-taken after relabelling "
          f"({relabelled} designs have a stair to relabel)")
    print(f"  score or fail list MOVED: {len(moved)}")
    for m in moved[:12]:
        print("    ", *m)
    print(f"  the two geometries disagree about which cells are stairs: {len(ambiguous)}")
    for a in ambiguous[:12]:
        print("    ", a)
    print(f"  a cell to relabel is not C: {len(complaints)}")
    for c in complaints[:12]:
        print("    ", *c)
    print(f"\nthen, with a stair joining the storeys it serves (§39.125): "
          f"{len(joined)} scores change")
    for j in joined[:20]:
        print("    ", *j)
    return 1 if (moved or complaints) else 0


# --------------------------------------------------------------------------- #
def _type_marks(text: str, paths: "list[str]") -> "list[tuple[int, int]]":
    """(line, column) of the `type` scalar of every leaf to relabel in a v1
    file, found on the YAML node graph so that nothing else is touched."""
    import yaml

    def get(m, key):
        for k, v in m.value:
            if k.value == key:
                return v
        return None

    marks = []
    lvl = yaml.compose(text)
    while lvl is not None:
        for p in paths:
            node = lvl
            for step in p:
                node = get(node, step) if node else None
            stack = [node] if node is not None else []
            while stack:
                n = stack.pop()
                kids = [c for c in (get(n, "l"), get(n, "r")) if c is not None]
                t = get(n, "type")
                if kids:
                    stack += kids
                elif t is not None and t.value == "C":
                    marks.append((t.start_mark.line, t.start_mark.column))
        lvl = get(lvl, "above")
    return marks


def write(src: Path) -> int:
    from homemaker_layout import dom
    data = json.loads(src.read_text())["designs"]
    done = cells = 0
    for rel, row in data.items():
        paths = stair_paths(row)
        if not paths:
            continue
        p = REPO / rel
        if is_v2(p):
            root = _load(p)
            assert not relabel(root, paths), rel
            dom.dump(root, str(p), version=2)
            done += 1
            continue
        text = p.read_text()
        lines = text.split("\n")
        marks = _type_marks(text, paths)
        want = _load(p)
        assert not relabel(want, paths), rel
        for ln, col in marks:
            assert lines[ln][col] == "C", (rel, ln, lines[ln])
            lines[ln] = lines[ln][:col] + "E" + lines[ln][col + 1:]
        p.write_text("\n".join(lines))
        got = _load(p)
        a = [(n.id, n.type) for lv in dom.levels(got) for n in lv.leaves()]
        b = [(n.id, n.type) for lv in dom.levels(want) for n in lv.leaves()]
        if a != b:                           # the file must say what memory said
            p.write_text(text)
            raise AssertionError(f"{rel}: the text edit and the relabelled tree disagree")
        done += 1
        cells += len(marks)
    print(f"relabelled {done} files ({cells} `type: C` scalars in the v1 ones)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--survey", type=Path, metavar="OUT.json")
    g.add_argument("--verify", type=Path, metavar="OLD.json")
    g.add_argument("--write", type=Path, metavar="OLD.json")
    g.add_argument("--self-test", type=Path, metavar="OLD.json")
    a = ap.parse_args(argv)
    if a.survey:
        return survey(a.survey)
    if a.verify:
        return verify(a.verify)
    if a.write:
        return write(a.write)
    n = verify(a.self_test, short=True)
    print("self-test", "PASSED" if n else "FAILED",
          f"-- relabelled one stair short, {n} scores move")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())

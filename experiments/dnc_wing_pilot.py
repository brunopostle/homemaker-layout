"""Divide-and-conquer pilot (`homemaker-py-2g7.13.1.5`, DESIGN.md §39.145):
cut one wing out of a whole-building design and pose it as a building of its
own.

The question is whether decomposition loses anything. Before any search can
answer it, the cut itself has to be shown faithful: the wing AS BUILT, lifted
onto its own plot under its own brief, should fail about what it fails inside
the building. This writes the stand-alone problem and makes that check.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/dnc_wing_pilot.py \
        experiments/results/halving-harbor/winner-total.dom --wing l \
        --out experiments/results/dnc-wing

writes, under --out:

  patterns.config  the programme's brief cut to the rooms the wing holds, with
                   their counts; one staircase; the wing's storey count
  costs.config     the programme's, unchanged, where it has one
  init.dom         the bare plot: the wing's outline, one storey, open to the
                   sky -- what a cold `homemaker-evolve` starts from
  wing.dom         the wing as built, every storey

The plot's sides are labelled from what lies beyond them in the building: a
side on the plot boundary keeps that side's label (`private`, or open); an
internal side is open if more than half of it faces outdoor cells on every
storey, and `private` otherwise -- a side takes one label, so a wall partly
onto a court and partly onto rooms is approximated. An open side is also a
possible way in (`no outside public access`), which a court side is not in
the building: the pilot's first approximation, recorded rather than modelled.
"""

from __future__ import annotations

import argparse
import copy
import shutil
import sys
from collections import Counter
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from homemaker_layout import dom, geometry  # noqa: E402
from homemaker_layout.fitness import Fitness, load_config  # noqa: E402

OUTDOOR = ("O", "S")


def _side_facing(lvl: dom.Node, wing: dom.Node, edge: int) -> "tuple[float, float]":
    """(length, length onto outdoor cells) of the wing's ``edge`` on storey
    ``lvl``, from the cells outside the wing whose sides lie along it."""
    a, b = geometry.coordinate(wing, edge), geometry.coordinate(wing, (edge + 1) % 4)
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = (dx * dx + dy * dy) ** 0.5
    inside = {id(x) for x in wing.leaves()}
    total = out = 0.0
    for leaf in lvl.leaves():
        if id(leaf) in inside:
            continue
        cs = [geometry.coordinate(leaf, i) for i in range(4)]
        for i in range(4):
            p, q = cs[i], cs[(i + 1) % 4]
            # both ends on the wing's side line, within 5 cm
            off = [abs((r[0] - a[0]) * dy - (r[1] - a[1]) * dx) / L for r in (p, q)]
            if max(off) > 0.05:
                continue
            t = sorted(((r[0] - a[0]) * dx + (r[1] - a[1]) * dy) / L for r in (p, q))
            seg = max(0.0, min(t[1], L) - max(t[0], 0.0))
            total += seg
            if leaf.type in OUTDOOR:
                out += seg
    return total, out


def cut(design: Path, prog: Path, path: str):
    """The wing at ``path`` of ``design`` as (levels, perimeter, room counts,
    report lines). The design is merged as the scorer merges it first."""
    fit = Fitness(*load_config(str(prog)))
    root = dom.load(str(design))
    fit.score_with_fails(root)                # merges same-type siblings in place
    lvls = dom.levels(root)
    wings = [lvl.by_id(path) for lvl in lvls]
    if wings[0] is None or not wings[0].divided:
        raise SystemExit(f"no divided node at {path!r} on the ground storey")
    report = []
    perimeter = {}
    for e in range(4):
        bid = geometry.boundary_id(wings[0], e)
        key = "abcd"[e]
        if bid in "abcd" and bid:
            perimeter[key] = root.perimeter.get(bid) if root.perimeter else None
            report.append(f"side {key}: plot side {bid} ({perimeter[key] or 'open'})")
            continue
        shares = []
        for lvl, w in zip(lvls, wings):
            if w is None:
                continue
            total, out = _side_facing(lvl, w, e)
            shares.append(out / total if total else 0.0)
        perimeter[key] = None if min(shares) > 0.5 else "private"
        report.append(f"side {key}: internal, onto outdoor cells "
                      + "/".join(f"{s:.0%}" for s in shares)
                      + f" by storey -> {perimeter[key] or 'open'}")
    counts = Counter(lf.type for w in wings if w is not None for lf in w.leaves())
    return root, lvls, wings, perimeter, counts, report


def brief(prog: Path, counts: Counter, storeys: int) -> dict:
    conf = yaml.safe_load((prog / "patterns.config").read_text())
    spaces = {}
    for code, spec in conf["spaces"].items():
        if counts.get(code):
            spec = dict(spec)
            if counts[code] > 1 or "count" in spec:
                spec["count"] = counts[code]
            spec["adjacency"] = [a for a in spec.get("adjacency") or []
                                 if a in ("c", "o", "s") or any(k.startswith(a) for k in counts)]
            spaces[code] = spec
    conf["spaces"] = spaces
    conf["staircase_min"] = conf["staircase_max"] = 1
    conf["storey_minimum"] = conf["storey_limit"] = storeys
    return conf


def wing_tree(lvls, wings, perimeter) -> dom.Node:
    """The wing as a building: each storey's root is the wing's node in its
    own frame (corner i of the root is corner i of the wing, rotation 0)."""
    corners = [list(geometry.coordinate(wings[0], i)) for i in range(4)]
    roots = []
    for lvl, w in zip(lvls, wings):
        r = copy.deepcopy(w)
        r.rotation = 0
        r.node, r.node_file = [list(p) for p in corners], None
        r.perimeter = dict(perimeter)
        for k in ("height", "elevation", "wall_inner", "wall_outer"):
            setattr(r, k, getattr(lvl, k))
        roots.append(r)
    for lo, hi in zip(roots, roots[1:]):
        lo.above = hi
    dom.link(roots[0])
    geometry.clear_cache()
    return roots[0]


def bare_plot(wing_root: dom.Node) -> dom.Node:
    r = dom.Node(type="O", rotation=0, node=[list(p) for p in wing_root.node],
                 perimeter=dict(wing_root.perimeter))
    for k in ("height", "elevation", "wall_inner", "wall_outer"):
        setattr(r, k, getattr(wing_root, k))
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("design", type=Path)
    ap.add_argument("--programme", default="harbor-house")
    ap.add_argument("--wing", default="l", help="the wing's path on every storey")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    prog = REPO / "examples" / args.programme

    fit = Fitness(*load_config(str(prog)))
    whole = dom.load(str(args.design))
    _s, fails = fit.score_with_fails(whole)
    root, lvls, wings, perimeter, counts, report = cut(args.design, prog, args.wing)
    inside = [f for f in fails if "/" in f.split()[0]
              and f.split()[0].split("/")[1].startswith(args.wing)]
    print(f"{args.design.name}: {len(fails)} fails in the building, "
          f"{len(inside)} of them in wing {args.wing!r}:")
    for f in inside:
        print(f"    {f}")
    print(f"    (and building-wide: {[f for f in fails if '/' not in f.split()[0]]})")
    for line in report:
        print("  " + line)
    print("  rooms: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))

    args.out.mkdir(parents=True, exist_ok=True)
    conf = brief(prog, counts, len(lvls))
    (args.out / "patterns.config").write_text(
        f"# Wing {args.wing!r} of {args.design.name}, cut by experiments/dnc_wing_pilot.py\n"
        + yaml.safe_dump(conf, sort_keys=False))
    for name in ("costs.config",):            # where the programme has one
        if (prog / name).is_file():
            shutil.copyfile(prog / name, args.out / name)
    wing = wing_tree(lvls, wings, perimeter)
    dom.dump(wing, str(args.out / "wing.dom"))
    dom.dump(bare_plot(wing), str(args.out / "init.dom"))

    wfit = Fitness(*load_config(str(args.out)))
    ws, wfails = wfit.score_with_fails(dom.load(str(args.out / "wing.dom")))
    print(f"\nthe wing as built, on its own plot under its own brief: "
          f"{len(wfails)} fails, score {ws:.4g}")
    for f in wfails:
        print(f"    {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

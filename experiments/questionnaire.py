"""The ordering questionnaire, worked through (`homemaker-py-5fje.2`, DESIGN.md §39.201-§39.202).

Each item is a pair of edits, A and B, to one real design. For each pair this
prints what every candidate score says (A worse, B worse, or level within
1%), lists every cell either edit moved, and draws both variants with
`plan_svg.py`. The owner's answer to an item then keeps the candidates that
agree with it and drops the rest.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/questionnaire.py \\
        --outdir experiments/results/questionnaire

Edits are made by moving ONE cut: the room's parent node is re-divided until
the room has the asked area, so the area goes to (or comes from) its sibling,
and the cells-moved list says what else changed. "Left out" retypes the room's
cell as the sibling's type.
"""
import argparse
import copy
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diag_aggregation import arms  # noqa: E402
from successive_halving import REPO, load_config  # noqa: E402
from homemaker_layout import dom, geometry, programme  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402

BASE = "experiments/results/halving-maple-clean/final-clean-9.dom"
PROG = "maple-court"
LOUNGE = (0, "ll")                 # lr1, 69 m2 of 80; sibling a 149 m2 yard
TOILET = (0, "rlrllrrrlllr")       # t, 7.0 m2 of 6; sibling a corridor

# (name, question, edit A, edit B); an edit is (cell, fraction of target) or
# (cell, "omit")
ITEMS = [
    ("O1", "the lounge at 2% of its target, or left out?",
     (LOUNGE, 0.02), (LOUNGE, "omit")),
    ("O2", "a toilet at 50% of its target, or the lounge at 50%?",
     (TOILET, 0.5), (LOUNGE, 0.5)),
    ("O3", "the lounge at 80% of its target, or a toilet at 50%?",
     (LOUNGE, 0.8), (TOILET, 0.5)),
]

# (label, arm, phi)
CANDIDATES = [("A0 today", "A0", 1e-3),
              ("P1 equal votes", "P1", 1e-3),
              ("P2 target-weighted", "P2", 1e-3),
              ("P1 unfloored", "P1", 1e-20),
              ("P2 unfloored", "P2", 1e-20)]


def find(root, cell):
    level, path = cell
    for leaf in dom.levels(root)[level].leaves():
        if leaf.id == path:
            return leaf
    raise KeyError(cell)


def edit(base, reqs, cell, how):
    root = copy.deepcopy(base)
    dom.link(root)
    geometry.clear_cache()
    leaf = find(root, cell)
    parent = leaf.parent
    sib = parent.right if parent.left is leaf else parent.left
    if how == "omit":
        leaf.type = sib.type
        return root
    goal = how * reqs[leaf.type].size

    def area_at(x):
        parent.division = [x, x]
        geometry.clear_cache()      # areas are memoised per tree
        return geometry.area(leaf)
    lo, hi = 0.001, 0.999
    rising = area_at(hi) > area_at(lo)
    for _ in range(60):
        mid = (lo + hi) / 2
        if (area_at(mid) < goal) == rising:
            lo = mid
        else:
            hi = mid
    area_at((lo + hi) / 2)
    geometry.clear_cache()
    return root


def cell_areas(root):
    geometry.clear_cache()
    return {(i, leaf.id): (leaf.type, geometry.area(leaf))
            for i, lvl in enumerate(dom.levels(root)) for leaf in lvl.leaves()}


def moved(base, root):
    a, b = cell_areas(base), cell_areas(root)
    out = []
    for k in sorted(set(a) | set(b)):
        ta, aa = a.get(k, ("-", 0.0))
        tb, ab = b.get(k, ("-", 0.0))
        if ta != tb or abs(aa - ab) > 0.5:
            out.append(f"{k[0]}/{k[1]} {ta} {aa:.1f} -> {tb} {ab:.1f}")
    return out


def describe(how, reqs, base, cell):
    t = find(base, cell).type
    return f"{t} left out" if how == "omit" else f"{t} at {how:.0%} ({how * reqs[t].size:.1f} m2)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--outdir")
    a = ap.parse_args()
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    d = REPO / "examples" / PROG
    fit = Fitness(*load_config(d))
    reqs = programme.load_programme_dir(str(d))
    base = dom.load(str(REPO / BASE))
    dom.link(base)
    r_base = arms(fit, reqs, base, 1e-3)
    print(f"base {BASE}: fails {r_base['fails']}")
    out = Path(a.outdir) if a.outdir else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    for name, question, ea, eb in ITEMS:
        print(f"\n== {name}: {question}")
        variants = {}
        for side, (cell, how) in (("A", ea), ("B", eb)):
            root = edit(base, reqs, cell, how)
            variants[side] = root
            r = arms(fit, reqs, root, 1e-3)
            print(f"  {side}: {describe(how, reqs, base, cell)}; fails {r['fails']}")
            for f in sorted(set(r["fail_lines"]) - set(r_base["fail_lines"])):
                print(f"       + {f}")
            for f in sorted(set(r_base["fail_lines"]) - set(r["fail_lines"])):
                print(f"       - {f}")
            for m in moved(base, root):
                print(f"       moved {m}")
            if out:
                p = out / f"{name}-{side}.dom"
                p.write_text(dom.dumps(root))
                subprocess.run([sys.executable, str(REPO / "experiments/plan_svg.py"),
                                "--programme", str(d), str(p), "-o", str(p.with_suffix(".svg")),
                                "--title", f"{name} {side}: {describe(how, reqs, base, cell)}"],
                               check=True, capture_output=True)
        print(f"  {'candidate':20s} {'A':>10s} {'B':>10s}  verdict")
        for label, arm, phi in CANDIDATES:
            sa = arms(fit, reqs, variants["A"], phi)[arm]
            sb = arms(fit, reqs, variants["B"], phi)[arm]
            if abs(sa - sb) <= 0.01 * max(abs(sa), abs(sb)):
                v = "level"
            else:
                v = f"{'A' if sa < sb else 'B'} worse, x{max(sa, sb) / min(sa, sb):.3g}"
            print(f"  {label:20s} {sa:10.4g} {sb:10.4g}  {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

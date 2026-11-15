"""Price a roof cost, a corner cost and the enclosed-outdoor fail over a corpus
before proposing them (`homemaker-py-5fje.20`, `5fje.21`, DESIGN.md §39.229).

The counterfactual pattern of §39.72, by exact arithmetic rather than a
monkeypatch (§39.80): under A0 a score is ``value * 0.5**n / cost``, so a
cost term ``x`` added to ``cost`` and ``k`` new fail lines give

    score' = score * cost / (cost + x) * 0.5**k

with ``cost`` the scorer's own total, captured as `report_card.capture` does.
P aggregations have no cost term (§39.200), so only the fail moves them.

The terms, in the scorer's units (an exterior wall is 100 per m2 of wall):

  roof_m2       indoor area of each storey not under indoor area of the
                storey above, the top storey's whole. A covered outdoor cell
                is already priced with its roof (`outside_covered*`)
  ground_m2     indoor area of the ground storey: the slab and substructure,
                which the flat `inside` rate charges on every storey alike
  corners       corners of each storey's indoor outline, outer ring and
                courts, seams under 5 cm dropped (`report_card._corners`),
                each weighted by its storey's height: a corner is charged as
                ``corner_m`` metres of extra exterior wall, top to bottom
  enclosed      ground-storey outdoor cells with indoor above, no outdoor
                neighbour and no open plot side (a party or private side is
                a wall): the owner's carriage arch, "not an outside space".
                Above the ground a covered outdoor cell already fails
                (`covered outside above ground`)

Since §39.231 the scorer prices these itself (`Fitness.envelope_cost`) and
the outline is its `indoor_outline`; this tool is kept as the record of how
the rates were chosen, and its numbers before that landed came from GEOS's
plain union, which lost area on 3 of 874 storeys.

Arms are (roof rate, ground rate, corner_m). For each, per programme: the
median extra cost, Kendall's tau between the old and new A0 order, and
whether the best design changes. Single- against multi-storey designs are
reported apart, since making two storeys cheaper than one is the point.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_5fje20_roof_corners.py \\
        [--tsv out.tsv] DESIGN.dom ...
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_5fje20_roof_corners.py --self-test
"""
import argparse
import statistics
import sys
from pathlib import Path

from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_card as rc  # noqa: E402
from homemaker_layout import dom, geometry  # noqa: E402
from homemaker_layout.fitness import _height, _perimeter, indoor_outline  # noqa: E402

ARMS = [  # (label, roof per m2, ground slab per m2, corner as m of exterior wall)
    ("roof100", 100.0, 0.0, 0.0),
    ("roof100+c1", 100.0, 0.0, 1.0),
    ("roof100+c2", 100.0, 0.0, 2.0),
    ("roof100+slab75+c1", 100.0, 75.0, 1.0),
    ("roof150+c1", 150.0, 0.0, 1.0),
]


def enclosed_cells(level_root, G):
    out = []
    for leaf in level_root.leaves():
        if not dom.is_outside(leaf) or not dom.is_usable(leaf) or not dom.is_covered(leaf):
            continue
        if any(dom.is_outside(nb) for nb in G.neighbors(leaf)):
            continue
        per = _perimeter(leaf)
        if any(geometry.is_external(b := geometry.boundary_id(leaf, e))
               and (per.get(b) or "").lower() not in ("private", "fortified")
               for e in range(geometry.n_edges(leaf))):
            continue
        out.append(leaf)
    return out


def terms(storeys):
    """roof_m2, ground_m2, corner metres (corners x storey height), enclosed."""
    polys = []
    heights = []
    for lvl, _, _ in storeys:
        polys.append(indoor_outline(lvl))
        heights.append(_height(lvl))
    roof = sum(p.difference(polys[i + 1] if i + 1 < len(polys) else rc.Polygon()).area
               for i, p in enumerate(polys))
    corner_m = 0.0
    corners = 0
    for p, h in zip(polys, heights):
        n = sum(rc._corners(r) for q in rc._polys(p) for r in [q.exterior, *q.interiors])
        corners += n
        corner_m += n * h
    enclosed = len(enclosed_cells(storeys[0][0], storeys[0][1])) if storeys else 0
    return dict(roof_m2=roof, ground_m2=polys[0].area if polys else 0.0,
                corners=corners, corner_m=corner_m, enclosed=enclosed)


def measure(progs, path, edit=None):
    p = progs(path)
    if p is None:
        return None
    prog, fit, _ = p
    root = dom.load(str(path))
    dom.link(root)
    if edit is not None:
        edit(root)
        dom.link(root)
    geometry.clear_cache()
    score, fails = fit.score_with_fails(root)
    root = dom.load(str(path))
    dom.link(root)
    if edit is not None:
        edit(root)
        dom.link(root)
    geometry.clear_cache()
    storeys, cost = rc.capture(fit, root)
    t = terms(storeys)
    wall = fit.cost("exterior_wall")
    row = dict(programme=prog, design=str(path), storeys=len(storeys), score=score,
               fails=len(fails), cost=cost, **t)
    for label, roof, slab, cm in ARMS:
        x = roof * t["roof_m2"] + slab * t["ground_m2"] + wall * cm * t["corner_m"]
        row[f"extra_{label}"] = x / cost
        # the scorer already fails an enclosed cell (§39.231), so the
        # factor is not applied twice
        row[f"score_{label}"] = score * cost / (cost + x)
    return row


def kendall(a, b):
    n = len(a)
    s = 0
    pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            x = (a[i] > a[j]) - (a[i] < a[j])
            y = (b[i] > b[j]) - (b[i] < b[j])
            if x and y:
                s += x * y
                pairs += 1
    return s / pairs if pairs else float("nan")


def summarise(rows):
    progs = sorted({r["programme"] for r in rows})
    print(f"\n{len(rows)} designs; enclosed outdoor cells (the new fail) in "
          f"{sum(r['enclosed'] > 0 for r in rows)}: "
          + ", ".join(f"{Path(r['design']).name} x{r['enclosed']}" for r in rows if r["enclosed"]))
    print("\nper programme: storeys seen; median roof m2 per m2 of ground floor; median corners")
    for prog in progs:
        rs = [r for r in rows if r["programme"] == prog]
        print(f"  {prog:16s} storeys {sorted({r['storeys'] for r in rs})}  "
              f"roof/ground {statistics.median(r['roof_m2'] / r['ground_m2'] for r in rs):.2f}  "
              f"corners {statistics.median(r['corners'] for r in rs):.0f}")
    for label, *_ in ARMS:
        print(f"\n== {label}")
        for prog in progs:
            rs = [r for r in rows if r["programme"] == prog]
            old = [r["score"] for r in rs]
            new = [r[f"score_{label}"] for r in rs]
            best_old = max(range(len(rs)), key=lambda i: old[i])
            best_new = max(range(len(rs)), key=lambda i: new[i])
            ex = [r[f"extra_{label}"] for r in rs]
            print(f"  {prog:16s} extra cost median {100 * statistics.median(ex):5.1f}% "
                  f"(range {100 * min(ex):.1f}-{100 * max(ex):.1f}%)  tau {kendall(old, new):.3f}  "
                  f"best {'same' if best_old == best_new else 'CHANGES'}")


# The control: the term each edit is about must move, by sign
def _top_room_over_yard(root):
    rc.yard_covered(root)


def _ground_cover(root):
    """Turn the largest open ground yard cell into covered outdoor space with
    no outdoor neighbour: build a room over it and wall it in by retyping
    every outdoor ground neighbour as indoor."""
    cell = rc._open_yard_cells(root)[0]
    lvls = dom.levels(root)
    c = geometry.centroid(cell)
    from shapely.geometry import Point
    for lvl in lvls[1:]:
        for n in lvl.leaves():
            if rc.outline(n).contains(Point(c)):
                n.type = "r"
    G = geometry.leaf_graph(lvls[0], 0.0)
    for nb in list(G.neighbors(cell)):
        if dom.is_outside(nb):
            nb.type = "r"


CONTROLS = [
    ("a top-storey room over the largest yard cell", _top_room_over_yard,
     {"roof_m2": "+", "enclosed": 0}),
    ("that cell covered on every storey and walled in", _ground_cover,
     {"enclosed": "+"}),
]


def self_test(progs):
    ok = True
    base = measure(progs, rc.CLEAN9)
    for what, edit, want in CONTROLS:
        e = measure(progs, rc.CLEAN9, edit)
        print(f"\n{what}")
        for c, need in want.items():
            d = e[c] - base[c]
            good = d > 0 if need == "+" else d < 0 if need == "-" else d == need
            ok &= good
            print(f"  {'ok ' if good else 'BAD'} {c}: {rc.fmt(base[c])} -> {rc.fmt(e[c])}")
        print(f"      corners {base['corners']} -> {e['corners']}")
    # corners on a known shape: a rectangle with a seam has 4, an L has 6
    sq = unary_union([rc._rect(0, 0, 5, 10), rc._rect(5, 0, 10, 10)]).buffer(1e-6).buffer(-1e-6)
    ell = rc._rect(0, 0, 10, 10).difference(rc._rect(4, 4, 10, 10))
    for what, poly, want in (("rectangle, seamed", sq, 4), ("L", ell, 6)):
        got = rc._corners(poly.exterior)
        ok &= got == want
        print(f"  {'ok ' if got == want else 'BAD'} corners of {what}: {got} (want {want})")
    print("negative control:", "PASS" if ok else "FAIL")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--tsv")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    # price against the objective before §39.231: the scorer now charges these
    # terms itself, so they are zeroed here and added by arithmetic
    from homemaker_layout import fitness
    for k in ("roof", "slab", "corner"):
        fitness.COST_DEFAULTS[k] = 0.0
    progs = rc.Programmes()
    if a.self_test:
        return 0 if self_test(progs) else 1
    rows = []
    for path in a.designs:
        r = measure(progs, path)
        if r is None:
            print(f"# skipped, no programme in path: {path}", file=sys.stderr)
            continue
        rows.append(r)
        print(f"{Path(path).name}: storeys {r['storeys']} fails {r['fails']} roof {r['roof_m2']:.0f} "
              f"corners {r['corners']} enclosed {r['enclosed']}", file=sys.stderr, flush=True)
    if a.tsv and rows:
        cols = list(rows[0])
        Path(a.tsv).write_text("\t".join(cols) + "\n" + "".join(
            "\t".join(rc.fmt(r[c]) for c in cols) + "\n" for r in rows))
    summarise(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())

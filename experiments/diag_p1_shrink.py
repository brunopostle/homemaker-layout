"""Why does tuning under P1 shrink rooms below their brief? (`homemaker-py-5fje.9`,
DESIGN.md §39.208, §39.212)

Phase 1 tuned each design's walls, topology fixed, under A0 and under P1
(`experiments/phase1_tune.py`). Under P1, room area fell on 35 of 38 designs
and shortfall rose on 30. The size factor is a symmetric gaussian on the
target, so a room shrinking below its brief loses size factor, and P1, which
is a geomean of each required room's product of factors, must be buying it
back somewhere. This reads where.

For each design, the twin tuned under ARM is compared with a BASE (the
design as found, or its A0 twin). The same topology means the same cell ids,
so each room that votes in P1 (the best ``count`` cells of a code) is
compared cell for cell. Per factor, the change in log(max(phi, factor)),
summed over a design's voting rooms, is P1's ledger: positive is what the
arm's walls gained, negative what they paid. Adjacency misses and the
building factor are reported beside it.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_p1_shrink.py
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_p1_shrink.py --base A0 --arm P1u
"""
import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
OUT = HERE / "results" / "phase1"


def voters(fit, reqs, path, phi):
    """{(level, id): (code, area, {factor: value})} for the cells that vote
    in P1, plus the design's building factor and building-level fail count."""
    from diag_aggregation import arms, capture
    from homemaker_layout import dom, geometry
    root = dom.load(str(path))
    dom.link(root)
    geometry.clear_cache()
    score, fails, leaves, bf, value, cost = capture(fit, root)
    rooms = {c: r for c, r in reqs.items() if not dom.is_generic(c)}
    by_code = defaultdict(list)
    for le in leaves:
        if le.type in rooms:
            s = math.prod(max(phi, v) for v in le.factors.values())
            by_code[le.type].append((s, le))
    out = {}
    for code, cells in by_code.items():
        for _, le in sorted(cells, key=lambda t: -t[0])[: rooms[code].count]:
            out[le.level, le.id] = (code, le.area, dict(le.factors))
    root = dom.load(str(path))
    dom.link(root)
    geometry.clear_cache()
    a = arms(fit, reqs, root, phi)
    return out, bf, a["n_bld"], a["P1"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--arm", default="P1")
    ap.add_argument("--base", default="found", help="found, or an arm (A0)")
    ap.add_argument("--phi", type=float, default=1e-3)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--per-design", action="store_true")
    a = ap.parse_args()
    import phase1_tune
    import report_card as rc
    from homemaker_layout import geometry
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    out = Path(a.out)
    run = json.loads((out / "run.json").read_text())
    progs = rc.Programmes()

    ledger = defaultdict(list)        # factor -> per-design summed dlog
    shrunk_by = defaultdict(list)     # factor -> dlog over rooms that shrank below target
    rooms_shrunk = rooms_total = 0
    rows = []
    for design in run["designs"]:
        prog, fit, reqs = progs(design)
        base = rc.REPO / design if a.base == "found" else out / phase1_tune.name(design, a.base)
        twin = out / phase1_tune.name(design, a.arm)
        if not (base.exists() and twin.exists()):
            continue
        vb, bfb, nb, pb = voters(fit, reqs, base, a.phi)
        vt, bft, nt, pt = voters(fit, reqs, twin, a.phi)
        per = defaultdict(float)
        for key in set(vb) & set(vt):
            code, area_b, fb = vb[key]
            _, area_t, ft = vt[key]
            target = reqs[code].size or 0
            rooms_total += 1
            below = target and area_t < area_b and area_t < target
            rooms_shrunk += bool(below)
            for f in set(fb) | set(ft):
                d = math.log(max(a.phi, ft.get(f, 1.0))) - math.log(max(a.phi, fb.get(f, 1.0)))
                per[f] += d
                if below:
                    shrunk_by[f].append(d)
        per["building factor"] = math.log(bft) - math.log(bfb)
        per["building fails"] = (nt - nb) * math.log(0.5)
        for f, d in per.items():
            ledger[f].append(d)
        rows.append((design, prog, pt / pb if pb else float("nan"), dict(per)))

    n = len(rows)
    print(f"== {a.arm} twin against {a.base}, {n} designs: P1's ledger, change in log factor "
          "summed over each design's voting rooms")
    print(f"  {'factor':16s} {'median':>8s} {'mean':>8s} {'gained':>7s} {'paid':>5s}")
    for f, ds in sorted(ledger.items(), key=lambda kv: -statistics.mean(kv[1])):
        ds = ds + [0.0] * (n - len(ds))
        print(f"  {f:16s} {statistics.median(ds):8.3f} {statistics.mean(ds):8.3f} "
              f"{sum(d > 1e-9 for d in ds):7d} {sum(d < -1e-9 for d in ds):5d}")
    print(f"\n  rooms that shrank below their target: {rooms_shrunk} of {rooms_total} voting rooms."
          " Their own factors, change in log (sum over those rooms):")
    for f, ds in sorted(shrunk_by.items(), key=lambda kv: -sum(kv[1])):
        print(f"    {f:14s} sum {sum(ds):8.2f}  improved {sum(d > 1e-9 for d in ds):4d}"
              f"  worsened {sum(d < -1e-9 for d in ds):4d}")
    if a.per_design:
        for design, prog, ratio, per in rows:
            print(f"  {prog:15s} P1 x{ratio:6.3f}  " + "  ".join(
                f"{f[:5]} {d:+.2f}" for f, d in sorted(per.items()) if abs(d) > 1e-6)
                  + f"  {design}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

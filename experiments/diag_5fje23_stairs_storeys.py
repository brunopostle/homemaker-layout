"""Price the owner's two rulings of §39.237 over committed designs before they
land (`homemaker-py-5fje.23`): a stair whose fit is over ``--long`` (its
length against what its flight needs) fails `stair too long`, and a storey's
circulation must be one piece WITHOUT the stairs as links
(`graph.STAIRS_JOIN_STOREYS` off).

Each design is scored with the scorer as it stands and with the joining switch
off; the long-stair fail is counted from the stair fits the scorer itself
chose (a spy on `Fitness._stair_fit`), so it is exact arithmetic on the fail
count (§39.80). Prints, per design: fails before, the `not connected` lines
the switch adds, the stairs over the limit, and whether a design that had no
`not connected` gains one.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_5fje23_stairs_storeys.py \\
        [--long 1.5] DESIGN.dom ...
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_5fje23_stairs_storeys.py --self-test
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_card as rc  # noqa: E402
from homemaker_layout import dom, geometry, graph  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
WINNER = REPO / "experiments/results/halving-health-swap/winner.dom"


def measure(progs, path, long_fit):
    p = progs(path)
    if p is None:
        return None
    _prog, fit, _ = p
    fits = []
    orig = fit._stair_fit

    def spy(leaf, corners):
        f = orig(leaf, corners)
        fits.append((leaf.id, f))
        return f

    out = {}
    for join in (True, False):
        graph.STAIRS_JOIN_STOREYS = join
        fits.clear()
        fit._stair_fit = spy
        root = dom.load(str(path))
        dom.link(root)
        geometry.clear_cache()
        try:
            score, fails = fit.score_with_fails(root)
        finally:
            fit._stair_fit = orig
            graph.STAIRS_JOIN_STOREYS = True
        out[join] = (score, list(fails), dict(fits))
    n_storeys = len(dom.levels(dom.load(str(path))))
    base = out[True][1]
    nc0 = sum("not connected" in f for f in base)
    nc1 = sum("not connected" in f for f in out[False][1])
    # a stair is scored once per storey it stands on; count each foot once
    long_ = sorted({i for i, f in out[True][2].items() if f > long_fit})
    return dict(design=str(path), storeys=n_storeys, fails=len(base), nc_join=nc0,
                nc_alone=nc1, long=len(long_), long_ids=long_,
                fits={i: round(f, 2) for i, f in out[True][2].items()})


def self_test(progs) -> bool:
    """The §39.236 winner is the case both rulings are about: its ground
    floor joins only through the upstairs, and its south stair is 2.01."""
    r = measure(progs, WINNER, 1.5)
    ok = r["nc_join"] == 0 and r["nc_alone"] > 0 and r["long"] >= 1
    print(f"winner: not connected {r['nc_join']} -> {r['nc_alone']} without the stairs; "
          f"stairs over 1.5: {r['long_ids']} (fits {r['fits']})")
    # control: at a limit above every fit, no stair is long
    r2 = measure(progs, WINNER, 9.0)
    ok &= r2["long"] == 0
    print("negative control:", "PASS" if ok else "FAIL")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--long", type=float, default=1.5)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    progs = rc.Programmes()
    if a.self_test:
        return 0 if self_test(progs) else 1
    rows = []
    for path in a.designs:
        r = measure(progs, path, a.long)
        if r is None:
            print(f"# skipped, no programme in path: {path}", file=sys.stderr)
            continue
        rows.append(r)
        print(f"{path}\tstoreys {r['storeys']}\tfails {r['fails']}\tnot connected "
              f"{r['nc_join']} -> {r['nc_alone']}\tlong stairs {r['long']} {r['fits']}", flush=True)
    multi = [r for r in rows if r["storeys"] > 1]
    print(f"\n{len(rows)} designs, {len(multi)} multi-storey")
    print(f"  gain a `not connected` without the stairs: "
          f"{sum(r['nc_alone'] > r['nc_join'] for r in multi)} "
          f"(+{sum(r['nc_alone'] - r['nc_join'] for r in multi)} fail lines)")
    print(f"  have a stair over {a.long}: {sum(r['long'] > 0 for r in multi)} "
          f"(+{sum(r['long'] for r in multi)} fail lines)")
    print(f"  untouched by both: "
          f"{sum(r['nc_alone'] == r['nc_join'] and r['long'] == 0 for r in multi)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

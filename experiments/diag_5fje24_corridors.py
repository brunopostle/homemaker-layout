"""Price the owner's corridor rulings of §39.241 over committed designs
(`homemaker-py-5fje.24`, `.25`, `.26`): how many `corridor too wide`,
`superfluous circulation` and `double-loaded corridor` fails each design now
carries. Each only appends fail lines, so the count is the exact change in
`n_fails` (§39.80); the score changes by 0.5 per line.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_5fje24_corridors.py DESIGN.dom ...
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_5fje24_corridors.py --self-test
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report_card as rc  # noqa: E402
from homemaker_layout import dom, geometry  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
KINDS = ("corridor too wide", "superfluous circulation", "double-loaded corridor")
WINNER = REPO / "experiments/results/halving-health-rulings/winner.dom"
SWAP = REPO / "experiments/results/halving-health-swap/winner.dom"


def measure(progs, path):
    p = progs(path)
    if p is None:
        return None
    prog, fit, _ = p
    root = dom.load(str(path))
    dom.link(root)
    geometry.clear_cache()
    _, fails = fit.score_with_fails(root)
    c = Counter(k for f in fails for k in KINDS if f.endswith(k))
    return prog, len(fails), c, [f for f in fails if any(f.endswith(k) for k in KINDS)]


def self_test(progs) -> bool:
    """The cells the owner pointed at fire; with the rules off nothing does."""
    _, _, c, lines = measure(progs, WINNER)
    ok = "0/lrrlrr superfluous circulation" in lines and c["double-loaded corridor"] == 1
    _, _, c2, lines2 = measure(progs, SWAP)
    ok &= "1/rlrr superfluous circulation" in lines2
    print("winner:", lines, "\nswap winner:", lines2)
    _, fit, _ = progs(WINNER)
    saved = dict(fit._conf)
    fit._conf.update(width_circulation_max=False, superfluous_circulation=False)
    dl, fit._double_loaded_fails = fit._double_loaded_fails, 0
    try:
        _, _, c3, _ = measure(progs, WINNER)
        ok &= not c3
    finally:
        fit._conf.clear(); fit._conf.update(saved); fit._double_loaded_fails = dl
    print("negative control:", "PASS" if ok else "FAIL")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("designs", nargs="*")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    progs = rc.Programmes()
    if a.self_test:
        return 0 if self_test(progs) else 1
    by = {}
    for path in a.designs:
        r = measure(progs, path)
        if r is None:
            continue
        prog, n, c, lines = r
        print(f"{path}\tfails {n}\t" + "\t".join(f"{k} {c[k]}" for k in KINDS), flush=True)
        t = by.setdefault(prog, [0, Counter(), Counter()])
        t[0] += 1
        t[1].update(c)
        t[2].update({k: 1 for k in c})
    print("\nprogramme\tdesigns\t" + "\t".join(f"{k} (designs/lines)" for k in KINDS))
    for prog, (n, lines, designs) in sorted(by.items()):
        print(f"{prog}\t{n}\t" + "\t".join(f"{designs[k]}/{lines[k]}" for k in KINDS))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Programme rooms built far ABOVE their target area, and what a rule
against them would cost (`homemaker-py-s36o`, DESIGN.md §39.258).

The mirror of `diag_shrunk_rooms.py` (§39.199). `quality_size` is a plain
gaussian, so a room over its target is one `size` line however far over it
is: harbor-house's §39.257 winner fills a 125.6 m2 strip with a 25 m2 plant
room and builds an 18 m2 store at the same size above it, one line each.
The swollen room's VALUE is already ~0 (its size factor is ~1e-30) and its
COST is paid in full, so the only thing a rule can add is fail lines.

That makes pricing exact arithmetic, no monkeypatch: a rule that adds k
lines multiplies the score by 0.5**k. `excess internal area` (`area_cap`) is
the building-level relative of this rule; it is reported beside each design
because it is the first place one would expect the swelling to be caught.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_oversized_rooms.py
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_oversized_rooms.py --rooms
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_oversized_rooms.py PATH.dom ...
    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_oversized_rooms.py --self-test

With no paths it prices the default design set: every race's final-*.dom and
winner*.dom and its drawings/*.dom, deduplicated by content, plus every
`+orth` cold-start corpus. The programme is read from the path.
"""
import argparse
import copy
import itertools
import hashlib
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from successive_halving import REPO, load_config  # noqa: E402
from homemaker_layout import dom, geometry, programme  # noqa: E402
from homemaker_layout import graph as graph_mod  # noqa: E402
from homemaker_layout.fitness import FAIL_THRESHOLD, Fitness  # noqa: E402

KEYS = {"maple": "maple-court", "harbor": "harbor-house",
        "health": "health-centre", "programme-house": "programme-house",
        "split-stair": "maple-court", "join-clean9": "maple-court"}

SERVICE = ("utility", "none")

# name -> (threshold over target, usages it applies to or None for every room,
#          graded: one line per doubling instead of one line)
RULES = {
    "svc>1.5": (1.5, SERVICE, False),
    "svc>2": (2.0, SERVICE, False),
    "svc>3": (3.0, SERVICE, False),
    "all>1.5": (1.5, None, False),
    "all>2": (2.0, None, False),
    "all>3": (3.0, None, False),
    "all-log2": (2.0, None, True),
}


# Option B: the building-level cap (`area_cap`, owner's "no more than 20%",
# §39.58) with a narrower one-sided gaussian. sigma is a fraction of the cap;
# 0.15 is today's, which fails only above 1.59x the programme.
CAP_SIGMAS = (0.10, 0.05)


def cap_lines(margin: float | None, sigma: float) -> float:
    """Line-equivalents the cap costs at `sigma` beyond what it costs today:
    -log2 of (factor ratio x 0.5 per newly crossed FAIL_THRESHOLD)."""
    if margin is None or margin <= 1:
        return 0.0
    def cost(s):
        f = math.exp(-((margin - 1) / s) ** 2 / 2)
        return -math.log2(f) + (1 if f < FAIL_THRESHOLD else 0)
    return cost(sigma) - cost(0.15)


def default_paths() -> list[Path]:
    res = REPO / "experiments" / "results"
    found = []
    for pat in ("*/final-*.dom", "*/winner*.dom", "*/drawings/*.dom"):
        found += sorted(res.glob(pat))
    found += sorted((REPO / "examples").glob("*/coldstart-*+orth-*.dom"))
    seen, out = set(), []
    for p in found:
        h = hashlib.sha1(p.read_bytes()).hexdigest()
        if h not in seen:
            seen.add(h)
            out.append(p)
    return out


def effective_target(fit: Fitness, reqs: dict, leaf) -> float | None:
    """The area `quality_size` centres its gaussian on: k x target for a
    shared leaf, the sum of both targets for a fused one."""
    r = reqs.get(leaf.type)
    if r is None or not r.size:
        return None
    target = r.size
    k = graph_mod.leaf_share(leaf, fit._max_share) if fit._leaf_sharing else 1
    co = None if k > 1 else fit._leaf_co_type(leaf)
    if k > 1:
        return target * k
    if co and reqs.get(co) is not None:
        return target + reqs[co].size
    return target


def lines_added(ratio: float, usage: str, rule) -> int:
    thr, usages, graded = rule
    if usages is not None and usage not in usages:
        return 0
    if ratio <= thr:
        return 0
    return int(math.floor(math.log2(ratio))) if graded else 1


def survey(fit, reqs, root):
    """[(storey/id, code, usage, area, target, ratio, has size fail)], fails,
    score, and the area_cap margin (internal / allowed)."""
    score, fails = fit.score_with_fails(root)
    sized = {f.split()[0] for f in fails if f.endswith(" size")}
    rows = []
    for i, lvl in enumerate(dom.levels(root)):
        for leaf in lvl.leaves():
            t = effective_target(fit, reqs, leaf)
            if t is None or dom.is_generic(leaf.type or ""):
                continue
            a = geometry.area(leaf)
            rows.append((f"{i}/{leaf.id}", leaf.type, reqs[leaf.type].usage, a, t,
                         a / t, f"{i}/{leaf.id}" in sized))
    cap = fit.conf("area_cap")
    margin = None
    if cap:
        room = sum(r.size * r.count for r in reqs.values()
                   if not dom.is_generic(r.code) and r.size > 0)
        margin = fit._area_internal(root) / (room * cap)
    return rows, fails, score, margin


FILLERS = ("O", "C")


def trim(fit, root, storey: int, path: str, target: float):
    """The fix the search would have to find: cut the room's cell so the room
    keeps its target area, the remainder filled with outside space or a
    corridor. A cut below is inherited by the cell at the same path on every
    storey above, so that cell is cut too, keeping its own type on the room's
    side. Returns the best (score, fails, description) over orientation, which
    side the room keeps, a small ratio neighbourhood and the fillers, or None
    when the cut cannot be made without moving a wall above (a cell above at
    the same path that is already divided would lose its own cut)."""
    lvls = dom.levels(root)
    leaf = lvls[storey].by_id(path)
    above = [lv.by_id(path) for lv in lvls[storey + 1:]]
    if any(n is not None and n.divided for n in above):
        return None
    n_above = sum(n is not None for n in above)
    r0 = target / geometry.area(leaf)
    best = None
    for rot in range(4):
        for room_left in (True, False):
            base = r0 if room_left else 1 - r0
            for r in (base - 0.04, base - 0.02, base, base + 0.02, base + 0.04):
                if not 0.02 < r < 0.98:
                    continue
                for fills in itertools.product(FILLERS, repeat=1 + n_above):
                    t = copy.deepcopy(root)
                    dom.link(t)
                    tl = dom.levels(t)
                    cells = [tl[storey].by_id(path)] + [
                        lv.by_id(path) for lv in tl[storey + 1:] if lv.by_id(path) is not None]
                    for c, fill in zip(cells, fills):
                        keep = dom.Node(type=c.type)
                        rest = dom.Node(type=fill)
                        c.left, c.right = (keep, rest) if room_left else (rest, keep)
                        c.division, c.rotation, c.type = [r, r], rot, None
                    dom.link(t)
                    sc, fl = fit.score_with_fails(t)
                    if best is None or sc > best[0]:
                        best = (sc, fl, f"rot {rot} r {r:.2f} fill {''.join(fills)}")
    return best


def self_test() -> int:
    """Negative control: swell one room of a real design and require the
    census to see it and every rule that should fire to fire."""
    d = REPO / "examples" / "harbor-house"
    fit, reqs = Fitness(*load_config(d)), programme.load_programme_dir(str(d))
    path = REPO / "experiments/results/halving-harbor-rooms/final-seed-20.dom"
    root = dom.load(str(path))
    dom.link(root)
    rows, *_ = survey(fit, reqs, root)
    over = [r for r in rows if r[5] > 3]
    assert over, "census sees no room over 3x on the §39.257 winner"
    usages = {r[2] for r in over}
    assert usages & set(SERVICE), f"expected a service room over 3x, got {usages}"
    for name, rule in RULES.items():
        n = sum(lines_added(r[5], r[2], rule) for r in rows)
        assert n > 0, f"rule {name} fires on nothing"
    # and a rule must NOT fire on a room exactly at target
    assert all(lines_added(1.0, u, rule) == 0 for rule in RULES.values() for u in SERVICE)
    assert lines_added(4.5, "living", RULES["all-log2"]) == 2
    assert lines_added(4.5, "living", RULES["svc>2"]) == 0
    assert cap_lines(1.0, 0.05) == 0 and cap_lines(0.9, 0.05) == 0
    assert cap_lines(1.12, 0.15) == 0
    assert cap_lines(1.12, 0.05) > cap_lines(1.12, 0.10) > 0
    print("self-test passed:", ", ".join(f"{r[1]} {r[5]:.1f}x" for r in over))
    return 0


def main() -> int:
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--rooms", action="store_true",
                    help="list every room over 1.5x its target")
    ap.add_argument("--trim", action="store_true",
                    help="for every room over 2x, does cutting it to target "
                         "(remainder outside or corridor) already score better?")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    paths = [Path(p) for p in a.paths] or default_paths()
    cache = {}
    if a.trim:
        return trim_census(paths, cache)
    names = list(RULES)
    print("programme\tdesign\tfails\tscore\tcap_margin\tover2\t" + "\t".join(names)
          + "".join(f"\tcap_s{s:.2f}" for s in CAP_SIGMAS))
    for path in paths:
        prog = next((v for k, v in KEYS.items() if k in str(path)), None)
        if prog is None:
            print(f"# skipped, no programme in path: {path}", file=sys.stderr)
            continue
        if prog not in cache:
            d = REPO / "examples" / prog
            cache[prog] = (Fitness(*load_config(d)), programme.load_programme_dir(str(d)))
        fit, reqs = cache[prog]
        root = dom.load(str(path))
        dom.link(root)
        rows, fails, score, margin = survey(fit, reqs, root)
        added = [sum(lines_added(r[5], r[2], RULES[n]) for r in rows) for n in names]
        rel = str(path.resolve().relative_to(REPO))
        over2 = sum(r[5] > 2 for r in rows)
        print(f"{prog}\t{rel}\t{len(fails)}\t{score:.3g}\t"
              f"{'-' if margin is None else f'{margin:.2f}'}\t{over2}\t"
              + "\t".join(map(str, added))
              + "".join(f"\t{cap_lines(margin, s):.1f}" for s in CAP_SIGMAS), flush=True)
        if a.rooms:
            for r in sorted(rows, key=lambda r: -r[5]):
                if r[5] > 1.5:
                    print(f"#\t{r[0]}\t{r[1]}\t{r[2]}\t{r[3]:.1f}/{r[4]:.0f} m2\t"
                          f"{r[5]:.2f}x\t{'size' if r[6] else 'NO size fail'}")
    return 0


def trim_census(paths, cache) -> int:
    print("programme\tdesign\tcell\tcode\tratio\tfails\ttrimmed_fails\t"
          "score_x\tbest\tgained\tlost")
    for path in paths:
        prog = next((v for k, v in KEYS.items() if k in str(path)), None)
        if prog is None:
            continue
        if prog not in cache:
            d = REPO / "examples" / prog
            cache[prog] = (Fitness(*load_config(d)), programme.load_programme_dir(str(d)))
        fit, reqs = cache[prog]
        root = dom.load(str(path))
        dom.link(root)
        rows, fails, score, _ = survey(fit, reqs, root)
        rel = str(path.resolve().relative_to(REPO))
        for cell, code, _u, _a, target, ratio, _s in rows:
            if ratio <= 2:
                continue
            storey, p = cell.split("/")
            res = trim(fit, root, int(storey), p, target)
            if res is None:
                print(f"{prog}\t{rel}\t{cell}\t{code}\t{ratio:.1f}\t{len(fails)}\t-\t-\t"
                      "divided above\t\t", flush=True)
                continue
            sc, fl, desc = res
            gained = sorted(set(fl) - set(fails))
            lost = sorted(set(fails) - set(fl))
            print(f"{prog}\t{rel}\t{cell}\t{code}\t{ratio:.1f}\t{len(fails)}\t{len(fl)}\t"
                  f"{sc / score:.3g}\t{desc}\t{'; '.join(gained)}\t{'; '.join(lost)}",
                  flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

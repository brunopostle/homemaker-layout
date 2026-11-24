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
import hashlib
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from successive_halving import REPO, load_config  # noqa: E402
from homemaker_layout import dom, geometry, programme  # noqa: E402
from homemaker_layout import operators  # noqa: E402
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
    """The area `quality_size` centres its gaussian on (the move's own
    `operators.size_target`, so the census and the move cannot disagree)."""
    return operators.size_target(fit, leaf)


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


def trim(fit, root, storey: int, path: str, target: float, prog_dir=None, inner=0):
    """The move itself (`operators.apply_trim`, `homemaker-py-s36o.1`) at each
    of its four draws. Returns [(score, fails, rotation)] per draw, after an
    inner loop of ``inner`` evaluations if asked -- warm-started as the driver
    starts a child: the parent's ratios, the move's own for its new cut."""
    from homemaker_layout import innerloop
    out = []
    for rot in range(4):
        t = copy.deepcopy(root)
        dom.link(t)
        operators.apply_trim(t, storey, path, target, rot)
        dom.link(t)
        geometry.clear_cache()
        if inner:
            parent = innerloop.ratio_map(root)
            x0 = innerloop.warm_x0(t, {**innerloop.ratio_map(t), **parent})
            innerloop.optimise(t, prog_dir, x0=x0, budget=inner)
            dom.link(t)
            geometry.clear_cache()
        sc, fl = fit.score_with_fails(t)
        out.append((sc, fl, rot))
    return out


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
                    help="census of the trim_oversized move: every room it "
                         "could draw, at each of its four draws, against its parent")
    ap.add_argument("--inner", type=int, default=0,
                    help="with --trim, re-tune child and parent with this many "
                         "inner-loop evaluations, as a search would")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    paths = [Path(p) for p in a.paths] or default_paths()
    cache = {}
    if a.trim:
        return trim_census(paths, cache, a.inner)
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


def trim_census(paths, cache, inner=0) -> int:
    """Every candidate the move would draw from, in every design, at each of
    its four draws: does the child beat its parent? With ``inner`` the parent
    gets the same inner loop, so a win is not just the extra tuning."""
    from homemaker_layout import innerloop
    print("programme\tdesign\tcell\tcode\tratio\tfails\tbest_fails\tbest_x\t"
          "draws_won\tbest_rot\tgained\tlost")
    for path in paths:
        prog = next((v for k, v in KEYS.items() if k in str(path)), None)
        if prog is None:
            continue
        d = REPO / "examples" / prog
        if prog not in cache:
            cache[prog] = (Fitness(*load_config(d)), programme.load_programme_dir(str(d)))
        fit, reqs = cache[prog]
        root = dom.load(str(path))
        dom.link(root)
        geometry.clear_cache()
        cands = operators.trim_candidates(root, fit)
        if not cands:
            continue
        if inner:
            innerloop.optimise(root, str(d), x0=innerloop.warm_x0(
                root, innerloop.ratio_map(root)), budget=inner)
            dom.link(root)
            geometry.clear_cache()
        score, fails = fit.score_with_fails(root)
        rel = str(path.resolve().relative_to(REPO))
        for li, p, target in cands:
            leaf = dom.levels(root)[li].by_id(p)
            ratio = geometry.area(leaf) / target
            code = leaf.type
            draws = trim(fit, root, li, p, target, str(d), inner)
            sc, fl, rot = max(draws, key=lambda x: x[0])
            won = sum(x[0] > score for x in draws)
            gained = sorted(set(fl) - set(fails))
            lost = sorted(set(fails) - set(fl))
            print(f"{prog}\t{rel}\t{li}/{p}\t{code}\t{ratio:.1f}\t{len(fails)}\t{len(fl)}\t"
                  f"{sc / score:.3g}\t{won}/4\t{rot}\t{'; '.join(gained)}\t{'; '.join(lost)}",
                  flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

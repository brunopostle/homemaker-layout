"""What does joining a finished design's circulation cost? (`homemaker-py-73r9`)

§39.192's `clean-9` has a single-loaded north range at 12 fails, three of them
`level N not connected`. `single-2`, connected, has 13. This takes the finished
design, runs the seeder's own `bridge_indoors` on each storey from the ground
up, and scores it raw and after the inner loop at the same topology. No search:
a price for the repair alone, seconds to minutes. Whether a search can then
recover what the repair cost is a separate question and needs the box.

Expectations, written before the first run:

  1. the repair joins storeys 1 and 2, whose north corridor is two rooms from a
     stair down the west wing, and may not join storey 0, where the pieces are
     buried in the south block and §39.159's opposite-walls case is likeliest;
  2. each room crossed costs its `size`, so raw fails rise to 15-21 for the
     3 or fewer removed;
  3. the inner loop gets back 1-3 of those, ending 14-18: worse than `single-2`'s
     13, which is the honest price before any search;
  4. rooms keep their codes: no missing room, no new `too few`/`too many`.

`--self-test`: a design already connected must come back with its cells and
score unmoved, or the before and after here are not comparable.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_join_clean9.py \\
        experiments/results/halving-maple-clean/final-clean-9.dom \\
        --out experiments/results/join-clean9/clean-9-bridged.dom
"""
import argparse, copy, re, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seed_from_catalogue import bridge_indoors, n_pieces  # noqa: E402
from successive_halving import REPO, load_config  # noqa: E402
from homemaker_layout import dom, geometry, innerloop, programme  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402


def family(f: str) -> str:
    """A fail with its cell and room names taken off."""
    f = re.sub(r"^\d+/\S+ ", "", f)
    f = re.sub(r"^\(\S+\) ", "", f)
    f = re.sub(r"^\d+ ", "", f)
    f = re.sub(r"^level \d+ ", "level ", f)
    return f.split(":")[0]


def report(label, fails, score) -> None:
    print(f"{label}: {len(fails)} fails, score {score:.4g}")
    print("   " + "; ".join(f"{k} {v}" for k, v in Counter(map(family, fails)).most_common()))


def storeys(root):
    while root is not None:
        yield root
        root = root.above


def join(root, reqs, fit) -> Counter:
    stats = Counter()
    for i, lvl in enumerate(storeys(root)):
        before = n_pieces(lvl, i > 0)
        made = bridge_indoors(lvl, reqs, stairs_join=i > 0, stats=stats, fit=fit)
        print(f"  storey {i}: pieces {before} -> {n_pieces(lvl, i > 0)}, {made} cells changed")
    return stats


def score(fit, root):
    dom.link(root); geometry.clear_cache()
    s, f = fit.score_with_fails(copy.deepcopy(root))
    geometry.clear_cache()
    return s, f


def self_test(fit, reqs, path) -> int:
    """A storey in one piece takes no bridge, so nothing may move."""
    r = dom.load(str(path)); dom.link(r)
    if any(n_pieces(l, i > 0) > 1 for i, l in enumerate(storeys(r))):
        print(f"self-test needs a fully connected design; {path} is not")
        return 2
    before = score(fit, r)
    stats = join(r, reqs, fit)
    after = score(fit, r)
    ok = before == after and not stats
    print("self-test", "passed" if ok else f"FAILED: {before} -> {after}, {stats}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("design")
    ap.add_argument("--programme", default="maple-court")
    ap.add_argument("--budget", type=int, default=2000, help="inner-loop evaluations")
    ap.add_argument("--out", help="write the tuned, joined design here")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    prog = REPO / "examples" / a.programme
    fit = Fitness(*load_config(prog))
    reqs = programme.load_programme_dir(str(prog))
    if a.self_test:
        return self_test(fit, reqs, a.design)

    root = dom.load(a.design); dom.link(root)
    s, f = score(fit, root)
    report("finished design", f, s)
    print(*sorted(f), sep="\n   ")
    stats = join(root, reqs, fit)
    print(f"  strips cut {stats['strip']}, routes abandoned {stats['left']}")
    s, f = score(fit, root)
    report("joined, raw", f, s)
    print(*sorted(f), sep="\n   ")
    res = innerloop.optimise(root, str(prog), budget=a.budget, method="nm")
    dom.link(root)
    s, f = score(fit, root)
    report(f"joined, inner loop {a.budget}", f, s)
    print(*sorted(f), sep="\n   ")
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        dom.dump(root, a.out)
        print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

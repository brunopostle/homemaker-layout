"""The same designs ranked by different ways of adding up a score
(`homemaker-py-5fje`, DESIGN.md §39.200).

Today's objective is

    score = sum_cells(area * value_rate * quality) * building_factor * 0.5**fails / cost

so a cell's say is its AREA, and a room that cannot be made good loses least
by being made small (§39.199). This re-scores committed designs under
candidate aggregations, reading every per-cell factor and every fail from the
live scorer, and changes nothing in src/ -- the objective stamp does not move.

Arms:

  A0     today's score.
  A1     value - cost: value * building_factor * 0.5**fails - cost. The
         owner's other reading of Urb's cost-benefit term. The penalty goes on
         value: at today's rates value is well under cost on every design, so
         (value - cost) * 0.5**fails is negative and a fail would RAISE it.
  P1     programme-centric, equal votes: each REQUIRED room instance gets a
         satisfaction s_i = product of its cell's factors, each floored at
         PHI, times 0.5 per adjacency it misses; a missing instance gets
         PHI**2. Score = geomean(s_i) * building_factor * 0.5**n_bld, where
         n_bld counts the fails no room carries (connectivity, stairs,
         covered outside, geometry fails on C/O/E cells, ...).
  P2     as P1, each room's log s_i weighted by its DECLARED target area, so
         big rooms still matter more but by what was asked, not what was
         built.

Neither P arm has a cost term: `area_cap` inside building_factor is the only
statement about building too much. Extra instances of a code (more cells
than `count`) get no vote; the best `count` cells of a code vote.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_aggregation.py \\
        [--phi 1e-3] [--tsv out.tsv] DESIGN.dom ...

The programme is read from the path, as in diag_shrunk_rooms.py.
"""
import argparse
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diag_shrunk_rooms import KEYS  # noqa: E402
from successive_halving import REPO, load_config  # noqa: E402
from homemaker_layout import dom, geometry, programme  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402

CELL_FAIL = re.compile(r"^(\d+)/([lr]*) (\w+)$")
ADJ_FAIL = re.compile(r"^(\d+)/([lr]*) \((\w+)\) not adjacent to (\w+)$")


def capture(fit, root):
    """Score ``root`` and return (score, fails, cells, building_factor, value, cost)."""
    cells, bf, plot = [], [1.0], [0.0]
    ps, eb, pc = fit.process_storey, fit.evaluate_building, fit.plot_cost

    def process_storey(*a, **k):
        se = ps(*a, **k)
        cells.append(se)
        return se

    def evaluate_building(*a, **k):
        bf[0] = eb(*a, **k)
        return bf[0]

    def plot_cost(*a, **k):
        plot[0] = pc(*a, **k)
        return plot[0]

    fit.process_storey, fit.evaluate_building, fit.plot_cost = (
        process_storey, evaluate_building, plot_cost)
    try:
        score, fails = fit.score_with_fails(root)
    finally:
        del fit.process_storey, fit.evaluate_building, fit.plot_cost
    value = sum(se.value for se in cells)
    cost = plot[0] + sum(se.cost for se in cells)
    leaves = [le for se in cells for le in se.leaves]
    return score, fails, leaves, bf[0], value, cost


def arms(fit, reqs, root, phi):
    score, fails, leaves, bf, value, cost = capture(fit, root)
    rooms = {c: r for c, r in reqs.items() if not dom.is_generic(c)}
    by_cell = {(le.level, le.id): le for le in leaves}
    adj_miss = defaultdict(int)
    room_fails = 0
    n_bld = 0
    for f in fails:
        m = ADJ_FAIL.match(f)
        if m and (int(m[1]), m[2]) in by_cell and by_cell[int(m[1]), m[2]].type in rooms:
            adj_miss[int(m[1]), m[2]] += 1
            room_fails += 1
            continue
        m = CELL_FAIL.match(f)
        if m and (int(m[1]), m[2]) in by_cell and by_cell[int(m[1]), m[2]].type in rooms:
            room_fails += 1           # carried by s_i through the factor itself
            continue
        if f.startswith("missing"):
            room_fails += 1           # carried by s_i = PHI**2
            continue
        n_bld += 1

    sat = defaultdict(list)
    for le in leaves:
        if le.type in rooms:
            s = math.prod(max(phi, v) for v in le.factors.values())
            s *= 0.5 ** adj_miss[le.level, le.id]
            sat[le.type].append(s)
    votes, extra, missing, token = [], 0, 0, 0
    for code, r in rooms.items():
        got = sorted(sat.get(code, []), reverse=True)
        extra += max(0, len(got) - r.count)
        got = got[: r.count]
        missing += r.count - len(got)
        got += [phi ** 2] * (r.count - len(got))
        votes += [(r.size or 1.0, s) for s in got]
    for le in leaves:
        r = rooms.get(le.type)
        if r and r.size and le.area / r.size < 0.25:
            token += 1
    w = sum(t for t, _ in votes)
    p1 = math.exp(sum(math.log(s) for _, s in votes) / len(votes)) * bf * 0.5 ** n_bld
    p2 = math.exp(sum(t * math.log(s) for t, s in votes) / w) * bf * 0.5 ** n_bld
    a1 = value * bf * 0.5 ** len(fails) - cost
    return dict(A0=score, A1=a1, P1=p1, P2=p2, fails=len(fails), n_bld=n_bld,
                room_fails=room_fails, missing=missing, extra=extra, token=token,
                bf=bf, value=value, cost=cost, fail_lines=fails)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("designs", nargs="+")
    ap.add_argument("--phi", type=float, default=1e-3, help="per-factor floor")
    ap.add_argument("--tsv", help="also write the rows here")
    a = ap.parse_args()
    if not geometry.ORTHOGONAL_DIVISION:
        sys.exit("set HOMEMAKER_ORTHOGONAL_DIVISION=1")
    cache, rows = {}, []
    cols = ["A0", "A1", "P1", "P2", "fails", "n_bld", "room_fails", "missing",
            "extra", "token", "bf", "value", "cost"]
    head = "programme\tdesign\t" + "\t".join(cols)
    print(head)
    for path in a.designs:
        prog = next((v for k, v in KEYS.items() if k in path), None)
        if prog is None:
            print(f"# skipped, no programme in path: {path}", file=sys.stderr)
            continue
        if prog not in cache:
            d = REPO / "examples" / prog
            cache[prog] = (Fitness(*load_config(d)), programme.load_programme_dir(str(d)))
        fit, reqs = cache[prog]
        root = dom.load(path)
        dom.link(root)
        r = arms(fit, reqs, root, a.phi)
        line = f"{prog}\t{path}\t" + "\t".join(
            f"{r[c]:.4g}" if isinstance(r[c], float) else str(r[c]) for c in cols)
        print(line, flush=True)
        rows.append(line)
    if a.tsv:
        Path(a.tsv).write_text(head + "\n" + "\n".join(rows) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

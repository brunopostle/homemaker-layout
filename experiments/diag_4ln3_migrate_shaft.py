"""`homemaker-py-4ln3`: does `mutate_level_add_migrate` keep the staircase?

DESIGN.md §39.134's A/B of `--level-add-migrate` ended three of 36 runs with a
stair fail against none in the control, and the bead had said beforehand that
a stair fail under the flag "would be a defect in its shaft guard". Three runs
resolve nothing, so this asks the operator directly, the census way (§39.73):
apply it to every committed design that has a staircase and count what happens
to the staircase.

    HOMEMAKER_ORTHOGONAL_DIVISION=1 python experiments/diag_4ln3_migrate_shaft.py
    ... --from-broken     parents are CHILDREN of one draw from the search's mix
    ... --self-test       the negative controls, alone
    ... --three           the three flagged designs, storey by storey

Per draw that moved (the operator says "noop" when it declines):

  LOST      a shaft the parent had is no longer one: its foot is not an `E`
            leaf whose exact path is an `E` leaf on the storey above
            (`operators._shaft_paths`, `graph.stair_shaft`)
  short     the shaft is kept but does not reach the storey just added, where
            the parent's reached its top. Not a fail by itself -- a stair may
            stop below the top (§39.125) -- but the operator's docstring says
            the core continues, so it is counted
  +few      the child fails `too few stairs` and the parent did not
  +volume   the child fails `staircase volume` and the parent did not. Scored
            as the operator leaves it, ratios untuned
  made      (parents with NO shaft only) the child has one
  aligned   (the same parents) the address the operator falls back to -- the
            largest ground `E` or `C` leaf, `operators._stair_path` -- is a
            circulation LEAF on every storey of the parent, which is what it
            takes for retyping that address to make a column

A zero here is worth nothing until each check has been seen to fire, so the
self-test runs first on every invocation: it takes real children of the
operator and breaks them the two ways the checks exist to catch.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402

from homemaker_layout import dom, driver, genome, geometry, graph, operators, programme  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402
from homemaker_layout.fitness_cmd import load_config  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PROGRAMMES = ("programme-house", "harbor-house", "health-centre", "maple-court")
FLAGGED = (6, 14, 32)          # §39.134's three migrate-arm seeds


def climbs(root: dom.Node) -> "dict[str, int]":
    """Every shaft's foot path -> the number of storeys it stands on."""
    lvls = dom.levels(root)
    return {lf.id: len(graph.stair_shaft(lf)) for lf in operators._shaft_feet(lvls)}


def check(parent: dom.Node, child: dom.Node) -> "set[str]":
    """The structural checks: what became of the parent's shafts."""
    before, after = climbs(parent), climbs(child)
    out = set()
    n_before, n_after = len(dom.levels(parent)), len(dom.levels(child))
    if not before:
        if after:
            out.add("made")
        return out
    if set(before) - set(after):
        out.add("LOST")
    if n_after > n_before and any(
            before[p] == n_before and after[p] < n_after
            for p in set(before) & set(after)):
        out.add("short")
    return out


def stair_fails(fit: Fitness, root: dom.Node) -> "set[str]":
    geometry.clear_cache()
    _score, fails = fit.score_with_fails(root)
    return {"few" if f.startswith("too few stairs") else "volume"
            for f in fails
            if f.startswith("too few stairs") or f == "staircase volume"}


def rng_for(path: Path, *salt) -> np.random.Generator:
    """A stream of the artefact's own. The whole path is hashed: the low bytes
    of every `coldstart-...` name are the same, and `hash()` is salted per
    process (§39.109)."""
    h = hashlib.sha1(("|".join([str(path), *map(str, salt)])).encode()).digest()
    return np.random.default_rng(int.from_bytes(h[:8], "big"))


def search_weights() -> "dict[str, float]":
    """The default search's mutation mix, read off `driver.search`'s defaults."""
    w = dict(driver._MUTATION_WEIGHTS)
    for name, param in inspect.signature(driver.search).parameters.items():
        if name.startswith("enable_") and not param.default:
            w[name[len("enable_"):]] = 0.0
    for off in ("level_add_migrate", "light_well", "storey_height"):
        w[off] = 0.0
    return w


def parents_of(prog_name: str) -> "list[Path]":
    prog = REPO / "examples" / prog_name
    paths = sorted(p for p in prog.glob("coldstart-*.dom") if "+orth" in p.name)
    if prog_name == "programme-house":
        paths += sorted((REPO / "experiments" / "results" / "v2k-ab")
                        .glob("v2k-ab-programme-house-shipped-s*.dom"))
    return paths


def load(path: Path) -> dom.Node:
    geometry.clear_cache()
    return genome.decode(genome.encode(dom.load(str(path))))


def self_test() -> bool:
    """Break real children the two ways the checks exist to catch."""
    prog = REPO / "examples" / "programme-house"
    conf, cost = load_config(prog)
    fit = Fitness(conf, cost)
    reqs = programme.load_programme_dir(str(prog))
    types = sorted(reqs) + ["C", "O"]
    fired = Counter()
    tried = 0
    for path in parents_of("programme-house"):
        root = load(path)
        if not climbs(root):
            continue
        child, desc = operators.mutate_level_add_migrate(
            root, rng_for(path, "self"), types, reqs=reqs)
        if "noop" in desc or check(root, child):
            continue                      # want a clean child to corrupt
        tried += 1
        foot = next(iter(climbs(child)))
        lvls = dom.levels(child)
        # (a) the landing on the first floor stops being a stair
        bad = copy.deepcopy(child)
        dom.levels(bad)[1].by_id(foot).type = "C"
        operators._finalise(bad)
        if "LOST" in check(root, bad):
            fired["LOST"] += 1
        if "few" in stair_fails(fit, bad) and "few" not in stair_fails(fit, root):
            fired["few"] += 1
        # (b) the landing on the storey just added stops being one
        bad = copy.deepcopy(child)
        dom.levels(bad)[len(lvls) - 1].by_id(foot).type = "C"
        operators._finalise(bad)
        if "short" in check(root, bad):
            fired["short"] += 1
        if tried == 6:
            break
    ok = tried > 0 and all(fired[k] == tried for k in ("LOST", "few", "short"))
    print(f"self-test: {tried} clean children corrupted; fired "
          f"LOST {fired['LOST']}, +few {fired['few']}, short {fired['short']} "
          f"of {tried} each -- {'ok' if ok else 'A CHECK IS SILENT'}")
    return ok


def three() -> None:
    prog = REPO / "examples" / "programme-house"
    conf, cost = load_config(prog)
    fit = Fitness(conf, cost)
    for seed in FLAGGED:
        for arm in ("migrate", "shipped"):
            path = (REPO / "experiments" / "results" / "v2k-ab" /
                    f"v2k-ab-programme-house-{arm}-s{seed}.dom")
            geometry.clear_cache()
            root = dom.load(str(path))
            score, fails = fit.score_with_fails(root)
            lvls = dom.levels(root)
            print(f"s{seed} {arm}: {len(lvls)} storeys, score {score:.4g}, "
                  f"fails {list(fails)}")
            for i, lvl in enumerate(lvls):
                print(f"    L{i} " + " ".join(f"{lf.id or '.'}:{lf.type}"
                                             for lf in lvl.leaves()))
            for lf in lvls[0].leaves():
                if lf.type == dom.GENERIC_STAIR:
                    print(f"    stair foot {lf.id}: on {len(graph.stair_shaft(lf))} "
                          f"storeys, {geometry.area(lf):.1f} m2, "
                          f"{geometry.usable_width(lf):.2f} m wide")
            if not climbs(root):
                print("    NO SHAFT")


def census(programmes, draws: int, from_broken: bool) -> None:
    weights = search_weights()
    total = Counter()
    for prog_name in programmes:
        prog = REPO / "examples" / prog_name
        conf, cost = load_config(prog)
        fit = Fitness(conf, cost)
        reqs = programme.load_programme_dir(str(prog))
        types = sorted(reqs) + ["C", "O"]
        row = Counter()
        via = Counter()
        examples = []
        for path in parents_of(prog_name):
            artefact = load(path)
            for d in range(draws):
                parent = artefact
                if from_broken:
                    parent, pdesc = operators.mutate(
                        artefact, rng_for(path, "break", d), types,
                        weights=weights, reqs=reqs, fit=fit)
                    if "noop" in pdesc:
                        continue
                    via[pdesc.split()[0]] += 1
                has = bool(climbs(parent))
                group = "shaft" if has else "none"
                aligned = False
                if not has:
                    lvls = dom.levels(parent)
                    at = [lvl.by_id(operators._stair_path(lvls) or "?")
                          for lvl in lvls]
                    aligned = all(n is not None and not n.divided
                                  and dom.is_circulation(n) for n in at)
                geometry.clear_cache()
                child, desc = operators.mutate_level_add_migrate(
                    parent, rng_for(path, "migrate", d), types, reqs=reqs)
                row[group, "n"] += 1
                if "noop" in desc:
                    row[group, "noop"] += 1
                    continue
                flags = check(parent, child)
                new = stair_fails(fit, child) - stair_fails(fit, parent)
                flags |= {"+" + f for f in new}
                if aligned:
                    flags.add("aligned")
                for f in flags:
                    row[group, f] += 1
                if flags & {"LOST", "+few"} and len(examples) < 4:
                    examples.append((path.name, d, sorted(flags), desc,
                                     climbs(parent), climbs(child)))
        print(f"\n{prog_name}: {len(parents_of(prog_name))} designs x {draws} draws"
              + ("  (parents: one draw of the search's mix)" if from_broken else ""))
        if from_broken:
            print("  drawn: " + ", ".join(f"{k} {v}" for k, v in via.most_common()))
        for group, label in (("shaft", "parent has a shaft"),
                             ("none", "parent has NO shaft")):
            n = row[group, "n"]
            if not n:
                continue
            moved = n - row[group, "noop"]
            cols = (("LOST", "short", "+few", "+volume") if group == "shaft"
                    else ("made", "aligned", "+few", "+volume"))
            print(f"  {label:20s} {n:4d} draws, {moved:4d} moved: "
                  + "  ".join(f"{c} {row[group, c]}" for c in cols))
        for name, d, flags, desc, before, after in examples:
            print(f"    e.g. {name} draw {d}: {flags}  {desc}\n"
                  f"         shafts {before} -> {after}")
        total.update(row)
    moved = total["shaft", "n"] - total["shaft", "noop"]
    print(f"\nALL, parents with a shaft: {moved} moves; "
          f"LOST {total['shaft', 'LOST']}, short {total['shaft', 'short']}, "
          f"+few {total['shaft', '+few']}, +volume {total['shaft', '+volume']}")
    moved = total["none", "n"] - total["none", "noop"]
    if moved:
        print(f"ALL, parents with none:    {moved} moves; "
              f"made {total['none', 'made']}, +few {total['none', '+few']}, "
              f"+volume {total['none', '+volume']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--draws", type=int, default=8)
    ap.add_argument("--from-broken", action="store_true",
                    help="parents are children of one draw from the search's mix")
    ap.add_argument("--self-test", action="store_true",
                    help="run the negative controls and stop")
    ap.add_argument("--three", action="store_true",
                    help="print the three flagged designs and stop")
    args = ap.parse_args(argv)
    if not geometry.ORTHOGONAL_DIVISION:
        print("set HOMEMAKER_ORTHOGONAL_DIVISION=1: every parent here is a "
              "+orth design", file=sys.stderr)
        return 2
    if args.three:
        three()
        return 0
    if not self_test():
        return 1
    if args.self_test:
        return 0
    census(args.programme or list(PROGRAMMES), args.draws, args.from_broken)
    return 0


if __name__ == "__main__":
    sys.exit(main())

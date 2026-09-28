"""Which operators produce a STRUCTURALLY broken child?

`diag_t7q_shaft_breakage.py` applies every operator to every corpus artefact and
counts how often one invariant -- the staircase shaft -- stops holding. That
pattern found real defects twice in a week (§39.73, §39.75). The shaft is the only
invariant it checks. This checks the structural ones, which differ from the shaft
in an important way: breaking a shaft is a TRADE the comparator can judge (§39.74),
and so are `on wrong level` and `storey_limit`/`storey_minimum`, because the scorer
charges for all three. The invariants here are not trades. A child that violates
one is malformed, and no comparator can price that.

  typeless      a leaf with no `type`. `_generic_class` returns "" for it, so the
                scorer treats it as a programme room with no target and it slips
                through as a silently mis-scored space rather than an error.
  half_divided  `division` set with only one child, or children with no
                `division`. `Node.divided` requires all three, so such a node is
                silently read as a LEAF while carrying a cut.
  stale_below   the worst one. `dom.link` points each node at the same-id node one
                storey down, and `geometry.coordinate` follows `below` BEFORE it
                reads a node's own rotation or division (§39.70). An operator that
                restructures without re-linking leaves those pointers addressing
                nodes that moved or no longer exist, so the child's GEOMETRY is
                computed from the wrong parent -- with no exception raised.
                Measured by re-running `dom.link` on a copy and diffing.
  roundtrip     `genome.decode(genome.encode(child))` must preserve every leaf's
                (level, id, type). The genome is what the search stores and what
                `genome.signature` dedups on, so a child it cannot represent is a
                child the search will mutate into something else than it scored.
  unscorable    `Fitness.score_with_fails` raises on the child.

Each artefact is handled under its own objective's orthogonal-division setting
(`+orth` in the name), since operators read geometry, and trees are canonicalised
through `genome.encode`/`decode` first because that is the form the search mutates.

    python experiments/diag_operator_invariants.py [--draws 8] [--programme NAME]
"""

from __future__ import annotations

import argparse
import copy
import inspect
import sys
import traceback
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402

from homemaker_layout import dom, driver, genome, geometry, operators, programme  # noqa: E402
from homemaker_layout.fitness import Fitness  # noqa: E402
from homemaker_layout.fitness_cmd import load_config  # noqa: E402

PROGRAMMES = ("harbor-house", "health-centre", "maple-court", "programme-house")
CHECKS = ("typeless", "half_divided", "stale_below", "roundtrip", "unscorable")


def _all_nodes(n: dom.Node) -> "list[dom.Node]":
    out = [n]
    for kid in (n.left, n.right):
        if kid is not None:
            out.extend(_all_nodes(kid))
    return out


def _nodes_by_address(root: dom.Node) -> "dict[tuple[int, str], dom.Node]":
    return {(li, n.id): n
            for li, lvl in enumerate(dom.levels(root))
            for n in _all_nodes(lvl)}


def _leaf_types(root: dom.Node) -> "dict[tuple[int, str], tuple]":
    """A leaf's identity to the scorer: its code, and the two modifiers that
    change how that code is read -- `share` (leaf-sharing, erc.3 §13.3) and
    `co_type` (multi-use, §26 path b). `GNode` carries none of the latter two,
    so the genome silently drops them; no corpus artefact uses either today, so
    this arm is latent coverage rather than a live finding."""
    return {(li, lf.id): (lf.type, lf.share or 1, lf.co_type)
            for li, lvl in enumerate(dom.levels(root))
            for lf in lvl.leaves()}


# --------------------------------------------------------------------------- #
def check_typeless(root) -> list[str]:
    return [f"{li}/{lf.id}"
            for li, lvl in enumerate(dom.levels(root))
            for lf in lvl.leaves() if not lf.type]


def check_half_divided(root) -> list[str]:
    bad = []
    for li, lvl in enumerate(dom.levels(root)):
        for n in _all_nodes(lvl):
            has_kids = (n.left is not None) or (n.right is not None)
            both_kids = (n.left is not None) and (n.right is not None)
            if has_kids and not both_kids:
                bad.append(f"{li}/{n.id} one child")
            elif both_kids and n.division is None:
                bad.append(f"{li}/{n.id} children but no division")
    return bad


def check_stale_below(root) -> list[str]:
    """`below` pointers that `dom.link` would set differently."""
    before = {addr: (None if n.below is None else n.below.id)
              for addr, n in _nodes_by_address(root).items()}
    probe = copy.deepcopy(root)
    dom.link(probe)
    after = {addr: (None if n.below is None else n.below.id)
             for addr, n in _nodes_by_address(probe).items()}
    bad = []
    for addr in sorted(set(before) | set(after), key=str):
        if before.get(addr, "<<missing>>") != after.get(addr, "<<missing>>"):
            bad.append(f"{addr[0]}/{addr[1]}: {before.get(addr)!r} -> {after.get(addr)!r}")
    return bad


def check_roundtrip(root) -> list[str]:
    try:
        rebuilt = genome.decode(genome.encode(root))
    except Exception as exc:                      # noqa: BLE001
        return [f"encode/decode raised {type(exc).__name__}: {exc}"]
    before, after = _leaf_types(root), _leaf_types(rebuilt)
    bad = []
    for addr in sorted(set(before) | set(after), key=str):
        if before.get(addr, "<<absent>>") != after.get(addr, "<<absent>>"):
            bad.append(f"{addr[0]}/{addr[1]}: {before.get(addr)!r} -> {after.get(addr)!r}")
    return bad


def check_unscorable(root, conf, cost) -> list[str]:
    try:
        Fitness(conf, cost).score_with_fails(copy.deepcopy(root))
    except Exception as exc:                      # noqa: BLE001
        return [f"{type(exc).__name__}: {exc}"]
    return []


def _gates() -> "dict[str, bool]":
    sig = inspect.signature(driver.search)
    return {name[len("enable_"):]: bool(param.default)
            for name, param in sig.parameters.items()
            if name.startswith("enable_")}


# --------------------------------------------------------------------------- #
# Negative control. A census that reports zero is worth nothing until each check
# has been shown to FIRE (§39.75's lesson, and the monkeypatch control in
# tests/test_stair_shaft_is_a_full_column.py). Each case corrupts a real corpus
# tree in exactly one way and asserts the matching check catches it.
# --------------------------------------------------------------------------- #
def self_test(conf, cost, root: dom.Node) -> int:
    def _first_divided(r):
        for lvl in dom.levels(r):
            for n in _all_nodes(lvl):
                if n.divided:
                    return n
        return None

    cases = []

    t = copy.deepcopy(root)
    next(iter(dom.levels(t)[0].leaves())).type = None
    cases.append(("typeless", check_typeless, t))

    t = copy.deepcopy(root)
    _first_divided(t).right = None
    cases.append(("half_divided", check_half_divided, t))

    t = copy.deepcopy(root)
    lvls = dom.levels(t)
    if len(lvls) > 1:
        # Point an upper node at a DIFFERENT node below, as a restructure that
        # forgot to re-link would. It must not be the storey root: that one's id
        # is "" and so is its correct below's, so aiming it at the level-0 root
        # changes nothing and the control passes vacuously (it did, first try).
        upper = next((n for n in _all_nodes(lvls[1])
                      if n.below is not None and n.id != ""), None)
        wrong = next((n for n in _all_nodes(lvls[0]) if n.id != upper.id), None) \
            if upper is not None else None
        if upper is not None and wrong is not None:
            upper.below = wrong
            cases.append(("stale_below", check_stale_below, t))

    t = copy.deepcopy(root)
    # `decode` reapplies a leaf's TYPE from the retypes delta, so a bogus type
    # round-trips intact and is not a control. `share` is genuinely absent from
    # `GNode`, so it is the thing the genome really cannot carry.
    next(iter(dom.levels(t)[0].leaves())).share = 3
    cases.append(("roundtrip", check_roundtrip, t))

    t = copy.deepcopy(root)
    dom.levels(t)[0].node = None          # no plot corners: geometry cannot run
    cases.append(("unscorable",
                  lambda r: check_unscorable(r, conf, cost), t))

    print("negative control -- each check must FIRE on a deliberately broken tree")
    failures = 0
    for name, fn, tree in cases:
        geometry.clear_cache()
        try:
            hits = fn(tree)
        except Exception as exc:                  # noqa: BLE001
            hits = [f"check itself raised {type(exc).__name__}: {exc}"]
        ok = bool(hits)
        failures += not ok
        print("  %-14s %s  %s" % (
            name, "FIRES" if ok else "!! SILENT -- the census cannot see this",
            ("; ".join(str(h) for h in hits[:2])[:96] if ok else "")))
    geometry.clear_cache()
    if failures:
        print(f"\n!! {failures} check(s) cannot detect their own defect; "
              "a zero in the census below means nothing for those rows.")
    else:
        print("  all checks fire, so a zero in the census is a real zero.")
    return failures


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--programme", action="append", choices=PROGRAMMES)
    ap.add_argument("--draws", type=int, default=8)
    ap.add_argument("--examples", type=int, default=3,
                    help="worked examples to print per (operator, check)")
    ap.add_argument("--no-self-test", dest="self_test", action="store_false",
                    help="skip the negative control (it is cheap; do not)")
    ap.add_argument("--from-broken", action="store_true",
                    help="apply a random FIRST operator, then measure the second "
                         "on its child -- the state a search actually offers an "
                         "operator, rather than a converged artefact (§39.75, "
                         "where that distinction changed an answer twenty-fold)")
    args = ap.parse_args(argv)
    programmes = args.programme or list(PROGRAMMES)

    if args.self_test:
        prog = REPO / "examples" / programmes[0]
        conf, cost = load_config(prog)
        path = sorted(prog.glob("coldstart-*.dom"))[0]
        geometry.ORTHOGONAL_DIVISION = "+orth" in path.name
        ctrl = genome.decode(genome.encode(dom.load(str(path))))
        geometry.clear_cache()
        self_test(conf, cost, ctrl)
        print()

    gates = _gates()
    gates_for = {"shape_rotate": gates.get("shape_repair", False),
                 "deslim": gates.get("shape_repair", False)}

    stats: dict = defaultdict(lambda: dict.fromkeys(("n", "noop", *CHECKS), 0))
    examples: dict = defaultdict(list)
    parent_bad: dict = defaultdict(int)

    for prog_name in programmes:
        prog = REPO / "examples" / prog_name
        conf, cost = load_config(prog)
        reqs = programme.load_programme_dir(str(prog))
        types = sorted(reqs) + ["C", "O"]

        for path in sorted(prog.glob("coldstart-*.dom")):
            geometry.ORTHOGONAL_DIVISION = "+orth" in path.name
            root = genome.decode(genome.encode(dom.load(str(path))))
            geometry.clear_cache()

            # the parent must itself be clean, or a child's breakage is inherited
            for name, found in (("typeless", check_typeless(root)),
                                ("half_divided", check_half_divided(root)),
                                ("stale_below", check_stale_below(root)),
                                ("roundtrip", check_roundtrip(root))):
                if found:
                    parent_bad[name] += 1

            fit = Fitness(conf, cost)

            def _kw_for(fn):
                params = inspect.signature(fn).parameters
                kw = {}
                if "reqs" in params:
                    kw["reqs"] = reqs
                if "fit" in params:
                    kw["fit"] = fit
                return kw

            def _parent_for(seed: int) -> dom.Node:
                """The tree the second operator actually sees."""
                if not args.from_broken:
                    return root
                rng = np.random.default_rng(10_000 + seed)
                first = sorted(operators.MUTATIONS)[
                    int(rng.integers(len(operators.MUTATIONS)))]
                fn = operators.MUTATIONS[first]
                geometry.clear_cache()
                try:
                    damaged, _d = fn(root, rng, types, **_kw_for(fn))
                except Exception:                 # noqa: BLE001
                    return root
                geometry.clear_cache()
                return damaged

            for op_name in sorted(operators.MUTATIONS):
                op = operators.MUTATIONS[op_name]
                kw = _kw_for(op)
                for seed in range(args.draws):
                    parent = _parent_for(seed)
                    geometry.clear_cache()
                    try:
                        child, desc = op(parent, np.random.default_rng(seed), types, **kw)
                    except Exception as exc:      # noqa: BLE001
                        row = stats[op_name]
                        row["n"] += 1
                        row["unscorable"] += 1
                        if len(examples[(op_name, "raised")]) < args.examples:
                            examples[(op_name, "raised")].append(
                                f"{path.name} seed={seed}: {type(exc).__name__}: {exc}\n"
                                + "".join(traceback.format_exc(limit=3)))
                        continue
                    geometry.clear_cache()

                    row = stats[op_name]
                    row["n"] += 1
                    if "noop" in desc:
                        row["noop"] += 1
                    found = {
                        "typeless": check_typeless(child),
                        "half_divided": check_half_divided(child),
                        "stale_below": check_stale_below(child),
                        "roundtrip": check_roundtrip(child),
                        "unscorable": check_unscorable(child, conf, cost),
                    }
                    for check, hits in found.items():
                        if hits:
                            row[check] += 1
                            key = (op_name, check)
                            if len(examples[key]) < args.examples:
                                examples[key].append(
                                    f"{path.name} seed={seed} [{desc}]: " + "; ".join(hits[:4]))

    # ----------------------------------------------------------------- report #
    print("Structural invariants after one operator application.")
    print("Parents are canonicalised through genome.encode/decode first.\n")
    if any(parent_bad.values()):
        print("!! some PARENT artefacts already violate a check:",
              dict(parent_bad), "\n")
    else:
        print("every parent artefact is clean on every check "
              "(so anything below is the operator's doing)\n")

    gate_note = {**gates, **gates_for}
    print("%-26s %5s %5s %s" % ("operator", "n", "noop",
                                "  ".join("%12s" % c for c in CHECKS)))
    total = dict.fromkeys(CHECKS, 0)
    for op_name in sorted(stats):
        row = stats[op_name]
        on = gate_note.get(op_name)
        tag = "" if on is None else ("  [default ON]" if on else "  [default off]")
        cells = "  ".join("%12d" % row[c] for c in CHECKS)
        print("%-26s %5d %5d %s%s" % (op_name, row["n"], row["noop"], cells, tag))
        for c in CHECKS:
            total[c] += row[c]
    print("%-26s %5s %5s %s" % ("TOTAL", "", "",
                                "  ".join("%12d" % total[c] for c in CHECKS)))

    if examples:
        print("\nworked examples")
        for (op_name, check), rows in sorted(examples.items()):
            print(f"\n-- {op_name} / {check}")
            for r in rows:
                print("   " + r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

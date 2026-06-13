#!/usr/bin/env python3
"""homemaker-py-gnw acceptance: per-leaf quality factors and per-storey
cost/value parity between homemaker.fitness and Urb's programme-driven fitness.

Runs experiments/dump_leaf_quality.pl (URB_NO_OCCLUSION oracle with per-leaf
DEBUG re-enabled) over the corpus, parses its output, and diffs against the
native evaluation: 7 quality factors + rate + area per leaf, cost/value per
storey, initial (plot) cost, and the leaf-scope failure set.

Usage: python3 experiments/leaf_parity.py [corpus_dir]
"""

from __future__ import annotations

import math
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from homemaker import dom, fitness, graph  # noqa: E402

URB = Path("/home/bruno/src/urb")
CORPUS = Path(sys.argv[1]) if len(sys.argv) > 1 else URB / "examples" / "programme-house"
WRAPPER = Path(__file__).resolve().parent / "dump_leaf_quality.pl"

REL_TOL = 1e-9

# Failures emitted by the gnw scope (leaf quality + cost functions + the two
# per-leaf structural checks in process_storey). All carry a "level/" prefix —
# requiring it excludes building-level fails like 'no outside public access'
# (homemaker-py-hgg scope), which would otherwise match the ' access' suffix.
_LEAF_FAIL_RE = re.compile(
    r"^\d+/.* (perpendicular|proportion|size|width|crinkliness|daylight|access"
    r"|edge too long|unsupported covered outside|covered outside above ground)$"
)

_FACTOR_RE = re.compile(r"^  quality (\w+): (\S+)$")
_LEAF_RE = re.compile(
    r"^leaf level: (\d+) id: ([lr]*) type: (\S+) rate: (\S+) area: (\S+) "
    r"width: (\S+) proportion: (\S+)$"
)
_STOREY_RE = re.compile(r"^STOREY (\d+) cost: (\S+) value: (\S+)$")


def run_oracle(files: list[str]) -> dict[str, dict]:
    """Run the wrapper over all files; return per-file parsed records."""
    proc = subprocess.run(
        ["perl", f"-I{URB}/lib", str(WRAPPER)] + files,
        cwd=CORPUS,
        env={"URB_NO_OCCLUSION": "1", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"wrapper failed:\n{proc.stderr}")

    out: dict[str, dict] = {}
    rec = None
    pending: dict[str, float] = {}
    for line in proc.stdout.splitlines():
        if line.startswith("=== FILE "):
            rec = out[line[len("=== FILE "):]] = {
                "leaves": {}, "storeys": {}, "fails": [], "initial_cost": None,
                "score": None,
            }
            pending = {}
            continue
        if rec is None:
            continue
        m = _FACTOR_RE.match(line)
        if m:
            pending[m.group(1)] = float(m.group(2))
            continue
        m = _LEAF_RE.match(line)
        if m:
            level, lid = int(m.group(1)), m.group(2)
            rec["leaves"][(level, lid)] = {
                "type": m.group(3),
                "rate": float(m.group(4)),
                "area": float(m.group(5)),
                "factors": pending,
            }
            pending = {}
            continue
        m = _STOREY_RE.match(line)
        if m:
            rec["storeys"][int(m.group(1))] = (float(m.group(2)), float(m.group(3)))
            continue
        if line.startswith("INITIAL_COST "):
            rec["initial_cost"] = float(line.split()[1])
        elif line.startswith("FAIL "):
            rec["fails"].append(line[len("FAIL "):])
        elif line.startswith("SCORE "):
            rec["score"] = float(line.split()[1])
    return out


def native_eval(path: Path, fit: fitness.Fitness) -> dict:
    root = dom.load(str(path))
    fails: list[str] = []
    fit.preprocess_building(root)
    dom.merge_divided(root)
    graphs = graph.build_graphs(root)

    rec: dict = {"leaves": {}, "storeys": {}, "fails": fails,
                 "initial_cost": fit.plot_cost(root)}
    for li, lvl in enumerate(dom.levels(root)):
        se = fit.process_storey(lvl, graphs[li], li, fails.append)
        rec["storeys"][li] = (se.cost, se.value)
        for le in se.leaves:
            rec["leaves"][(le.level, le.id)] = {
                "type": le.type, "rate": le.rate, "area": le.area,
                "factors": le.factors,
            }
    return rec


def close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=1e-12)


def main() -> int:
    files = sorted(p.name for p in CORPUS.glob("*.dom"))
    conf, cost = fitness.load_config(CORPUS)
    fit = fitness.Fitness(conf, cost)
    oracle = run_oracle(files)

    n_leaves = n_factors = 0
    bad: dict[str, list[str]] = defaultdict(list)

    for name in files:
        o = oracle[name]
        n = native_eval(CORPUS / name, fit)

        if not close(o["initial_cost"], n["initial_cost"]):
            bad[name].append(
                f"initial cost {o['initial_cost']} != {n['initial_cost']}")

        if set(o["leaves"]) != set(n["leaves"]):
            bad[name].append(
                f"leaf sets differ: oracle-only {sorted(set(o['leaves']) - set(n['leaves']))}, "
                f"native-only {sorted(set(n['leaves']) - set(o['leaves']))}")
        for key in sorted(set(o["leaves"]) & set(n["leaves"])):
            ol, nl = o["leaves"][key], n["leaves"][key]
            n_leaves += 1
            for fld in ("rate", "area"):
                if not close(ol[fld], nl[fld]):
                    bad[name].append(f"leaf {key} {fld}: {ol[fld]} != {nl[fld]}")
            if ol["type"] != nl["type"]:
                bad[name].append(f"leaf {key} type: {ol['type']} != {nl['type']}")
            for fac, ov in ol["factors"].items():
                n_factors += 1
                nv = nl["factors"].get(fac)
                if nv is None or not close(ov, nv):
                    bad[name].append(f"leaf {key} {fac}: {ov} != {nv}")

        for li, (oc, ov) in o["storeys"].items():
            nc, nv = n["storeys"].get(li, (None, None))
            if nc is None or not close(oc, nc):
                bad[name].append(f"storey {li} cost: {oc} != {nc}")
            if nv is None or not close(ov, nv):
                bad[name].append(f"storey {li} value: {ov} != {nv}")

        o_fails = sorted(f for f in o["fails"] if _LEAF_FAIL_RE.search(f))
        n_fails = sorted(n["fails"])
        if o_fails != n_fails:
            bad[name].append(
                f"leaf fails differ:\n    oracle: {o_fails}\n    native: {n_fails}")

    for name in sorted(bad):
        print(f"MISMATCH {name}")
        for msg in bad[name]:
            print(f"  {msg}")
    print(f"\n{len(files)} files, {n_leaves} leaves, {n_factors} factors compared; "
          f"{len(bad)} files with mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

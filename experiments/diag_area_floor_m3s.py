"""m3s / DESIGN.md §39.57 -- does the internal-area floor catch anything the
per-room quality_size checks miss?  Run from the repo root.  Prints one row per
artefact at the objective in OBJ (default: the live one)."""
import os, sys
from pathlib import Path
sys.path.insert(0, os.path.abspath("src"))
from homemaker_layout import dom as dom_mod, geometry
from homemaker_layout.fitness import (
    Fitness, load_config, gaussian, _generic_class, FAIL_THRESHOLD)

ROOT = os.getcwd()
rows = []
for line in open("experiments/results/coldstart_baseline.tsv"):
    p = line.rstrip("\n").split("\t")
    if p[0] == os.environ.get("OBJ", "c836457+orth"):
        rows.append((p[1], p[2], p[-1]))
rows.sort()

hdr = (f"{'programme':<16}{'s':<3}{'internal':>9}{'circ':>8}{'rooms':>8}"
       f"{'req':>8}{'g1.2':>8}{'g1.0':>8}{'minQS':>8}{'prodQS':>9}{'sizefails':>10}")
print(hdr); print("-"*len(hdr))
for prog, seed, dom in rows:
    d = Path(ROOT) / "examples" / prog
    os.chdir(d)
    conf, cost = load_config(Path.cwd())
    ev = Fitness(conf, cost)
    root = dom_mod.load(dom)
    geometry.clear_cache()

    # global rule inputs
    min_required = 0.0
    for req in (ev._programme or {}).values():
        if dom_mod.is_generic(req.code):
            continue
        if req.size > 0:
            min_required += req.size * req.count
    internal = ev._area_internal(root)

    circ = 0.0; rooms_only = 0.0
    qs = []
    nfail = 0
    for lvl in dom_mod.levels(root):
        for leaf in lvl.leaves():
            if dom_mod.is_outside(leaf):
                continue
            a = geometry.area(leaf)
            if _generic_class(leaf) == "c":
                circ += a
            else:
                rooms_only += a
                f = ev.quality_size(leaf)
                qs.append(f)
                if f < FAIL_THRESHOLD:
                    nfail += 1
    prod = 1.0
    for f in qs: prod *= f
    def g(mult):
        mr = min_required * mult
        if internal < mr and mr > 0:
            return gaussian(internal, 1.0, mr, mr*0.15)
        return 1.0
    os.chdir(ROOT)
    print(f"{prog:<16}{seed:<3}{internal:>9.1f}{circ:>8.1f}{rooms_only:>8.1f}"
          f"{min_required:>8.1f}{g(1.2):>8.3f}{g(1.0):>8.3f}"
          f"{(min(qs) if qs else 1):>8.3f}{prod:>9.4f}{nfail:>10d}")

"""Per-room-spec satisfiability audit of `patterns.config` targets.

Evidence for `homemaker-py-2v1`/`ssz`/`tdp` (DESIGN.md §38/§39). The corpus
configs were estimated years ago on the principle that exact values do not
matter for getting the engine working. This asks the opposite question: **does
any individual room spec make itself impossible to satisfy?**

For one room code, model the leaf as a rectangle of area ``A`` and aspect
``r = w/h >= 1`` (``h`` is `length_narrowest`, the width metric). The
FAIL_THRESHOLD-inverted bounds come from the already-validated
``shapecurve.leaf_constraints`` (§37.2), so this is not a reimplementation of
the Gaussians:

* size        ``amin <= A <= amax``
* width       ``h >= wmin``          =>  ``r <= A / wmin^2``
* proportion  ``r <= rmax``
* crinkliness ``L_exposed >= A / (X * height)`` with ``X = 1.6202`` (§38.3)

The last one depends on how much of the leaf's boundary is external, which is a
*placement* property, not a spec property — so the audit reports the **minimum
number of exposed sides** each spec needs. A spec needing 2 adjacent sides is
demanding a corner; a rectangular storey has only four corners, so a programme
wanting more corner rooms than the plot has corners is over-subscribed before
the search starts.

Usage::

    python experiments/audit_programme_config.py
    python experiments/audit_programme_config.py examples/harbor-house --verbose
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import yaml

from homemaker_layout import dom, fitness, programme, shapecurve
from homemaker_layout.dom import Node

# 1/crink bounds from §38.3; recomputed from the live conf, never hard-coded.
def crink_bounds(fit: fitness.Fitness, circulation: bool = False) -> tuple[float, float]:
    key = "uncrinkliness_circulation" if circulation else "uncrinkliness"
    target, sigma = fit.conf(key)
    k = math.sqrt(-2 * sigma * sigma
                  * math.log(fitness.FAIL_THRESHOLD) / math.log(fitness._E))
    return target + k, max(1e-12, target - k)


# Exposure patterns, cheapest first: name -> exposed length given (w, h), w >= h.
EXPOSURE = [
    ("1 short side", lambda w, h: h),
    ("1 long side", lambda w, h: w),
    ("2 adjacent (corner)", lambda w, h: w + h),
    ("2 opposite long", lambda w, h: 2 * w),
    ("3 sides", lambda w, h: 2 * h + w),
    ("4 sides (freestanding)", lambda w, h: 2 * (w + h)),
]


def _synthetic_leaf(code: str) -> Node:
    """A bare typed leaf — ``leaf_constraints`` reads only its type/flags."""
    return Node(node=[[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0]], type=code)


def audit_code(fit: fitness.Fitness, code: str, height: float,
               grid: int = 240) -> dict:
    """Feasibility of one room spec, and the exposure it needs."""
    bounds = shapecurve.leaf_constraints(fit, _synthetic_leaf(code))
    amin, amax, wmin, rmax = bounds.amin, bounds.amax, bounds.wmin, bounds.rmax
    if not math.isfinite(amax):
        amax = max(amin * 4, 200.0)

    hi, lo = crink_bounds(fit, circulation=code[:1].lower() == "c")
    areas = np.linspace(max(amin, 1e-6), amax, grid)
    ratios = np.linspace(1.0, max(rmax, 1.0), grid)
    A, R = np.meshgrid(areas, ratios, indexing="ij")
    W, H = np.sqrt(A * R), np.sqrt(A / R)

    swp = (H >= wmin) & (R <= rmax)          # size is satisfied by construction
    result = {"code": code, "amin": amin, "amax": amax, "wmin": wmin,
              "rmax": rmax, "swp": bool(swp.any()), "needs": None,
              "swp_only_at": None}
    if not result["swp"]:
        return result

    # smallest square-ish area that satisfies width at r=1, for the report
    result["swp_only_at"] = float(max(amin, wmin * wmin))

    for name, length_of in EXPOSURE:
        L = length_of(W, H)
        crink_ok = (L >= A / (hi * height)) & (L <= A / (lo * height))
        if bool((swp & crink_ok).any()):
            result["needs"] = name
            break
    return result


# The SEMANTIC (usage) prefixes. Unlike the generic types these classify
# PROGRAMME CODES by first letter, and they are still prefix-based by design —
# it is how Urb encodes room usage. graph.has_circulation strips edges based on
# them (a "bedroom" loses its edges to living/kitchen/bedroom/toilet; a "toilet"
# loses its edges to outside/living/kitchen/toilet), and fitness.access /
# public-access read them too. So a code that picks one up by accident is
# silently given another room's connectivity rules.
USAGE_PREFIXES = {"b": "bedroom", "t": "toilet", "l": "living", "k": "kitchen"}


def audit_usage(progdir: str) -> list[tuple[str, str, str]]:
    """Report which programme codes acquire a usage class from their spelling."""
    reqs = programme.load_programme_dir(progdir)
    hits = [(c, USAGE_PREFIXES[c[:1].lower()], reqs[c].name)
            for c in sorted(reqs) if c[:1].lower() in USAGE_PREFIXES]
    if not hits:
        print(f"=== {Path(progdir).name}: no code carries a usage prefix\n")
        return []
    print(f"=== {Path(progdir).name}: {len(hits)} code(s) carry a usage prefix")
    for code, usage, name in hits:
        # crude but useful: does the human-readable name agree with the usage?
        agrees = usage[:3] in (name or "").lower() or {
            "toilet": ("wc", "bathroom", "toilet", "ensuite"),
            "bedroom": ("bedroom",), "living": ("living", "lounge"),
            "kitchen": ("kitchen",)}.get(usage, ())
        ok = any(w in (name or "").lower() for w in (
            agrees if isinstance(agrees, tuple) else (usage,)))
        flag = "" if ok else "   <-- name disagrees with the usage it is given"
        print(f"  {code:<6} -> {usage:<8} (name: {name}){flag}")
    print()
    return hits


def audit_namespace(progdir: str) -> int:
    """Report programme codes that collide with the generic type prefixes.

    Urb's type system is prefix-based — a type starting with ``c`` is
    circulation, ``o``/``s`` is outside — and programme codes live in the *same
    namespace*. So a room code that happens to start with one of those letters
    is silently reinterpreted as a generic type. Three separate consequences,
    none of them announced anywhere in the output:

    1. ``graph.check_space_counts`` **skips the code entirely**
       (``if code[0].lower() in ("c", "o", "s"): continue``) — the room is never
       required, never counted, and never produces a missing/too-many failure.
    2. ``Fitness.get_space_params`` returns the generic
       ``*_circulation``/``*_outside`` parameters *before* consulting the
       programme, so declared size/width/proportion are overridden.
    3. ``dom.is_circulation``/``is_outside`` become true, changing the leaf's
       value rate, its crinkliness treatment, and whether it supplies daylight
       to its neighbours.
    """
    reqs = programme.load_programme_dir(progdir)
    conf, cost = fitness.load_config(progdir)
    fit = fitness.Fitness(conf, cost)
    spaces = conf.get("spaces") or {}

    hits = [c for c in sorted(reqs) if c[:1].lower() in ("c", "o", "s")]
    total = sum(r.count for r in reqs.values())
    if not hits:
        print(f"=== {Path(progdir).name}: namespace clean "
              f"({len(reqs)} codes / {total} instances)\n")
        return 0

    skipped = sum(reqs[c].count for c in hits)
    print(f"=== {Path(progdir).name}: {len(hits)} code(s) collide with the "
          f"generic c/o/s type prefixes")
    print(f"    {skipped} of {total} room instances ({100 * skipped / total:.0f}%) "
          f"are SILENTLY OPTIONAL — check_space_counts skips them\n")
    for code in hits:
        spec = spaces.get(code, {})
        leaf = _synthetic_leaf(code)
        print(f"  {code}  \"{reqs[code].name}\"  (count {reqs[code].count})")
        for param in ("size", "width", "proportion"):
            declared = spec.get(param)
            effective = fit.get_space_params(code, param)
            flag = "" if declared == effective else "   <-- OVERRIDDEN"
            print(f"      {param:<11} declared={str(declared):<16} "
                  f"effective={effective}{flag}")
        print(f"      is_circulation={dom.is_circulation(leaf)}  "
              f"is_outside={dom.is_outside(leaf)}  "
              f"value_rate={fit.value_rate(leaf)} (inside={fit.conf('value_inside')})")
    print()
    return skipped


def audit(progdir: str, verbose: bool) -> tuple[int, int]:
    reqs = programme.load_programme_dir(progdir)
    conf, cost = fitness.load_config(progdir)
    fit = fitness.Fitness(conf, cost)
    seed = yaml.safe_load(open(f"{progdir}/init.dom"))
    height = seed.get("height") or 3.0

    print(f"=== {Path(progdir).name}   (height {height} m)")
    hdr = f"  {'code':<7}{'count':<7}{'area ok':<18}{'min width':<11}{'max aspect':<12}needs"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    impossible = corner_demand = 0
    for code in sorted(reqs) + ["C", "O"]:
        count = reqs[code].count if code in reqs else 0
        r = audit_code(fit, code, height)
        if not r["swp"]:
            verdict = "IMPOSSIBLE (size/width/proportion contradict)"
            impossible += max(count, 1)
        elif r["needs"] is None:
            verdict = "IMPOSSIBLE even fully exposed (crinkliness)"
            impossible += max(count, 1)
        else:
            verdict = r["needs"]
            if "corner" in verdict or "opposite" in verdict or "3 sides" in verdict \
                    or "4 sides" in verdict:
                corner_demand += max(count, 1)
        area_col = "%.1f-%.1f m2" % (r["amin"], r["amax"])
        width_col = "%.2f m" % r["wmin"]
        aspect_col = "%.2f" % r["rmax"]
        count_col = str(count) if count else "-"
        print(f"  {code:<7}{count_col:<7}{area_col:<18}"
              f"{width_col:<11}{aspect_col:<12}{verdict}")

    print(f"\n  room instances that are impossible as specified : {impossible}")
    print(f"  room instances requiring >=2 exposed sides       : {corner_demand}"
          f"   (a rectangular storey has 4 corners)\n")
    return impossible, corner_demand


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("progdir", nargs="?", default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    dirs = [args.progdir] if args.progdir else [
        "examples/harbor-house", "examples/maple-court",
        "examples/health-centre", "examples/programme-house"]
    print("### namespace collisions (generic C/O/S structural types)\n")
    for d in dirs:
        audit_namespace(d)
    print("### usage prefixes (b/t/l/k -- still prefix-based, by design)\n")
    for d in dirs:
        audit_usage(d)
    print("### per-room-spec satisfiability\n")
    for d in dirs:
        audit(d, args.verbose)


if __name__ == "__main__":
    main()

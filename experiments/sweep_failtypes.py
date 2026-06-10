"""Equal-offset (perpendicular) warm-start sweep with failure-type histogram.

Isolates which fitness constraints break when we move equal-offset cuts to fix
programme room sizes. Equal offset (a == b) keeps walls perpendicular on
near-rectangular plots, so any regression here is NOT a perpendicularity
artifact -- it tells us what sizing genuinely trades against.
"""

import collections
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from homemaker import dom, oracle, programme, solver  # noqa: E402

URB = Path("/home/bruno/src/urb")
EX = URB / "examples/programme-house"


def classify(line: str) -> str:
    s = line.strip().lower()
    if not s or s == "---" or s.startswith(("- ", "type:", "issue:", "actual:", "min:")):
        # structured YAML fails: pull the keyword if present
        if "staircase" in s:
            return "staircase"
        if "access" in s or "inaccessible" in s:
            return "access"
        if not s or s == "---":
            return ""
    for key in ("perpendicular", "crinkliness", "width", "proportion", "size",
                "adjacent", "access", "inaccessible", "level", "staircase"):
        if key in s:
            return "adjacency" if key == "adjacent" else (
                "access" if key == "inaccessible" else key)
    return "other"


def tally(fails: str, counter: collections.Counter) -> None:
    for line in fails.splitlines():
        t = classify(line)
        if t:
            counter[t] += 1


def main() -> None:
    scratch = Path(__file__).resolve().parents[1] / "scratch"
    scratch.mkdir(exist_ok=True)
    shutil.copy(EX / "patterns.config", scratch / "patterns.config")
    targets = programme.load_programme(str(EX / "patterns.config"))

    before = collections.Counter()
    after = collections.Counter()
    doms = sorted(p for p in EX.glob("*.dom") if p.stem != "init")

    for src in doms:
        shutil.copy(src, scratch / "orig.dom")
        s0 = oracle.score(scratch / "orig.dom", URB)
        root = dom.load(str(src))
        solver.solve_ratios(  # equal offset, shape-aware (strong width/proportion)
            root, targets, strip=False, perpendicular=True,
            weight_width=3.0, weight_proportion=2.0, min_width_generic=1.5,
        )
        dom.dump(root, str(scratch / "ref.dom"))
        s1 = oracle.score(scratch / "ref.dom", URB)
        tally(s0.fails, before)
        tally(s1.fails, after)

    types = sorted(set(before) | set(after), key=lambda t: -(after[t] - before[t]))
    print(f"{'failure type':16s} {'before':>8s} {'after':>8s} {'delta':>8s}")
    for t in types:
        print(f"{t:16s} {before[t]:8d} {after[t]:8d} {after[t] - before[t]:+8d}")
    print(f"{'TOTAL':16s} {sum(before.values()):8d} {sum(after.values()):8d} "
          f"{sum(after.values()) - sum(before.values()):+8d}")


if __name__ == "__main__":
    main()

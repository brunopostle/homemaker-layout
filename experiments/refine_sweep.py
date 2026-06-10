"""Population sweep: warm-start refine every evolved candidate and tally results.

For each real .dom in the example dir, score it, run the solver as a geometry
optimiser (warm-start, no strip), and re-score. Reports how often bottom-up
sizing improves vs regresses total fitness, plus aggregate fail-count change.

This is a breadth check on the solver-as-optimiser role; raw fitness is still
confounded by the 0.5^n failure cliff and any topological defects, so the
fail-count and per-candidate detail matter as much as the win/loss tally.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from homemaker import dom, oracle, programme, solver  # noqa: E402

URB = Path("/home/bruno/src/urb")
EX = URB / "examples/programme-house"


def _is_candidate(p: Path) -> bool:
    # real designs: 32-hex hashes or candidate-NNN; skip init and our scratch
    name = p.stem
    return name not in {"init", "original", "roundtrip", "solved", "refined"}


def main() -> None:
    scratch = Path(__file__).resolve().parents[1] / "scratch"
    scratch.mkdir(exist_ok=True)
    shutil.copy(EX / "patterns.config", scratch / "patterns.config")
    targets = programme.load_programme(str(EX / "patterns.config"))

    doms = sorted(p for p in EX.glob("*.dom") if _is_candidate(p))
    win = loss = tie = 0
    fails_before = fails_after = 0
    rows = []
    for src in doms:
        try:
            shutil.copy(src, scratch / "orig.dom")
            s0 = oracle.score(scratch / "orig.dom", URB)
            root = dom.load(str(src))
            # gentlest refiner: nudge cut POSITIONS for programme-room area only,
            # keep evolved cut angles and leave circulation/shape untouched.
            solver.solve_ratios(
                root, targets, strip=False, perpendicular=False,
                weight_width=0.0, weight_proportion=0.0, min_width_generic=0.0,
            )
            dom.dump(root, str(scratch / "ref.dom"))
            s1 = oracle.score(scratch / "ref.dom", URB)
        except Exception as e:  # noqa: BLE001
            rows.append(f"  {src.name:40s} ERROR {e}")
            continue
        fails_before += s0.n_fails
        fails_after += s1.n_fails
        if s1.fitness > s0.fitness * 1.001:
            win += 1
            mark = "＋"
        elif s1.fitness < s0.fitness * 0.999:
            loss += 1
            mark = "－"
        else:
            tie += 1
            mark = "="
        rows.append(
            f"  {mark} {src.name:40s} {s0.fitness:.4g} -> {s1.fitness:.4g}"
            f"  fails {s0.n_fails}->{s1.n_fails}"
        )

    print("\n".join(rows))
    n = win + loss + tie
    print(f"\n{n} candidates: {win} improved, {loss} regressed, {tie} tied")
    print(f"total fails: {fails_before} -> {fails_after}")


if __name__ == "__main__":
    main()

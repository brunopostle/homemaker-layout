"""Phase-1 fitness oracle: score ``.dom`` files via Urb's ``urb-fitness.pl``.

This is the only throwaway component. It shells out to the Perl evaluator so we
can validate the Python search core against the trusted fitness before porting
fitness to Python (Phase 3). ``urb-fitness.pl`` reads ``patterns.config`` from
its working directory, so the ``.dom`` must live beside the programme config.

``urb-fitness.pl`` accepts many ``.dom`` paths per invocation; ``score_batch``
exploits this so the ~0.65 s Perl startup amortises across a generation
(DESIGN.md §4.6: ~0.99 s/dom batched vs ~1.65 s/dom single). Note the Perl
script computes the occlusion field from the *first* dom in a batch and reuses
it for the rest; ``experiments/bench_batch_oracle.py`` verifies this leaves
corpus scores identical to single-file calls.

Two flavours of Urb-side nondeterminism to know about (both from Perl's
per-process hash-order randomisation, neither a batching artifact): ``.fails``
line *order* varies between runs (use ``Score.fail_lines``), and the score
itself can flip by ~1 ULP. Compare fitness with a relative tolerance
(``math.isclose(..., rel_tol=1e-12)``), never ``==``.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import yaml

DEFAULT_URB_ROOT = Path("/home/bruno/src/urb")


def _structured_fail_to_str(f: dict) -> str:
    """Convert a structured failure dict (llm-agent-mcp branch format) to the
    plain-text string that master urb/ProgrammeDriven.pm would have emitted."""
    t = f.get("type", "")
    if t == "level":
        return f"{f['space']} on wrong level (level {f['actual']}, expected {f['required']})"
    if t == "missing":
        code = f["code"]
        c = f.get("constraint")
        if c == "size":
            return f"missing {code}: would need size check"
        if c == "width":
            return f"missing {code}: would need width check"
        if c == "proportion":
            return f"missing {code}: would need proportion check"
        if c == "adjacency":
            return f"missing {code}: would need adjacency to {f.get('target', '')}"
        if c == "level":
            return f"missing {code}: would need to be on level {f['required']}"
        if c == "vertical":
            return f"missing {code}: would need connection to {f.get('target', '')} below"
        if f.get("critical"):
            return f"missing required space: {code} (critical)"
        return f"missing required space: {code}"
    if t == "count":
        return f"too many spaces: {f['code']} (found {f['actual']}, expected {f['expected']})"
    if t == "adjacency":
        return f"{f['node']} ({f['space']}) not adjacent to {f['target']}"
    if t == "vertical":
        return f"{f['space']} not connected to {f['target']} below"
    if t == "staircase":
        issue = f.get("issue", "")
        if issue == "volume":
            return "staircase volume"
        if issue == "count":
            actual = f.get("actual", 0)
            if "min" in f:
                return f"too few stairs ({actual}, min {f['min']})"
            if "max" in f:
                return f"too many stairs ({actual}, max {f['max']})"
    if t == "storey":
        if f.get("issue") == "limit":
            return "storey limit"
        if f.get("issue") == "minimum":
            return "storey minimum"
    if t == "access" and f.get("issue") == "no_outside_public_access":
        return "no outside public access"
    return str(f)


def _parse_fails(text: str) -> list[str]:
    """Parse a .fails file that may contain a YAML block followed by plain-text
    lines (urb branch format) or only plain-text lines (master format)."""
    text = text.strip()
    if not text:
        return []
    if not text.startswith("---"):
        return [line.strip() for line in text.splitlines() if line.strip()]

    # Split YAML block from trailing plain-text lines: YAML list items start
    # with "- " or are indented; once we hit a non-indented, non-dash line
    # that isn't blank or the "---" marker, the YAML part has ended.
    yaml_lines: list[str] = []
    plain_lines: list[str] = []
    in_yaml = True
    for line in text.splitlines():
        if in_yaml:
            stripped = line.strip()
            if not stripped or stripped == "---" or stripped.startswith("-") or line[:1] == " ":
                yaml_lines.append(line)
            else:
                in_yaml = False
                plain_lines.append(stripped)
        else:
            if line.strip():
                plain_lines.append(line.strip())

    result: list[str] = []
    try:
        doc = yaml.safe_load("\n".join(yaml_lines))
        if isinstance(doc, list):
            for item in doc:
                if isinstance(item, dict):
                    result.append(_structured_fail_to_str(item))
    except yaml.YAMLError:
        pass
    result.extend(plain_lines)
    return result


@dataclass
class Score:
    fitness: float
    fails: str  # raw .fails content (YAML and/or plain lines)

    @property
    def fail_lines(self) -> tuple[str, ...]:
        """Failure messages as a sorted tuple — Perl's per-process hash-order
        randomisation shuffles the raw ``.fails`` line order between runs, so
        comparisons must be order-insensitive."""
        return tuple(sorted(_parse_fails(self.fails)))

    @property
    def n_fails(self) -> int:
        return len(self.fail_lines)


def score_batch(
    dom_paths: Sequence[str | Path], urb_root: str | Path = DEFAULT_URB_ROOT
) -> list[Score]:
    """Score many ``.dom`` files in one ``urb-fitness.pl`` invocation.

    All files must live in the same directory (the working directory, where
    ``patterns.config`` is found). Results are returned in input order.
    """
    paths = [Path(p).resolve() for p in dom_paths]
    if not paths:
        return []
    cwd = paths[0].parent
    for p in paths:
        if p.parent != cwd:
            raise ValueError(f"batch spans directories: {p} not in {cwd}")
        Path(f"{p}.score").unlink(missing_ok=True)
        Path(f"{p}.fails").unlink(missing_ok=True)

    urb_root = Path(urb_root).resolve()
    env = {**os.environ, "DEBUG": "1", "URB_NO_OCCLUSION": "1"}
    proc = subprocess.run(
        ["perl", f"-I{urb_root}/lib", str(urb_root / "bin" / "urb-fitness.pl")]
        + [p.name for p in paths],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )

    results = []
    for p in paths:
        score_file = Path(f"{p}.score")
        if not score_file.exists():
            raise RuntimeError(
                f"urb-fitness.pl produced no score for {p}\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        fails_file = Path(f"{p}.fails")
        results.append(
            Score(
                fitness=float(score_file.read_text().strip()),
                fails=fails_file.read_text() if fails_file.exists() else "",
            )
        )
    return results


def score(dom_path: str | Path, urb_root: str | Path = DEFAULT_URB_ROOT) -> Score:
    return score_batch([dom_path], urb_root)[0]

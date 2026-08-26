"""Write the agreed `usage:` attribute into every corpus `patterns.config`.

One-shot migration for `homemaker-py-sel` (DESIGN.md §39.7). Reads the reviewed
assignments in ``usage_map_proposal.yaml`` and inserts a ``usage:`` line into
each space definition, in place, preserving comments and formatting (the file
is edited as text, not round-tripped through the YAML emitter, which would strip
every comment in the corpus).

Idempotent: a space that already declares ``usage:`` is left alone unless
``--force`` is given, in which case the existing value is rewritten.

Usage::

    python experiments/migrate_usage_key.py --check     # dry run, report only
    python experiments/migrate_usage_key.py             # apply
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

PROPOSAL = Path(__file__).with_name("usage_map_proposal.yaml")
CORPUS = Path(__file__).resolve().parent.parent / "examples"


def load_assignments() -> dict[str, str]:
    """code -> usage, from the reviewed proposal (its top-level keys ARE the
    usage classes; every other key in the file is a comment)."""
    doc = yaml.safe_load(PROPOSAL.read_text()) or {}
    out: dict[str, str] = {}
    for usage, codes in doc.items():
        for code in (codes or {}):
            out[code] = usage
    return out


def migrate(path: Path, assign: dict[str, str], check: bool,
            force: bool) -> tuple[int, int, list[str]]:
    """Insert ``usage:`` as the first property of each space definition.

    Returns ``(written, skipped, unknown_codes)``. Edits the file as text so the
    corpus keeps its comments and layout.
    """
    text = path.read_text()
    spaces = (yaml.safe_load(text) or {}).get("spaces") or {}
    space_key = re.compile(r"^  ([A-Za-z_][\w-]*):\s*$")

    written = skipped = 0
    unknown: list[str] = []
    out: list[str] = []

    for line in text.splitlines(keepends=True):
        m = space_key.match(line)
        code = m.group(1) if m and m.group(1) in spaces else None

        # drop a pre-existing usage line when rewriting
        if force and re.match(r"^    usage:\s", line):
            continue

        out.append(line)
        if code is None:
            continue
        usage = assign.get(code)
        if usage is None:
            unknown.append(code)
        elif "usage" in spaces[code] and not force:
            skipped += 1
        else:
            out.append(f"    usage: {usage}\n")
            written += 1

    if not check and written:
        path.write_text("".join(out))
    return written, skipped, unknown


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="dry run")
    ap.add_argument("--force", action="store_true",
                    help="rewrite a usage: that is already present")
    args = ap.parse_args()

    assign = load_assignments()
    print(f"{len(assign)} code -> usage assignments loaded from "
          f"{PROPOSAL.name}\n")

    total_unknown: list[tuple[str, str]] = []
    for cfg in sorted(CORPUS.glob("*/patterns.config")):
        written, skipped, unknown = migrate(cfg, assign, args.check, args.force)
        total_unknown += [(cfg.parent.name, c) for c in unknown]
        verb = "would write" if args.check else "wrote"
        print(f"  {cfg.parent.name:<20} {verb} {written:>3}, "
              f"already present {skipped:>3}"
              + (f", UNKNOWN {unknown}" if unknown else ""))

    if total_unknown:
        print(f"\n{len(total_unknown)} code(s) have no assignment — "
              "add them to the proposal first:", file=sys.stderr)
        for d, c in total_unknown:
            print(f"    {d}: {c}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Rename harbor-house's colliding room codes in existing `.dom` files.

`homemaker-py-ju3` (DESIGN.md §39.2) renamed four harbor-house programme codes
that collided with Urb's reserved generic type prefixes (``c`` = circulation,
``o``/``s`` = outside). Any `.dom` produced **before** that change still carries
the old leaf types, and will score differently against the renamed programme —
the old types are no longer declared, so every affected leaf reads as an
unmatched generic instead of the room it was.

This matters for artefacts not checked in at the time, notably the
``evolved-3M*.dom`` harbor-house runs.

Mapping (chosen so each new prefix is unused in harbor-house *and* carries no
adjacency semantics of its own — ``l``/``k``/``b``/``t`` do, ``f``/``a``/``g``
do not — while preserving the original prefix-sharing structure, i.e. the two
storage codes still share one prefix):

    cr1 -> fr1   Common Room with Fireplace
    of  -> ao    Staff Office
    st1 -> gs1   Ground Floor Storage
    st2 -> gs2   First Floor Storage

Usage::

    python experiments/migrate_ju3_rename.py path/to/evolved-3M.dom [...]
    python experiments/migrate_ju3_rename.py --check path/to/*.dom
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RENAMES = {"cr1": "fr1", "of": "ao", "st1": "gs1", "st2": "gs2"}


def migrate(path: Path, check_only: bool) -> int:
    """Rewrite ``type:`` lines in place; return the number of leaves changed."""
    text = path.read_text()
    total = 0
    for old, new in RENAMES.items():
        # Anchored to a whole `type: <code>` line so a code appearing inside a
        # name, comment or unrelated scalar is never touched.
        text, n = re.subn(rf"^(\s*type: ){re.escape(old)}\s*$", rf"\g<1>{new}",
                          text, flags=re.M)
        total += n
    if total and not check_only:
        path.write_text(text)
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--check", action="store_true",
                    help="report what would change without writing")
    args = ap.parse_args()

    stale = 0
    for path in args.paths:
        if not path.is_file():
            print(f"  {path}: NOT FOUND", file=sys.stderr)
            continue
        n = migrate(path, args.check)
        stale += bool(n)
        verb = "would rename" if args.check else "renamed"
        print(f"  {path}: {verb} {n} leaf type(s)"
              if n else f"  {path}: already current")
    if args.check and stale:
        print(f"\n{stale} file(s) still carry pre-ju3 codes.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

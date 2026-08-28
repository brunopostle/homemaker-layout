"""Declare `crinkliness:` where a space needs no window (`homemaker-py-ssz`).

One-shot migration for DESIGN.md §38.10. The compact side of the crinkliness
gaussian IS the daylight requirement, so a space that does not need daylight
says so in its own `crinkliness:` target -- there is no separate attribute.

Ruled by the project owner: everything a person occupies wants a window --
WCs and bathrooms included, reception/waiting/foyer included, offices and
consulting rooms included. Only stores, plant, records and laundry
(`usage: utility`) do not. Internal corridors do not either, but those are
generic `C` leaves with no `spaces:` entry, so they are handled by the
`uncrinkliness_circulation` key rather than here.

Edits the file as text, preserving comments and layout. Idempotent: a space
that already declares `crinkliness:` is left alone unless `--force`.

Usage::

    python experiments/migrate_crinkliness_key.py --check     # dry run
    python experiments/migrate_crinkliness_key.py             # apply
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

CORPUS = Path(__file__).resolve().parent.parent / "examples"
NO_DAYLIGHT_USAGES = {"utility"}


def migrate(path: Path, check: bool, force: bool) -> tuple[int, int]:
    text = path.read_text()
    spaces = (yaml.safe_load(text) or {}).get("spaces") or {}
    space_key = re.compile(r"^  ([A-Za-z_][\w-]*):\s*$")

    written = skipped = 0
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        m = space_key.match(line)
        code = m.group(1) if m and m.group(1) in spaces else None

        if force and re.match(r"^    crinkliness:\s", line):
            continue

        out.append(line)
        if code is None:
            continue
        c = spaces[code]
        if c.get("usage") not in NO_DAYLIGHT_USAGES:
            continue
        if "crinkliness" in c and not force:
            skipped += 1
        else:
            out.append("    crinkliness: none   # no window needed\n")
            written += 1

    if not check and written:
        path.write_text("".join(out))
    return written, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="dry run")
    ap.add_argument("--force", action="store_true",
                    help="rewrite a crinkliness: already present")
    args = ap.parse_args()

    for cfg in sorted(CORPUS.glob("*/patterns.config")):
        written, skipped = migrate(cfg, args.check, args.force)
        verb = "would declare" if args.check else "declared"
        print(f"  {cfg.parent.name:<20} {verb} crinkliness:none on {written:>2} "
              f"space(s), already present {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

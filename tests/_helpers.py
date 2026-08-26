"""Shared helpers for the test suite."""

from __future__ import annotations

# The pre-§39.7 first-character convention, kept HERE and nowhere else so that
# synthetic fixtures keep exercising what they always did while the production
# code has no prefix rule left at all (homemaker-py-sel). Tests about a specific
# usage should state it explicitly rather than rely on this.
_LEGACY_PREFIX_USAGE = {"b": "bedroom", "t": "toilet", "l": "living", "k": "kitchen"}


def with_usage(spaces: dict) -> dict:
    """Fill in a mandatory ``usage:`` for a synthetic ``spaces`` fixture.

    ``usage`` is required in real ``patterns.config`` files, but most tests care
    about size/width/collapse and not about access class. This supplies the class
    the code's first letter used to imply, so those tests are unchanged by the
    migration. An explicit ``usage`` in the fixture always wins.
    """
    return {
        code: {"usage": _LEGACY_PREFIX_USAGE.get(code[:1].lower(), "none"),
               **(spec or {})}
        for code, spec in spaces.items()
    }

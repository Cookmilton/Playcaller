"""Extract game-clock hints from ESPN summary play text (best-effort)."""

from __future__ import annotations

import re

_CLOCK_PREFIX = re.compile(r"^\s*\((?P<mm>\d{1,2}):(?P<ss>\d{2})\)\s*")


def clock_seconds_remaining_in_period_from_text(text: str | None) -> int | None:
    """
    ESPN often prefixes plays with ``(M:SS)`` as clock **within the quarter**.

    Returns seconds remaining in the period (0–900 for regulation), or ``None``
    if no prefix is found or parsing fails.
    """
    if not text:
        return None
    m = _CLOCK_PREFIX.match(text)
    if not m:
        return None
    try:
        mm = int(m.group("mm"))
        ss = int(m.group("ss"))
    except ValueError:
        return None
    if ss >= 60 or mm > 15:
        return None
    return mm * 60 + ss

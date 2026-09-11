"""Situation-aware play WHY text (predictor/explanation; not UI)."""

from __future__ import annotations

import re
from typing import Any

_TWO_MINUTE_RE = re.compile(r"two[\s-]?minute|2[\s-]?minute", re.IGNORECASE)


def clock_matches_two_minute(ctx: Any) -> bool:
    """True when the (already derived) mode or the clock is a two-minute situation."""
    mode = str(getattr(ctx, "game_mode", "") or "").strip()
    if mode == "two_minute":
        return True
    try:
        quarter = int(getattr(ctx, "quarter", 0) or 0)
        seconds = int(getattr(ctx, "seconds_remaining", 0) or 0)
    except (TypeError, ValueError):
        return False
    return quarter in (2, 4) and seconds <= 120


def situation_aware_why(why: Any, ctx: Any) -> str:
    """
    Keep clock-dependent WHY clauses only when the clock matches.

    Catalog copy such as ``two-minute boundary throw`` is dropped at Q1 15:00 and
    other non-two-minute snaps. Does not mutate library dicts.
    """
    text = str(why or "").strip()
    if not text or clock_matches_two_minute(ctx):
        return text
    kept: list[str] = []
    for part in text.split(";"):
        clause = part.strip()
        if not clause:
            continue
        if _TWO_MINUTE_RE.search(clause):
            continue
        kept.append(clause)
    return "; ".join(kept)

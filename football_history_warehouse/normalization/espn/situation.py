"""Best-effort down/distance extraction from free-text descriptions."""

from __future__ import annotations

import re

_DOWN_DIST = re.compile(r"(?P<dn>[1-4])(?:st|nd|rd|th)\s*&\s*(?P<dist>\d+)", re.IGNORECASE)


def down_distance_from_description(text: str | None) -> tuple[int | None, int | None]:
    """Parse patterns like ``2nd & 7`` when present in the play string."""
    if not text:
        return None, None
    m = _DOWN_DIST.search(text)
    if not m:
        return None, None
    try:
        d = int(m.group("dn"))
        dist = int(m.group("dist"))
    except ValueError:
        return None, None
    if dist > 99:
        return None, None
    return d, dist

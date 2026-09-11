"""Parse ESPN event / competition timestamps into an honest ``YYYY-MM-DD`` (or None)."""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

_ISO_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def calendar_date_from_espn_iso(raw: Any) -> Optional[str]:
    """UTC calendar date from an ESPN ISO-8601 timestamp. Unknown → None (never invent a date)."""
    m = _ISO_DATE_PREFIX.match(str(raw or "").strip())
    if not m:
        return None
    return m.group(1)


def resolve_espn_game_date(
    summary_payload: Optional[Mapping[str, Any]],
    scoreboard_payload: Optional[Mapping[str, Any]],
    *,
    event_id: str,
) -> Optional[str]:
    """Prefer the scoreboard event matching ``event_id``, then summary header / competition."""
    eid = str(event_id or "").strip()
    blobs: list[Any] = []
    if isinstance(scoreboard_payload, Mapping):
        for ev in scoreboard_payload.get("events") or []:
            if not isinstance(ev, Mapping):
                continue
            if eid and str(ev.get("id") or "").strip() != eid:
                continue
            blobs.append(ev.get("date"))
            comps = ev.get("competitions") or []
            if comps and isinstance(comps[0], Mapping):
                blobs.append(comps[0].get("date"))
            if eid:
                break
    if isinstance(summary_payload, Mapping):
        header = summary_payload.get("header")
        if isinstance(header, Mapping):
            blobs.append(header.get("date"))
            comps = header.get("competitions") or []
            if comps and isinstance(comps[0], Mapping):
                blobs.append(comps[0].get("date"))
    for blob in blobs:
        parsed = calendar_date_from_espn_iso(blob)
        if parsed:
            return parsed
    return None

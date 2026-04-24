"""
Authoritative + fallback extraction of quarter/clock from ESPN summary JSON.

ESPN usually exposes ``status.displayClock`` and ``status.period``, but some live payloads
omit ``displayClock`` (or leave it stale) while play rows still carry ``(M:SS)`` prefixes.
This module prefers real feed fields, then last-resort play-text hints — never inventing a
full game clock without a parseable source.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from playcaller.live_data.types import ClockResolutionSource

logger = logging.getLogger(__name__)

_CLOCK_PREFIX_RE = re.compile(r"^\(\s*(\d{1,2})\s*:\s*(\d{2})\s*\)")
_QUARTER_WORD_RE = re.compile(r"\b([1-4])(?:st|nd|rd|th)\s+quarter\b", re.IGNORECASE)


def intish(v: Any) -> Optional[int]:
    """Best-effort int coercion for ESPN JSON number/string fields."""
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def parse_display_clock_seconds(display_clock: Optional[str]) -> Optional[int]:
    """Parse ESPN ``displayClock`` string (time **remaining** in the period)."""
    if not display_clock:
        return None
    s = str(display_clock).strip()
    if not s or s.lower() in ("0:00", "00:00"):
        return 0
    parts = s.replace(" ", "").split(":")
    try:
        if len(parts) == 2:
            m, sec = int(parts[0]), int(parts[1])
            return max(0, min(15 * 60, m * 60 + sec))
        if len(parts) == 1:
            return max(0, int(parts[0]))
    except ValueError:
        return None
    return None


def parse_clock_from_play_text(text: str) -> Optional[int]:
    """ESPN often prefixes play description with ``(7:05)`` = clock at snap."""
    if not text:
        return None
    m = _CLOCK_PREFIX_RE.match(str(text).strip())
    if not m:
        return None
    try:
        mm, ss = int(m.group(1)), int(m.group(2))
        if mm > 15 or ss > 59:
            return None
        return max(0, min(15 * 60, mm * 60 + ss))
    except ValueError:
        return None


def _play_text_from_row(p: Dict[str, Any]) -> str:
    tx = p.get("text")
    if isinstance(tx, dict):
        return str(tx.get("text") or "")
    return str(p.get("description") or p.get("text") or "")


def _iter_play_texts_with_source_newest_first(
    payload: Dict[str, Any],
) -> List[Tuple[str, Literal["drives.current", "drives.previous"]]]:
    """Collect (description, origin) pairs: current drive first (newest snap), then last previous drive."""
    out: List[Tuple[str, Literal["drives.current", "drives.previous"]]] = []
    drives = payload.get("drives") or {}
    cur = drives.get("current")
    if isinstance(cur, dict):
        plays = list(cur.get("plays") or [])
        for p in reversed(plays):
            if not isinstance(p, dict):
                continue
            t = _play_text_from_row(p)
            if t:
                out.append((t, "drives.current"))
    prev = drives.get("previous")
    if isinstance(prev, list) and prev:
        last_drv = prev[-1]
        if isinstance(last_drv, dict):
            for p in reversed(list(last_drv.get("plays") or [])):
                if not isinstance(p, dict):
                    continue
                t = _play_text_from_row(p)
                if t:
                    out.append((t, "drives.previous"))
    return out


def _clock_from_status_numeric(status: Dict[str, Any]) -> Optional[int]:
    """
    Some responses expose a numeric clock (seconds). ESPN shapes vary; stay conservative.
    """
    for key in ("clock", "displayClockSeconds"):
        raw = status.get(key)
        if raw is None:
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        # Heuristic: values ~0–900 are seconds in period; larger values are suspicious.
        if 0 <= v <= 15 * 60:
            return int(v)
        if 900 < v <= 15 * 60 * 1000:
            # Possible milliseconds
            s = int(round(v / 1000.0))
            if 0 <= s <= 15 * 60:
                return s
    return None


def infer_espn_period(status: Dict[str, Any]) -> Tuple[Optional[int], Tuple[str, ...]]:
    """
    Return ESPN **period** (1–4 regulation, 5 = OT in this app's UI), plus debug notes.
    """
    notes: List[str] = []
    p = intish(status.get("period"))
    if p is not None and p >= 1:
        # Normalize wild values (defensive)
        if p > 5:
            notes.append(f"period: clamping unusual ESPN period value ({p}) to 5 (OT).")
            p = 5
        return p, tuple(notes)

    typ = status.get("type") if isinstance(status.get("type"), dict) else {}
    blob = " ".join(
        str(typ.get(k) or "")
        for k in ("detail", "shortDetail", "description", "name")
    )
    inferred = _infer_period_from_detail_blob(blob)
    if inferred is not None:
        notes.append(f"period: inferred from status.type text ({blob[:80]}…)" if len(blob) > 80 else f"period: inferred from status.type text ({blob})")
        return inferred, tuple(notes)

    return None, tuple(notes)


def _infer_period_from_detail_blob(blob: str) -> Optional[int]:
    if not blob:
        return None
    low = blob.lower()
    if "overtime" in low:
        return 5
    if re.search(r"(?<![a-z0-9])ot(?![a-z0-9])", low) and "shot" not in low:
        return 5
    if "halftime" in low or "half time" in low:
        return None
    m = _QUARTER_WORD_RE.search(blob)
    if m:
        qi = int(m.group(1))
        if 1 <= qi <= 4:
            return qi
    return None


def resolve_espn_clock_seconds(
    payload: Dict[str, Any],
    status: Dict[str, Any],
) -> Tuple[Optional[int], Tuple[str, ...], Optional[ClockResolutionSource]]:
    """
    Resolve time remaining in the **current period** (0–900 for regulation).

    Fallback order (first hit wins):
    1. ``status.displayClock``
    2. Numeric ``status.clock`` / ``displayClockSeconds`` when clearly seconds-in-period
    3. Leading ``(M:SS)`` on the most recent play description(s)

    Returns ``(seconds, debug_notes, resolution_source)`` where ``resolution_source`` is
    ``None`` only when no clock could be resolved.
    """
    notes: List[str] = []

    dc = parse_display_clock_seconds(status.get("displayClock"))
    if dc is not None:
        return dc, tuple(notes), "display_clock"

    num = _clock_from_status_numeric(status)
    if num is not None:
        notes.append("clock: from numeric status.clock / displayClockSeconds (seconds in period).")
        return num, tuple(notes), "numeric_status"

    for text, src in _iter_play_texts_with_source_newest_first(payload):
        hit = parse_clock_from_play_text(text)
        if hit is not None:
            notes.append(
                f"clock: fallback from play text ({src}, newest-first scan) — may lag true game clock by one snap."
            )
            logger.info(
                "ESPN summary: displayClock missing; using play-text clock hint (%s) from play text excerpt: %.80s",
                src,
                text,
            )
            return hit, tuple(notes), "play_text"

    notes.append(
        "clock: unknown — ESPN omitted displayClock and no (M:SS) prefix on scanned play texts; "
        "quarter clock not updated this sync."
    )
    logger.warning(
        "ESPN summary: could not resolve clock (no displayClock, no parseable play-text prefix)."
    )
    return None, tuple(notes), None


def snapshot_state_sanity_flags(
    *,
    quarter: Optional[int],
    clock_seconds: Optional[int],
    is_final: bool,
    status_detail: str,
) -> Tuple[str, ...]:
    """Non-fatal flags for audits/logging when combinations look inconsistent."""
    flags: List[str] = []
    if is_final:
        return tuple(flags)
    low = (status_detail or "").lower()
    if "delay" in low or "commercial" in low or "timeout" in low:
        flags.append("status_may_be_non_play (timeout/tv/delay)")
    if clock_seconds is None and quarter is not None and quarter >= 2:
        flags.append("clock_unknown_mid_game (quarter advanced but no clock — check feed)")
    return tuple(flags)

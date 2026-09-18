"""Copy widget-derived quarter/clock onto ``Game`` without inventing skipped ESPN fields.

Logic lives here (not in UI modules) so Streamlit pages and ``GameContext`` builders
share one skip rule: feed origin + ``LIVE_FEED_LAST_AUDIT["skipped"]`` keeps ``Game`` unset.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from playcaller.possession import generate_blocked_reason_for_possession, generate_skip_debug_reason
from playcaller.streamlit_state.keys import LIVE_FEED_LAST_AUDIT, LIVE_FEED_LAST_ORIGIN
from playcaller.streamlit_state.possession import ORIGIN_FEED

GENERATE_UNSYNCED_CLOCK_REASON = (
    "Quarter and clock not synced — confirm the board before generating."
)


def _ss_get(ss: Mapping[str, Any], key: str, default: Any = None) -> Any:
    try:
        return ss[key]
    except Exception:
        return default


def skipped_feed_fields(ss: Mapping[str, Any]) -> dict[str, str]:
    """Map situation field name → skip reason from last-sync audit ``skipped``."""
    audit = _ss_get(ss, LIVE_FEED_LAST_AUDIT)
    if not isinstance(audit, Mapping):
        return {}
    out: dict[str, str] = {}
    for entry in audit.get("skipped") or []:
        if not isinstance(entry, dict):
            continue
        field = str(entry.get("field") or "").strip()
        reason = str(entry.get("reason") or "").strip()
        if field and reason:
            out[field] = reason
    return out


def copy_derived_clock_to_game(
    game: Any,
    ss: Mapping[str, Any],
    *,
    quarter: int,
    seconds_remaining: int,
) -> None:
    """Copy widget-derived period clock onto ``Game`` unless ESPN skipped those fields."""
    origin = str(_ss_get(ss, LIVE_FEED_LAST_ORIGIN) or "")
    skipped = skipped_feed_fields(ss)
    if origin == ORIGIN_FEED:
        if "quarter" in skipped:
            game.quarter = None
        else:
            game.quarter = quarter
        if "clock" in skipped:
            game.clock_seconds_remaining = None
        else:
            game.clock_seconds_remaining = seconds_remaining
        return
    game.quarter = quarter
    game.clock_seconds_remaining = seconds_remaining


def generate_blocked_reason_for_feed_board(
    *,
    origin: str,
    skipped: Mapping[str, str],
    possession: Optional[str],
) -> Optional[str]:
    """Possession gate first; then refuse Generate when feed quarter/clock were skipped."""
    blocked = generate_blocked_reason_for_possession(possession)
    if blocked:
        return blocked
    if str(origin or "").strip() != ORIGIN_FEED:
        return None
    if "quarter" in skipped or "clock" in skipped:
        return GENERATE_UNSYNCED_CLOCK_REASON
    return None


def generate_blocked_reason_for_session(
    ss: Mapping[str, Any],
    *,
    possession: Optional[str],
) -> Optional[str]:
    origin = str(_ss_get(ss, LIVE_FEED_LAST_ORIGIN) or "")
    return generate_blocked_reason_for_feed_board(
        origin=origin,
        skipped=skipped_feed_fields(ss),
        possession=possession,
    )


def generate_skip_debug_reason_for_session(
    ss: Mapping[str, Any],
    *,
    possession: Optional[str],
) -> Optional[str]:
    skipped_pos = generate_skip_debug_reason(possession)
    if skipped_pos:
        return skipped_pos
    origin = str(_ss_get(ss, LIVE_FEED_LAST_ORIGIN) or "")
    if origin != ORIGIN_FEED:
        return None
    skipped = skipped_feed_fields(ss)
    if "quarter" in skipped or "clock" in skipped:
        return "unsynced_quarter_clock"
    return None

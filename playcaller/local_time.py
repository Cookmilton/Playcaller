"""Format sync timestamps in a named IANA zone (no Streamlit)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def datetime_from_epoch(epoch: float, *, timezone_name: Optional[str] = None) -> tuple[datetime, str]:
    """
    Aware datetime plus a short zone label.

    Unknown / invalid ``timezone_name`` falls back to UTC labelled ``UTC``.
    """
    name = str(timezone_name or "").strip()
    if name:
        try:
            tz = ZoneInfo(name)
            dt = datetime.fromtimestamp(float(epoch), tz)
            label = str(dt.tzname() or name).strip() or "UTC"
            return dt, label
        except (ZoneInfoNotFoundError, Exception):
            pass
    dt = datetime.fromtimestamp(float(epoch), timezone.utc)
    return dt, "UTC"


def format_synced_hhmm(epoch: float, *, timezone_name: Optional[str] = None) -> str:
    """Sidebar line: ``HH:MM TZ``."""
    dt, label = datetime_from_epoch(epoch, timezone_name=timezone_name)
    return f"{dt.strftime('%H:%M')} {label}".strip()


def format_local_epoch_labeled(epoch: float, *, timezone_name: Optional[str] = None) -> str:
    """``Live data:`` stamp with timezone abbreviation (``UTC`` when zone unknown)."""
    dt, label = datetime_from_epoch(epoch, timezone_name=timezone_name)
    return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} {label}".strip()

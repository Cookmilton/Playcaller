"""Local-time formatting for live-sync captions (no Streamlit)."""

from __future__ import annotations

from datetime import datetime


def local_datetime_from_epoch(epoch: float) -> datetime:
    return datetime.fromtimestamp(float(epoch)).astimezone()


def format_synced_hhmm(epoch: float) -> str:
    """Sidebar line: ``HH:MM TZ`` in the operator's local zone."""
    dt = local_datetime_from_epoch(epoch)
    tz = str(dt.tzname() or "").strip()
    clock = dt.strftime("%H:%M")
    return f"{clock} {tz}".strip() if tz else clock


def format_local_epoch_labeled(epoch: float) -> str:
    """``Live data:`` stamp with timezone abbreviation."""
    dt = local_datetime_from_epoch(epoch)
    tz = str(dt.tzname() or "").strip()
    stamp = dt.strftime("%Y-%m-%d %H:%M:%S")
    return f"{stamp} {tz}".strip() if tz else stamp

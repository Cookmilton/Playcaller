"""Streamlit viewer timezone → :mod:`playcaller.local_time` (1.56 ``st.context.timezone``)."""

from __future__ import annotations

from typing import Optional

from playcaller.local_time import format_local_epoch_labeled, format_synced_hhmm


def viewer_timezone_name() -> Optional[str]:
    """Browser IANA zone from Streamlit 1.56 ``st.context.timezone``, else None."""
    try:
        import streamlit as st

        ctx = getattr(st, "context", None)
        tz = getattr(ctx, "timezone", None) if ctx is not None else None
    except Exception:
        return None
    name = str(tz or "").strip()
    return name or None


def format_synced_hhmm_viewer(epoch: float) -> str:
    return format_synced_hhmm(epoch, timezone_name=viewer_timezone_name())


def format_local_epoch_labeled_viewer(epoch: float) -> str:
    return format_local_epoch_labeled(epoch, timezone_name=viewer_timezone_name())

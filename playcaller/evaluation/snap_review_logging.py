"""Opt-in logging for snap review persistence (set ``PLAYCALLER_SNAP_REVIEW_LOG=1``)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Mapping, MutableMapping

logger = logging.getLogger("playcaller.snap_review")

# Streamlit session_state key for in-app debug (set ``PLAYCALLER_SNAP_REVIEW_STREAMLIT_DEBUG=1``).
STREAMLIT_DEBUG_STATE_KEY = "_playcaller_snap_review_streamlit_debug"
# Always-updated last pipeline step (counts + event) for sidebar verification.
SNAP_REVIEW_SESSION_TRACE_KEY = "_playcaller_snap_review_session_trace"


def snap_review_file_log_enabled() -> bool:
    v = (os.environ.get("PLAYCALLER_SNAP_REVIEW_LOG") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def log_after_generate(*, row_count: int, snap_id: str | None = None) -> None:
    if not snap_review_file_log_enabled():
        return
    if snap_id:
        logger.info("snap_review after Generate: total_rows=%s last_snap_id=%s", row_count, snap_id)
    else:
        logger.info("snap_review after Generate: total_rows=%s", row_count)


def log_after_log_result(*, row: Mapping[str, Any] | None) -> None:
    if not snap_review_file_log_enabled():
        return
    if row is None:
        logger.info("snap_review after Log result: no row updated (no matching open snap)")
        return
    sid = row.get("snap_id", "?")
    st = row.get("status")
    logger.info(
        "snap_review after Log result: snap_id=%s status=%s completed=%s has_actual_result=%s",
        sid,
        st,
        row.get("completed"),
        row.get("actual_result") is not None,
    )


def log_before_export(*, row_count: int) -> None:
    if not snap_review_file_log_enabled():
        return
    logger.info("snap_review before export: recommendation_audit/snap_review_log rows=%s", row_count)


def streamlit_snap_review_debug_enabled() -> bool:
    v = (os.environ.get("PLAYCALLER_SNAP_REVIEW_STREAMLIT_DEBUG") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def merge_streamlit_snap_review_debug(
    ss: MutableMapping[str, Any],
    *,
    event: str,
    **fields: Any,
) -> None:
    """Merge debug fields into ``ss[STREAMLIT_DEBUG_STATE_KEY]`` for sidebar display."""
    trace: dict[str, Any] = dict(ss.get(SNAP_REVIEW_SESSION_TRACE_KEY) or {})
    trace["event"] = event
    trace["t"] = time.time()
    for k, v in fields.items():
        trace[k] = v
    ss[SNAP_REVIEW_SESSION_TRACE_KEY] = trace
    if not streamlit_snap_review_debug_enabled():
        return
    cur: dict[str, Any] = dict(ss.get(STREAMLIT_DEBUG_STATE_KEY) or {})
    cur["event"] = event
    cur["t"] = time.time()
    for k, v in fields.items():
        cur[k] = v
    ss[STREAMLIT_DEBUG_STATE_KEY] = cur

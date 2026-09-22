"""Live ESPN polling guards. The Streamlit fragment only evaluates these and maybe reruns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, MutableMapping, Optional

from playcaller.services.live_feed_sync import sync_readiness_from_session
from playcaller.streamlit_state.keys import (
    LIVE_FEED_LAST_IS_FINAL,
    LIVE_FEED_LAST_ORIGIN,
    LIVE_FEED_LAST_SYNC_EPOCH,
    LIVE_SYNC_INITIATOR,
    LIVE_SYNC_REQUESTED,
    UI_LIVE_POLLING_ENABLED,
)
from playcaller.streamlit_state.possession import ORIGIN_MANUAL

POLL_INTERVAL_SECONDS = 15
POLL_INITIATOR = "poll"

IDLE_POLLING_OFF = "Polling is off"
IDLE_GAME_FINAL = "Game is final"
IDLE_ORIGIN_MANUAL = "Board is marked manual"
IDLE_OPEN_SNAP = "Open snap — polling deferred"


@dataclass(frozen=True)
class PollingReadiness:
    should_poll: bool
    idle_reason: Optional[str]


def tail_recommendation_audit_is_open(ss: MutableMapping[str, Any]) -> bool:
    """True only when the tail ``recommendation_audit`` row is the live unresolved snap."""
    game = ss.get("game")
    audit = getattr(game, "recommendation_audit", None) if game is not None else None
    if not audit:
        return False
    return audit[-1].get("status") == "open"


def polling_readiness_from_session(ss: MutableMapping[str, Any]) -> PollingReadiness:
    """All five activation guards. Every one must pass before a poll may fire."""
    if not ss.get(UI_LIVE_POLLING_ENABLED):
        return PollingReadiness(False, IDLE_POLLING_OFF)
    ready = sync_readiness_from_session(ss)
    if not ready.can_sync:
        return PollingReadiness(False, ready.block_reason or "Sync is not ready")
    if ss.get(LIVE_FEED_LAST_IS_FINAL) is True:
        return PollingReadiness(False, IDLE_GAME_FINAL)
    if ss.get(LIVE_FEED_LAST_ORIGIN) == ORIGIN_MANUAL:
        return PollingReadiness(False, IDLE_ORIGIN_MANUAL)
    if tail_recommendation_audit_is_open(ss):
        return PollingReadiness(False, IDLE_OPEN_SNAP)
    return PollingReadiness(True, None)


def is_fragment_timer_tick() -> bool:
    """True only on a fragment-only rerun (``run_every`` tick), not the inline full-app call.

    Streamlit 1.56 sets ``ScriptRunContext.fragment_ids_this_run`` from
    ``rerun_data.fragment_id_queue`` (``script_runner.py:550-552``). That value is
    ``None`` on a full app run. ``fragment.py:189`` uses the same check to restore
    cursors for a fragment-only run. AppTest never fills ``fragment_id_queue``
    (``local_script_runner.py:139-145``), so ``AppTest.run()`` is always inline.
    """
    from streamlit.runtime.scriptrunner_utils.script_run_context import get_script_run_ctx

    ctx = get_script_run_ctx()
    return bool(ctx is not None and ctx.fragment_ids_this_run)


def maybe_request_live_poll(ss: MutableMapping[str, Any]) -> bool:
    """Queue a poll sync when this is a timer tick and every guard passes.

    Returns True when the fragment should ``st.rerun(scope="app")``. The inline
    execution that happens while the fragment is declared is always a no-op.
    """
    if not is_fragment_timer_tick():
        return False
    if not polling_readiness_from_session(ss).should_poll:
        return False
    ss[LIVE_SYNC_REQUESTED] = True
    ss[LIVE_SYNC_INITIATOR] = POLL_INITIATOR
    return True


def polling_status_caption(ss: MutableMapping[str, Any]) -> str:
    """Sidebar: polling on/off, interval, and why it is idle when a guard blocks."""
    enabled = bool(ss.get(UI_LIVE_POLLING_ENABLED))
    head = f"Auto-poll **{'on' if enabled else 'off'}** · every **{POLL_INTERVAL_SECONDS}s**"
    ready = polling_readiness_from_session(ss)
    if enabled and ready.idle_reason:
        head = f"{head} · idle: {ready.idle_reason}"
    ts = ss.get(LIVE_FEED_LAST_SYNC_EPOCH)
    if ts:
        from playcaller.ui.local_time import format_synced_hhmm_viewer

        head = f"{head} · last fetch **{format_synced_hhmm_viewer(float(ts))}**"
    return head

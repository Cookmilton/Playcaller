"""
Session state: ``ui_*`` (widget-owned) vs ``game_*`` (backend / feed mirror).

**Widget layer — ``ui_*``**

Keys that appear as Streamlit ``key=`` for sidebar (or other) widgets are *widget-owned*.
Streamlit forbids assigning ``st.session_state[that_key]`` **after** that widget is
constructed earlier in the same script run. Feed loaders and sync code must not write these
keys mid-run; use ``game_*`` plus :func:`request_widget_hydrate_from_backend` and a rerun.

**Backend layer — ``game_*``**

ESPN :func:`~playcaller.live_data.sync.apply_snapshot`, **Load game JSON**, and similar paths
write mirrored board state here. :func:`reconcile_widget_and_backend_state` runs **before**
widgets: either it copies ``game_*`` → ``ui_*`` (hydrate) or ``ui_*`` → ``game_*`` (operator
authoritative for mirrored fields).

**Adding a mirrored field**

1. Add a canonical ``game_*`` constant in ``playcaller.streamlit_state.keys``.
2. Append ``(GAME_…, "ui_…")`` to :data:`GAME_UI_MIRROR_PAIRS`.
3. Ensure ESPN / load paths set the ``game_*`` key only, then call
   :func:`request_widget_hydrate_from_backend` when a rerun will refresh widgets.
4. After the new widget is added in the sidebar, append its ``ui_*`` string to
   :data:`SIDEBAR_UI_WIDGET_KEYS` and either add a ``game_*`` pair or register the key under
   :data:`UI_SIDEBAR_KEYS_WITHOUT_BACKEND_MIRROR` with a short reason.

**Derived (non-widget) session keys**

``GAME_CONTEXT_QUARTER`` and ``GAME_CLOCK_TOTAL_SECONDS`` are computed caches, not Streamlit
widget keys — see :func:`refresh_derived_game_context_cache`.

**Development checks**

Set ``PLAYCALLER_DEV_AUDITS=1`` to log mirror-registry issues on startup. Set
``PLAYCALLER_UI_WRITE_GUARD=strict`` to raise on illegal ``ui_*`` writes after registration (default is ``warn``).
"""

from __future__ import annotations

import logging
import os
from typing import Any, MutableMapping

from playcaller.game_situation_input import context_quarter_from_period, split_clock
from playcaller.streamlit_state.keys import (
    GAME_CLOCK_TOTAL_SECONDS,
    GAME_CONTEXT_QUARTER,
    GAME_DISTANCE,
    GAME_DOWN,
    GAME_OPP_TOS,
    GAME_OWN_TOS,
    GAME_PERIOD,
    GAME_POSSESSION_SIDE,
    GAME_QUARTER_CLOCK_MINS,
    GAME_QUARTER_CLOCK_SECS,
    GAME_SCORE_OURS,
    GAME_SCORE_THEIRS,
    GAME_TERRITORY,
    GAME_WIDGET_HYDRATE_PENDING,
    GAME_YARDLINE,
)
from playcaller.streamlit_state.ui_defaults import new_game_ui_values
from playcaller.streamlit_state.ui_write_guard import assign_session_state

logger = logging.getLogger(__name__)

# (backend_key, widget_key) — ESPN / load JSON / hydrate targets.
GAME_UI_MIRROR_PAIRS: tuple[tuple[str, str], ...] = (
    (GAME_SCORE_OURS, "ui_score_ours"),
    (GAME_SCORE_THEIRS, "ui_score_theirs"),
    (GAME_PERIOD, "ui_game_period"),
    (GAME_QUARTER_CLOCK_MINS, "ui_quarter_clock_mins"),
    (GAME_QUARTER_CLOCK_SECS, "ui_quarter_clock_secs"),
    (GAME_DOWN, "ui_down"),
    (GAME_DISTANCE, "ui_distance"),
    (GAME_TERRITORY, "ui_territory"),
    (GAME_YARDLINE, "ui_yardline"),
    (GAME_OWN_TOS, "ui_own_tos"),
    (GAME_OPP_TOS, "ui_opp_tos"),
    (GAME_POSSESSION_SIDE, "ui_possession_side"),
)

# Every ``key="ui_…"`` in ``playcaller/ui/sidebar.py`` must appear here or in
# ``UI_SIDEBAR_KEYS_WITHOUT_BACKEND_MIRROR``.
SIDEBAR_UI_WIDGET_KEYS: frozenset[str] = frozenset(
    {
        "ui_possession_side",
        "ui_score_ours",
        "ui_score_theirs",
        "ui_down",
        "ui_distance",
        "ui_territory",
        "ui_yardline",
        "ui_def_personnel",
        "ui_box_count",
        "ui_coverage_shell",
        "ui_safeties",
        "ui_blitz_likely",
        "ui_game_period",
        "ui_quarter_clock_mins",
        "ui_quarter_clock_secs",
        "ui_own_tos",
        "ui_opp_tos",
        "ui_weather",
        "ui_wind_mph",
        "ui_qb_limited",
        "ui_game_mode",
        "ui_mismatch",
        "ui_drive_end_on_new",
        "ui_debug_game_context",
        "ui_live_espn_sport",
        "ui_live_pick_event_id",
        "ui_live_home_or_away",
        "ui_live_event_id_manual",
        "ui_live_our_team_advanced",
        "ui_live_lock_situation",
        "ui_live_lock_score",
        "ui_live_auto_plays",
        "ui_live_import_completed_feed_drives",
        "ui_live_import_current_feed_drive_plays",
    }
)

# Sidebar widget keys that intentionally have no ``game_*`` mirror (local UI / model-only).
UI_SIDEBAR_KEYS_WITHOUT_BACKEND_MIRROR: frozenset[str] = frozenset(
    {
        "ui_def_personnel",
        "ui_box_count",
        "ui_coverage_shell",
        "ui_safeties",
        "ui_blitz_likely",
        "ui_weather",
        "ui_wind_mph",
        "ui_qb_limited",
        "ui_game_mode",
        "ui_mismatch",
        "ui_drive_end_on_new",
        "ui_debug_game_context",
        "ui_live_espn_sport",
        "ui_live_pick_event_id",
        "ui_live_home_or_away",
        "ui_live_event_id_manual",
        "ui_live_our_team_advanced",
        "ui_live_lock_situation",
        "ui_live_lock_score",
        "ui_live_auto_plays",
        "ui_live_import_completed_feed_drives",
        "ui_live_import_current_feed_drive_plays",
    }
)


def development_mirror_audit_messages() -> list[str]:
    """Return human-readable issues; empty if registry and mirror pairs are consistent."""
    issues: list[str] = []
    mirrored_ui = {u for _g, u in GAME_UI_MIRROR_PAIRS}

    for k in sorted(SIDEBAR_UI_WIDGET_KEYS):
        if k not in mirrored_ui and k not in UI_SIDEBAR_KEYS_WITHOUT_BACKEND_MIRROR:
            issues.append(
                f"Sidebar widget {k!r} is neither in GAME_UI_MIRROR_PAIRS nor "
                f"UI_SIDEBAR_KEYS_WITHOUT_BACKEND_MIRROR — add a policy."
            )

    for k in sorted(UI_SIDEBAR_KEYS_WITHOUT_BACKEND_MIRROR):
        if k not in SIDEBAR_UI_WIDGET_KEYS:
            issues.append(
                f"UI_SIDEBAR_KEYS_WITHOUT_BACKEND_MIRROR lists {k!r} but it is not in SIDEBAR_UI_WIDGET_KEYS."
            )

    for gk, uk in GAME_UI_MIRROR_PAIRS:
        if uk not in SIDEBAR_UI_WIDGET_KEYS:
            issues.append(f"GAME_UI_MIRROR_PAIRS maps to {uk!r} which is missing from SIDEBAR_UI_WIDGET_KEYS.")

    return issues


def log_development_mirror_audit() -> None:
    """If ``PLAYCALLER_DEV_AUDITS`` is set, log mirror-registry audit results."""
    if not os.environ.get("PLAYCALLER_DEV_AUDITS"):
        return
    msgs = development_mirror_audit_messages()
    for msg in msgs:
        logger.warning("playcaller dev audit: %s", msg)
    if not msgs:
        logger.info("playcaller dev audit: GAME_UI_MIRROR_PAIRS and sidebar registry are consistent.")


def ensure_game_backend_defaults(ss: MutableMapping[str, Any]) -> None:
    """Initialize missing ``game_*`` keys from matching ``ui_*`` (or ``new_game_ui_values``)."""
    defaults = new_game_ui_values()
    for gk, uk in GAME_UI_MIRROR_PAIRS:
        if gk not in ss:
            if uk in ss:
                ss[gk] = ss[uk]
            else:
                ss[gk] = defaults[uk]


def sync_widgets_from_backend(ss: MutableMapping[str, Any]) -> None:
    """Push backend → widget layer. Call only before bound widgets are instantiated this run."""
    for gk, uk in GAME_UI_MIRROR_PAIRS:
        if gk in ss:
            assign_session_state(ss, uk, ss[gk], context="sync_widgets_from_backend")


def sync_backend_from_widgets(ss: MutableMapping[str, Any]) -> None:
    """Copy operator-facing widgets into backend mirrors (feed / export consistency)."""
    for gk, uk in GAME_UI_MIRROR_PAIRS:
        if uk in ss:
            ss[gk] = ss[uk]


def reconcile_widget_and_backend_state(ss: MutableMapping[str, Any]) -> None:
    """
    Run once per script entry after :func:`~playcaller.streamlit_state.pending.apply_all_pending`.

    If a feed or load queued a hydrate, copy ``game_*`` → ``ui_*``. Otherwise copy ``ui_*`` → ``game_*``.
    """
    ensure_game_backend_defaults(ss)
    if ss.pop(GAME_WIDGET_HYDRATE_PENDING, False):
        sync_widgets_from_backend(ss)
    else:
        sync_backend_from_widgets(ss)
    refresh_derived_game_context_cache(ss)


def request_widget_hydrate_from_backend(ss: MutableMapping[str, Any]) -> None:
    """Backend writers call this, then ``st.rerun()``; next run reconciles before widgets."""
    ss[GAME_WIDGET_HYDRATE_PENDING] = True


def refresh_derived_game_context_cache(ss: MutableMapping[str, Any]) -> None:
    """
    Recompute ``GAME_CONTEXT_QUARTER`` and ``GAME_CLOCK_TOTAL_SECONDS`` from period + quarter clock.

    Uses ``game_*`` with ``ui_*`` fallback. Not tied to Streamlit widgets — call after
    ``reconcile_widget_and_backend_state`` and again after ``sync_backend_from_widgets`` when
    the operator may have changed clock sliders.
    """
    period = int(ss.get(GAME_PERIOD, ss.get("ui_game_period", 1)))
    ctx_q = context_quarter_from_period(period)
    seconds_remaining, _, _ = split_clock(
        int(ss.get(GAME_QUARTER_CLOCK_MINS, ss.get("ui_quarter_clock_mins", 0))),
        int(ss.get(GAME_QUARTER_CLOCK_SECS, ss.get("ui_quarter_clock_secs", 0))),
        period,
    )
    ss[GAME_CONTEXT_QUARTER] = int(ctx_q)
    ss[GAME_CLOCK_TOTAL_SECONDS] = int(seconds_remaining)

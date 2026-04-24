"""
ESPN live-feed UI helpers: manual Event ID lookup phase, sync readiness, summaries.

Keeps ``sidebar.py`` thin; no ESPN network/provider calls here.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, MutableMapping, Optional


class ManualEventLookupPhase(str, Enum):
    """Manual path: where we are between Event ID entry and a successful summary fetch."""

    NO_EVENT_ID = "no_event_id"
    NEED_FETCH = "need_fetch"
    FETCH_FAILED = "fetch_failed"
    GAME_LOADED = "game_loaded"


@dataclass(frozen=True)
class ManualLookupStatus:
    phase: ManualEventLookupPhase
    """Single-line guidance for operators."""
    hint: str


@dataclass(frozen=True)
class EspnLiveSyncReadiness:
    can_sync: bool
    """Why **Sync from ESPN** is disabled, or ``None`` when enabled."""
    block_reason: str | None
    event_id: str
    our_team_id: str


def clear_manual_fetch_error_if_event_id_changed(
    ss: MutableMapping[str, Any],
    *,
    eid_typed: str,
    last_attempt_id_key: str,
    fetch_error_key: str,
) -> None:
    """Drop a typed fetch error when the Event ID no longer matches the last attempt."""
    if not ss.get(fetch_error_key):
        return
    att = str(ss.get(last_attempt_id_key) or "").strip()
    cur = eid_typed.strip()
    if att and cur != att:
        ss[fetch_error_key] = None


def clear_manual_event_cache_if_event_id_mismatch(
    ss: MutableMapping[str, Any],
    *,
    eid_typed: str,
    teams_key: str,
    for_id_key: str,
    fetch_error_key: str,
) -> None:
    """
    Drop cached summary when the box no longer matches the last successful fetch id,
    or when the Event ID is cleared.

    Avoids showing an old away/home matchup after the operator edits the Event ID.
    """
    cur = eid_typed.strip()
    cached_for = str(ss.get(for_id_key) or "").strip()
    if not cached_for:
        return
    if not cur or cur != cached_for:
        ss[teams_key] = None
        ss[for_id_key] = ""
        ss[fetch_error_key] = None


def manual_event_lookup_phase(
    *,
    eid_typed: str,
    teams: Optional[Mapping[str, Any]],
    teams_for_eid: str,
    fetch_error: Optional[str],
) -> ManualEventLookupPhase:
    eid = eid_typed.strip()
    if not eid:
        return ManualEventLookupPhase.NO_EVENT_ID
    err = (fetch_error or "").strip()
    if err:
        return ManualEventLookupPhase.FETCH_FAILED
    cached_for = (teams_for_eid or "").strip()
    if teams and cached_for == eid:
        return ManualEventLookupPhase.GAME_LOADED
    return ManualEventLookupPhase.NEED_FETCH


def manual_lookup_status(
    *,
    eid_typed: str,
    teams: Optional[Mapping[str, Any]],
    teams_for_eid: str,
    fetch_error: Optional[str],
) -> ManualLookupStatus:
    phase = manual_event_lookup_phase(
        eid_typed=eid_typed,
        teams=teams,
        teams_for_eid=teams_for_eid,
        fetch_error=fetch_error,
    )
    hints = {
        ManualEventLookupPhase.NO_EVENT_ID: "Enter an **Event ID** from the ESPN game URL, then fetch details.",
        ManualEventLookupPhase.NEED_FETCH: "Click **Fetch game details** (or enable auto-fetch) to load the matchup.",
        ManualEventLookupPhase.FETCH_FAILED: "Fix the issue above, then fetch again.",
        ManualEventLookupPhase.GAME_LOADED: "Matchup loaded — pick **Our team**, then sync.",
    }
    return ManualLookupStatus(phase=phase, hint=hints[phase])


def our_team_label_from_manual_teams(teams: Mapping[str, Any], *, home_or_away: str) -> str:
    ho = (home_or_away or "away").strip().lower()
    if ho not in ("away", "home"):
        ho = "away"
    if ho == "away":
        return str(teams.get("away_name") or "Away")
    return str(teams.get("home_name") or "Home")


def derive_espn_sync_readiness(
    *,
    uses_scoreboard: bool,
    event_id: str,
    our_team_id: str,
    manual: Optional[ManualLookupStatus] = None,
) -> EspnLiveSyncReadiness:
    """When ``uses_scoreboard`` is False, pass ``manual`` from :func:`manual_lookup_status`."""
    eid = (event_id or "").strip()
    tid = (our_team_id or "").strip()

    if uses_scoreboard:
        if not eid:
            return EspnLiveSyncReadiness(
                False,
                "Load the scoreboard and pick a game.",
                eid,
                tid,
            )
        if not tid:
            return EspnLiveSyncReadiness(
                False,
                "Choose **Our sideline team** (away vs home).",
                eid,
                tid,
            )
        return EspnLiveSyncReadiness(True, None, eid, tid)

    if manual is None:
        return EspnLiveSyncReadiness(
            False,
            "Complete manual Event ID setup first.",
            eid,
            tid,
        )
    if manual.phase is ManualEventLookupPhase.NO_EVENT_ID:
        return EspnLiveSyncReadiness(False, "Enter an **Event ID** first.", eid, tid)
    if manual.phase is ManualEventLookupPhase.NEED_FETCH:
        return EspnLiveSyncReadiness(
            False,
            "Fetch game details for this Event ID (not loaded yet).",
            eid,
            tid,
        )
    if manual.phase is ManualEventLookupPhase.FETCH_FAILED:
        return EspnLiveSyncReadiness(
            False,
            "Resolve the fetch error, then load game details again.",
            eid,
            tid,
        )
    # GAME_LOADED
    if not eid:
        return EspnLiveSyncReadiness(False, "Enter an **Event ID** first.", eid, tid)
    if not tid:
        return EspnLiveSyncReadiness(
            False,
            "Select **Our team (sideline OC)** — away or home.",
            eid,
            tid,
        )
    return EspnLiveSyncReadiness(True, None, eid, tid)


def format_espn_game_summary_markdown(
    *,
    away_name: str,
    home_name: str,
    event_id: str,
    our_team_description: str,
    sync_ready: bool,
    sync_block_reason: str | None,
) -> str:
    """Rich text for ``st.markdown`` (Streamlit-safe)."""
    away = away_name.strip() or "Away"
    home = home_name.strip() or "Home"
    ready = "**Ready to sync**" if sync_ready else "**Not ready to sync**"
    tail = "" if sync_ready else f" — {sync_block_reason or 'See status above.'}"
    return (
        f"**{away}** vs **{home}**\n\n"
        f"- **Event ID:** `{event_id}`\n"
        f"- **Our team (OC):** {our_team_description}\n"
        f"- **Sync:** {ready}{tail}"
    )


def format_espn_match_pills_html(
    *,
    away_name: str,
    home_name: str,
    event_id: str,
    our_team_description: str,
    sync_ready: bool,
    sync_block_reason: str | None,
) -> str:
    """Compact pill row for sidebar (inline HTML, escape names)."""
    away = html.escape(away_name.strip() or "Away")
    home = html.escape(home_name.strip() or "Home")
    eid = html.escape(str(event_id).strip() or "—")
    oc = html.escape(str(our_team_description).strip() or "—")
    status = "Ready" if sync_ready else "Blocked"
    reason = "" if sync_ready else html.escape(str(sync_block_reason or "See detail"))
    pill = (
        "display:inline-block;padding:3px 10px;border-radius:999px;border:1px solid #475569;"
        "margin:2px 6px 2px 0;font-size:12px;color:#e2e8f0;background:#1e293b"
    )
    return (
        f"<div style='font-size:12px;line-height:1.5;color:#cbd5e1;margin:4px 0 8px 0'>"
        f"<span style='{pill}'><strong>{away}</strong></span>"
        f"<span style='{pill}'><strong>{home}</strong></span>"
        f"<span style='{pill}'>ID {eid}</span>"
        f"<span style='{pill}'>{oc}</span>"
        f"<span style='{pill}'>{html.escape(status)}"
        f"{'' if sync_ready else f' · {reason}'}</span>"
        f"</div>"
    )


def maybe_auto_fetch_event_id(
    *,
    eid_typed: str,
    auto_fetch_enabled: bool,
    lookup_phase: ManualEventLookupPhase,
    session_key_prev: str,
) -> tuple[bool, str]:
    """
    Decide whether the manual path should trigger a fetch this run.

    Returns ``(should_fetch, updated_prev_eid)`` for storing in ``st.session_state``.

    Only fires when auto-fetch is on, the id looks like a full ESPN numeric id (9+ digits),
    and the lookup is not already loaded for that id. Tracks a **cursor** id so failed
    auto-fetches do not retry every rerun; editing the id resets the attempt.
    """
    cur = eid_typed.strip()
    prev = (session_key_prev or "").strip()
    if not auto_fetch_enabled:
        return False, prev
    if not cur or not cur.isdigit() or len(cur) < 9:
        return False, prev
    if lookup_phase is ManualEventLookupPhase.GAME_LOADED:
        return False, cur
    if lookup_phase is ManualEventLookupPhase.NO_EVENT_ID:
        return False, prev
    if lookup_phase is ManualEventLookupPhase.FETCH_FAILED:
        if cur == prev:
            return False, prev
        return True, cur
    # NEED_FETCH
    if cur == prev:
        return False, prev
    return True, cur

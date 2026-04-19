from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

from .espn_completed_drives import extract_completed_drives_from_espn_payload
from .espn_summary_teams import team_labels_from_espn_summary
from .http_util import fetch_json
from .types import FeedPlayEvent, FetchResult, NormalizedGameSnapshot

Sport = Literal["nfl", "college-football", "ufl"]


def _sport_path(sport: Sport) -> str:
    if sport == "nfl":
        return "football/nfl"
    if sport == "college-football":
        return "football/college-football"
    return "football/ufl"


def summary_url(sport: Sport, event_id: str) -> str:
    return f"https://site.api.espn.com/apis/site/v2/sports/{_sport_path(sport)}/summary?event={event_id}"


def scoreboard_url(sport: Sport) -> str:
    return f"https://site.api.espn.com/apis/site/v2/sports/{_sport_path(sport)}/scoreboard"


def _parse_clock_to_seconds(display_clock: Optional[str]) -> Optional[int]:
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


def _intish(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _competition(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    header = payload.get("header") or {}
    comps = header.get("competitions")
    if not comps:
        return None
    c0 = comps[0]
    return c0 if isinstance(c0, dict) else None


@dataclass(frozen=True)
class EspnEventTeams:
    """Home/away identity from an ESPN game summary payload."""

    event_id: str
    home_team_id: str
    away_team_id: str
    home_name: str
    away_name: str
    matchup_label: str


def _team_display_name(team: Any) -> str:
    if not isinstance(team, dict):
        return "?"
    return str(
        team.get("displayName")
        or team.get("shortDisplayName")
        or team.get("name")
        or team.get("abbreviation")
        or "?"
    )


def parse_event_teams_from_summary(payload: Dict[str, Any]) -> EspnEventTeams:
    """
    Read home/away team ids and labels from a summary JSON object.

    Raises ``ValueError`` if the payload does not look like a game summary.
    """
    comp = _competition(payload)
    if not comp:
        raise ValueError(
            "ESPN summary missing header.competitions[0] — check Event ID and sport, or the game may not exist."
        )
    eid = str(comp.get("id") or "")
    competitors = comp.get("competitors") or []
    home_id = away_id = ""
    home_name = away_name = ""
    for co in competitors:
        if not isinstance(co, dict):
            continue
        team = co.get("team") if isinstance(co.get("team"), dict) else {}
        tid = str(co.get("id") or (team.get("id") if isinstance(team, dict) else "") or "")
        label = _team_display_name(team)
        ha = str(co.get("homeAway") or "")
        if ha == "home":
            home_id, home_name = tid, label
        elif ha == "away":
            away_id, away_name = tid, label
    if not home_id or not away_id:
        raise ValueError("ESPN summary did not include both home and away competitors with ids.")
    matchup = f"{away_name} @ {home_name}"
    return EspnEventTeams(
        event_id=eid,
        home_team_id=home_id,
        away_team_id=away_id,
        home_name=home_name,
        away_name=away_name,
        matchup_label=matchup,
    )


def fetch_event_teams(sport: Sport, event_id: str) -> Tuple[EspnEventTeams, bool]:
    """GET game summary and extract home/away metadata.

    Returns ``(teams, used_insecure_ssl_fallback)``.
    """
    eid = str(event_id or "").strip()
    if not eid:
        raise ValueError("Event ID is empty.")
    res = fetch_json(summary_url(sport, eid))
    return parse_event_teams_from_summary(res.data), res.used_insecure_ssl_fallback


def list_espn_scoreboard_games(
    sport: Sport,
    *,
    limit: int = 30,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Return recent games from the ESPN scoreboard (id, label, status, home, away).

    Each row: ``{"id", "label", "detail", "home_abbr", "away_abbr", "home_id", "away_id"}``.
    Second tuple element is True when TLS verification was skipped (local fallback).
    """
    res = fetch_json(scoreboard_url(sport))
    data = res.data
    insecure = res.used_insecure_ssl_fallback
    events = data.get("events") or []
    out: List[Dict[str, Any]] = []
    for ev in events[:limit]:
        if not isinstance(ev, dict):
            continue
        eid = str(ev.get("id") or "")
        if not eid:
            continue
        comps = ev.get("competitions") or []
        c0 = comps[0] if comps and isinstance(comps[0], dict) else {}
        st = (c0.get("status") or {}) if isinstance(c0, dict) else {}
        typ = (st.get("type") or {}) if isinstance(st, dict) else {}
        competitors = c0.get("competitors") or []
        home_abbr = away_abbr = home_id = away_id = ""
        for co in competitors:
            if not isinstance(co, dict):
                continue
            team = co.get("team") or {}
            tid = str(co.get("id") or team.get("id") or "")
            ab = str(team.get("abbreviation") or "")
            if co.get("homeAway") == "home":
                home_abbr, home_id = ab, tid
            elif co.get("homeAway") == "away":
                away_abbr, away_id = ab, tid
        name = str(ev.get("name") or ev.get("shortName") or f"{away_abbr} @ {home_abbr}")
        out.append(
            {
                "id": eid,
                "label": name,
                "detail": str(typ.get("detail") or typ.get("shortDetail") or ""),
                "home_abbr": home_abbr,
                "away_abbr": away_abbr,
                "home_id": home_id,
                "away_id": away_id,
            }
        )
    return out, insecure


def _current_feed_drive_play_dicts(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], ...]:
    """Shallow-copy ``drives.current.plays`` for stable snapshot merge (in-progress drive only)."""
    drives = payload.get("drives") or {}
    current = drives.get("current")
    if not isinstance(current, dict):
        return ()
    out: List[Dict[str, Any]] = []
    for p in current.get("plays") or []:
        if isinstance(p, dict):
            out.append(dict(p))
    return tuple(out)


def _current_feed_drive_team_espn_id(payload: Dict[str, Any]) -> Optional[str]:
    drives = payload.get("drives") or {}
    current = drives.get("current")
    if not isinstance(current, dict):
        return None
    team = current.get("team")
    if isinstance(team, dict):
        tid = str(team.get("id") or "").strip()
        return tid or None
    return None


def parse_espn_summary(
    payload: Dict[str, Any],
    *,
    sport: Sport,
    our_team_id: str,
) -> NormalizedGameSnapshot:
    """
    Map raw ESPN summary JSON into :class:`NormalizedGameSnapshot`.

    ``our_team_id`` is the ESPN numeric team id for the offense you coach (maps to ``Game`` "offense").
    """
    comp = _competition(payload)
    if not comp:
        raise ValueError("ESPN payload missing header.competitions[0]")

    eid = str(comp.get("id") or "")
    status = comp.get("status") or {}
    typ = status.get("type") or {}
    is_final = bool(typ.get("completed"))
    status_detail = str(typ.get("detail") or typ.get("shortDetail") or "")
    quarter = _intish(status.get("period"))
    clock_seconds_in_period = _parse_clock_to_seconds(status.get("displayClock"))

    situation = comp.get("situation")
    situation = situation if isinstance(situation, dict) else None

    down = distance = None
    abs_yards: Optional[int] = None
    possession_team_id: Optional[str] = None
    notes: List[str] = []

    if situation:
        down = _intish(situation.get("down"))
        distance = _intish(situation.get("distance"))
        yte = _intish(situation.get("yardsToEndzone"))
        if yte is not None:
            ytc = max(0, min(99, yte))
            abs_yards = 99 if ytc == 0 else max(1, min(99, 100 - ytc))
        possession_team_id = situation.get("teamPossessionId") or situation.get("possession")
        if possession_team_id is not None:
            possession_team_id = str(possession_team_id)
    else:
        notes.append("No in-game situation block (game may be final or between snaps).")

    our_score = opp_score = None
    our_tos = opp_tos = None
    competitors = comp.get("competitors") or []
    oid = str(our_team_id)
    for co in competitors:
        if not isinstance(co, dict):
            continue
        tid = str(co.get("id") or "")
        if not tid:
            continue
        sc = _intish(co.get("score"))
        if tid == oid:
            our_score = sc
        else:
            opp_score = sc
        # ESPN sometimes lists timeouts on competitor during live games
        to = _intish(co.get("timeouts"))
        if to is not None:
            if tid == oid:
                our_tos = to
            else:
                opp_tos = to

    poss_ours: Optional[bool] = None
    if possession_team_id:
        poss_ours = possession_team_id == oid

    new_plays, play_notes = _extract_recent_plays(payload, possession_team_id)
    notes.extend(play_notes)

    completed_drives = extract_completed_drives_from_espn_payload(payload, event_id=eid)
    current_feed_plays = _current_feed_drive_play_dicts(payload)
    cur_team_id = _current_feed_drive_team_espn_id(payload)

    team_labels = team_labels_from_espn_summary(payload)
    if not team_labels:
        notes.append(
            "ESPN feed: no team label index from header.competitions; imported drive headings may show '?'."
        )
    missing_drive_team = sum(1 for fd in completed_drives if not (fd.team_espn_id or "").strip())
    if missing_drive_team:
        notes.append(
            f"ESPN feed: {missing_drive_team} completed drive(s) from drives.previous lack drive.team.id."
        )
    unresolved = sorted(
        {
            fd.team_espn_id
            for fd in completed_drives
            if (fd.team_espn_id or "").strip() and team_labels and fd.team_espn_id not in team_labels
        }
    )
    if unresolved:
        notes.append(
            "ESPN feed: drive team id(s) not in competition list (abbrev may be '?'): "
            + ", ".join(unresolved)
            + "."
        )

    return NormalizedGameSnapshot(
        provider="espn",
        external_game_id=eid,
        sport=sport,
        fetched_at_epoch=time.time(),
        status_detail=status_detail,
        quarter=quarter,
        clock_seconds_in_period=clock_seconds_in_period,
        down=down,
        distance=distance,
        abs_yards_from_own_goal=abs_yards,
        possession_team_id=possession_team_id,
        possession_is_our_team=poss_ours,
        our_score=our_score,
        opponent_score=opp_score,
        our_timeouts=our_tos,
        opponent_timeouts=opp_tos,
        is_final=is_final,
        new_plays=tuple(new_plays),
        debug_notes=tuple(notes),
        coached_team_id=str(our_team_id),
        completed_feed_drives=completed_drives,
        current_feed_drive_plays=current_feed_plays,
        current_feed_drive_team_espn_id=cur_team_id,
    )


def _extract_recent_plays(
    payload: Dict[str, Any],
    possession_team_id: Optional[str],
) -> Tuple[List[FeedPlayEvent], List[str]]:
    """Pull the last few plays from the current drive when ESPN exposes them."""
    notes: List[str] = []
    drives = payload.get("drives") or {}
    current = drives.get("current")
    plays_raw: List[Any] = []
    if isinstance(current, dict):
        plays_raw = list(current.get("plays") or [])
    if not plays_raw and isinstance(drives.get("previous"), list):
        prev = drives["previous"]
        if prev and isinstance(prev[-1], dict):
            plays_raw = list(prev[-1].get("plays") or [])
            notes.append("Using last archived drive for play tail (no current drive).")
    events: List[FeedPlayEvent] = []
    for p in plays_raw[-8:]:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "")
        if not pid:
            continue
        tx = p.get("text") or p.get("statYardage")
        if isinstance(tx, dict):
            text = str(tx.get("text") or "")
        else:
            text = str(p.get("description") or "")
        if not text:
            text = "(no description)"
        yds = _intish(p.get("statYardage"))
        ty = p.get("type")
        if isinstance(ty, dict):
            ptype = str(ty.get("text") or "").lower()
        else:
            ptype = str(ty or "").lower()
        text_l = text.lower()
        if "rush" in ptype or "rushing" in ptype:
            th = "rush"
        elif "pass" in ptype or "sack" in text_l:
            th = "pass"
        elif "penalty" in text_l:
            th = "penalty"
        elif "kick" in text_l or "punt" in text_l or "field goal" in text_l:
            th = "kick"
        else:
            th = "unknown"
        events.append(FeedPlayEvent(event_id=pid, summary_text=text, yards_gained=yds, type_hint=th))
    _ = possession_team_id  # reserved for future filtering by team
    return events, notes


class EspnFootballProvider:
    """ESPN Site API provider for NFL or college football."""

    def __init__(self, sport: Sport) -> None:
        self.sport = sport

    def fetch_snapshot(self, event_id: str, *, our_team_id: str) -> FetchResult:
        try:
            url = summary_url(self.sport, event_id)
            res = fetch_json(url)
            snap = parse_espn_summary(res.data, sport=self.sport, our_team_id=str(our_team_id))
        except Exception as e:
            return FetchResult(ok=False, error=str(e))
        return FetchResult(
            ok=True,
            snapshot=snap,
            used_insecure_ssl_fallback=res.used_insecure_ssl_fallback,
        )

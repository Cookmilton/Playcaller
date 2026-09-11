"""
Live game situation (down / distance / field position / possession / timeouts) from ESPN.

ESPN publishes a ``situation`` block **only** on the scoreboard endpoint, at
``events[].competitions[0].situation``. The summary endpoint has no ``situation`` key at
any depth, so the summary alone cannot supply the current down and distance.

Two sources, in priority order:

1. ``"scoreboard"`` — the scoreboard ``situation`` block. Authoritative, and the only
   source that carries timeouts.
2. ``"last_play_end"`` — ``drives.current.plays[-1].end`` on the summary payload. Used
   only when the scoreboard fetch failed, the event is absent from the scoreboard, or its
   ``situation`` block is missing.

Values come back **raw**: this module never clamps. Range policy lives in
:mod:`playcaller.live_data.sync` so that a field which cannot be applied is reported with
a reason instead of being silently coerced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .espn_game_state import intish
from .types import SituationSource

# ESPN ``possessionText`` is either "<ABBR> <yard>" ("LAR 34") or a bare "50" at midfield.
_POSSESSION_TEXT_RE = re.compile(r"^\s*(?:(?P<abbr>[A-Za-z]{2,5})\s+)?(?P<yard>\d{1,2})\s*$")


@dataclass(frozen=True)
class EspnSituation:
    """One parsed situation block. ``None`` fields are absent in that source, not zero."""

    source: SituationSource
    down: Optional[int] = None
    distance: Optional[int] = None
    # Yards from the possessing team's spot to the opponent goal line (1–99 when sane).
    yards_to_endzone: Optional[int] = None
    possession_team_id: Optional[str] = None
    home_timeouts: Optional[int] = None
    away_timeouts: Optional[int] = None
    notes: Tuple[str, ...] = ()


def scoreboard_event_competition(
    scoreboard_payload: Optional[Dict[str, Any]],
    *,
    event_id: str,
) -> Optional[Dict[str, Any]]:
    """
    ``events[]`` entry whose ``id`` matches ``event_id``, or ``None``.

    Selection is by id only. Matching on date would break for games played outside the
    US (an event's local kickoff can land on a different UTC calendar day).
    """
    if not isinstance(scoreboard_payload, dict):
        return None
    eid = str(event_id or "").strip()
    if not eid:
        return None
    for ev in scoreboard_payload.get("events") or []:
        if not isinstance(ev, dict) or str(ev.get("id") or "").strip() != eid:
            continue
        comps = ev.get("competitions") or []
        c0 = comps[0] if comps and isinstance(comps[0], dict) else None
        return c0
    return None


def competitor_abbreviation_by_id(competition: Dict[str, Any], team_id: str) -> str:
    """Team abbreviation for ``team_id`` from a competition's ``competitors`` list."""
    tid = str(team_id or "").strip()
    if not tid:
        return ""
    for co in competition.get("competitors") or []:
        if not isinstance(co, dict):
            continue
        team = co.get("team") if isinstance(co.get("team"), dict) else {}
        if str(co.get("id") or team.get("id") or "").strip() != tid:
            continue
        return str(team.get("abbreviation") or "").strip()
    return ""


def yards_to_endzone_from_possession_text(
    possession_text: Any,
    *,
    possession_team_abbr: str,
) -> Optional[int]:
    """
    Yards to the opponent goal from ESPN ``possessionText``.

    The abbreviation names whose half the ball is on, so it — not ``yardLine``, whose
    frame of reference varies — decides the direction:

    * ``"LAR 34"`` with LAR in possession → own 34 → 66
    * ``"SF 34"`` with LAR in possession → opponent 34 → 34
    * ``"50"`` (midfield, no abbreviation) → 50

    ``None`` when the text is unparseable, or when it names a side but the possessing
    team's abbreviation is unknown (direction would be a guess).
    """
    m = _POSSESSION_TEXT_RE.match(str(possession_text or ""))
    if not m:
        return None
    yard = int(m.group("yard"))
    if not 0 <= yard <= 50:
        return None
    abbr = (m.group("abbr") or "").strip().upper()
    if not abbr:
        return yard
    own = str(possession_team_abbr or "").strip().upper()
    if not own:
        return None
    return 100 - yard if abbr == own else yard


def parse_scoreboard_situation(
    scoreboard_payload: Optional[Dict[str, Any]],
    *,
    event_id: str,
) -> Optional[EspnSituation]:
    """Parse ``events[].competitions[0].situation`` for ``event_id``."""
    comp = scoreboard_event_competition(scoreboard_payload, event_id=event_id)
    if comp is None:
        return None
    sit = comp.get("situation")
    if not isinstance(sit, dict):
        return None

    notes: List[str] = []
    poss_id = str(sit.get("possession") or "").strip() or None
    poss_abbr = competitor_abbreviation_by_id(comp, poss_id) if poss_id else ""
    poss_text = sit.get("possessionText")
    yte = yards_to_endzone_from_possession_text(poss_text, possession_team_abbr=poss_abbr)
    if yte is None and str(poss_text or "").strip():
        notes.append(
            "situation: could not derive yards-to-endzone from scoreboard possessionText "
            f"{str(poss_text)!r} (possession team abbreviation {poss_abbr or 'unknown'})."
        )
    return EspnSituation(
        source="scoreboard",
        down=intish(sit.get("down")),
        distance=intish(sit.get("distance")),
        yards_to_endzone=yte,
        possession_team_id=poss_id,
        home_timeouts=intish(sit.get("homeTimeouts")),
        away_timeouts=intish(sit.get("awayTimeouts")),
        notes=tuple(notes),
    )


def parse_last_play_end_situation(
    summary_payload: Optional[Dict[str, Any]],
) -> Optional[EspnSituation]:
    """
    Parse ``drives.current.plays[-1].end`` from a summary payload.

    ESPN's ``end`` object describes the state *after* the play, which is the upcoming
    snap — the same thing the scoreboard ``situation`` reports. It carries no timeouts.
    """
    if not isinstance(summary_payload, dict):
        return None
    drives = summary_payload.get("drives")
    if not isinstance(drives, dict):
        return None
    current = drives.get("current")
    if not isinstance(current, dict):
        return None
    plays = [p for p in (current.get("plays") or []) if isinstance(p, dict)]
    if not plays:
        return None
    end = plays[-1].get("end")
    if not isinstance(end, dict):
        return None

    team = end.get("team") if isinstance(end.get("team"), dict) else {}
    poss_id = str(team.get("id") or "").strip()
    if not poss_id:
        cur_team = current.get("team") if isinstance(current.get("team"), dict) else {}
        poss_id = str(cur_team.get("id") or "").strip()
    return EspnSituation(
        source="last_play_end",
        down=intish(end.get("down")),
        distance=intish(end.get("distance")),
        yards_to_endzone=intish(end.get("yardsToEndzone")),
        possession_team_id=poss_id or None,
        notes=(
            "situation: scoreboard block unavailable — using drives.current.plays[-1].end, "
            "which can lag the broadcast by one snap and carries no timeouts.",
        ),
    )


def resolve_espn_situation(
    *,
    summary_payload: Dict[str, Any],
    scoreboard_payload: Optional[Dict[str, Any]],
    event_id: str,
    scoreboard_error: Optional[str] = None,
) -> Tuple[Optional[EspnSituation], Tuple[str, ...]]:
    """
    Pick the situation source for one sync.

    Returns ``(situation_or_None, debug_notes)``. ``None`` means neither source had a
    usable block; the notes always explain which source was used and why.
    """
    notes: List[str] = []
    if scoreboard_error:
        notes.append(f"situation: scoreboard fetch failed ({scoreboard_error}).")
    elif scoreboard_payload is None:
        notes.append("situation: no scoreboard payload supplied to the parser.")
    elif scoreboard_event_competition(scoreboard_payload, event_id=event_id) is None:
        notes.append(
            f"situation: event {event_id} not present in the scoreboard response "
            "(scoreboard covers the current week only)."
        )

    sit = parse_scoreboard_situation(scoreboard_payload, event_id=event_id)
    if sit is None and scoreboard_payload is not None and not scoreboard_error:
        if scoreboard_event_competition(scoreboard_payload, event_id=event_id) is not None:
            notes.append(
                "situation: scoreboard event found but it has no situation block "
                "(pre-kickoff, halftime, or final)."
            )
    if sit is None:
        sit = parse_last_play_end_situation(summary_payload)
    if sit is None:
        notes.append(
            "situation: unavailable from both the scoreboard block and "
            "drives.current.plays[-1].end — down, distance, field position, possession, "
            "and timeouts were not updated this sync."
        )
        return None, tuple(notes)

    notes.extend(sit.notes)
    return sit, tuple(notes)


def situation_timeouts_for_coached_team(
    situation: Optional[EspnSituation],
    *,
    coached_home_away: str,
) -> Tuple[Optional[int], Optional[int]]:
    """
    Map ``homeTimeouts`` / ``awayTimeouts`` onto ``(ours, theirs)``.

    ``coached_home_away`` is ``"home"`` or ``"away"``; anything else yields
    ``(None, None)`` because the mapping would be a guess.
    """
    if situation is None:
        return None, None
    side = str(coached_home_away or "").strip().lower()
    if side == "home":
        return situation.home_timeouts, situation.away_timeouts
    if side == "away":
        return situation.away_timeouts, situation.home_timeouts
    return None, None

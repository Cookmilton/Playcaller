"""
Parse ESPN **game summary** JSON (football) into :class:`EspnSummaryParseResult`.

**Supported shape:** responses shaped like ``GET .../summary`` payloads: a top-level
``header`` with ``competitions[0].competitors`` and optional ``drives.previous`` /
``drives.current``. This matches saved fixtures used elsewhere in the repo; ESPN
may add fields — unknown keys are ignored.

**Not in scope:** scoreboard-only rows, team roster endpoints, or non-JSON transports.
Normalization (canonical IDs, ``PlayFamily``, etc.) is a separate stage.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from football_history_warehouse.parsers.espn_summary.exceptions import EspnSummaryParserError
from football_history_warehouse.parsers.espn_summary.models import (
    SOURCE_FORMAT_ESPN_GAME_SUMMARY_V1,
    EspnSummaryParseResult,
    ParseNotice,
    ParsedEspnBroadcastStatus,
    ParsedEspnDrive,
    ParsedEspnGame,
    ParsedEspnParticipant,
    ParsedEspnPlay,
    ParsedEspnTeam,
)


def _notice(
    code: str,
    detail: str,
    *,
    where: str | None = None,
    severity: Literal["warning", "info"] = "warning",
) -> ParseNotice:
    return ParseNotice(severity=severity, code=code, detail=detail, where=where)


def _as_str(x: Any, default: str = "") -> str:
    if x is None:
        return default
    return str(x)


def _as_opt_int(x: Any) -> int | None:
    if x is None:
        return None
    try:
        return int(str(x).strip())
    except (TypeError, ValueError):
        return None


def _parse_team(comp: Mapping[str, Any], notices: list[ParseNotice]) -> ParsedEspnTeam | None:
    ha = _as_str(comp.get("homeAway")).lower()
    if ha not in ("home", "away"):
        notices.append(_notice("team_missing_home_away", "Competitor missing homeAway; skipped.", where="header.competitions[].competitors[]"))
        return None
    tid = _as_str(comp.get("id")) or _as_str((comp.get("team") or {}).get("id"))
    if not tid:
        notices.append(_notice("team_missing_id", "Competitor missing id; skipped.", where="header.competitions[].competitors[]"))
        return None
    team = comp.get("team") if isinstance(comp.get("team"), dict) else {}
    assert isinstance(team, dict)
    abbr = _as_str(team.get("abbreviation")) or None
    if not abbr:
        notices.append(_notice("team_missing_abbreviation", f"Team {tid} has no abbreviation.", where="team.abbreviation"))
    score_raw = comp.get("score")
    score = _as_opt_int(score_raw)
    if score is None and score_raw not in (None, ""):
        notices.append(_notice("team_score_unparsed", f"Could not parse score {score_raw!r} for team {tid}.", where="competitor.score"))
    return ParsedEspnTeam(
        espn_team_id=tid,
        home_away=ha,  # type: ignore[arg-type]
        abbreviation=abbr,
        display_name=_as_str(team.get("displayName")) or None,
        short_display_name=_as_str(team.get("shortDisplayName")) or None,
        score=score,
    )


def _parse_participants(raw: Mapping[str, Any]) -> tuple[ParsedEspnParticipant, ...]:
    out: list[ParsedEspnParticipant] = []
    for p in raw.get("participants") or []:
        if not isinstance(p, dict):
            continue
        ath = p.get("athlete") if isinstance(p.get("athlete"), dict) else {}
        assert isinstance(ath, dict)
        out.append(
            ParsedEspnParticipant(
                role=_as_str(p.get("type")) or None,
                display_name=_as_str(ath.get("displayName")) or None,
                jersey=_as_str(ath.get("jersey")) or None,
            )
        )
    return tuple(out)


def _parse_play(raw: Mapping[str, Any], seq: int, notices: list[ParseNotice]) -> ParsedEspnPlay | None:
    pid = _as_str(raw.get("id"))
    if not pid:
        notices.append(_notice("play_missing_id", "Play without id omitted.", where="drives.*.plays[]"))
        return None
    typ = raw.get("type") if isinstance(raw.get("type"), dict) else {}
    assert isinstance(typ, dict)
    yardage = raw.get("statYardage")
    sy: int | None
    if yardage is None:
        sy = None
    else:
        try:
            sy = int(yardage)
        except (TypeError, ValueError):
            notices.append(_notice("play_yardage_unparsed", f"Play {pid}: bad statYardage {yardage!r}.", where="play.statYardage"))
            sy = None
    return ParsedEspnPlay(
        source_play_id=pid,
        sequence_in_drive=seq,
        play_type_text=_as_str(typ.get("text")) or None,
        play_type_id=_as_str(typ.get("id")) or None,
        description_text=_as_str(raw.get("text")) or None,
        stat_yardage=sy,
        participants=_parse_participants(raw),
        raw_play=dict(raw),
    )


def _parse_drive(
    raw: Mapping[str, Any],
    order: int,
    *,
    synthetic_id: str | None,
    notices: list[ParseNotice],
) -> ParsedEspnDrive | None:
    did = synthetic_id or _as_str(raw.get("id"))
    if not did:
        notices.append(_notice("drive_missing_id", f"Drive order {order} missing id; skipped.", where="drives"))
        return None
    team = raw.get("team") if isinstance(raw.get("team"), dict) else {}
    assert isinstance(team, dict)
    offense = _as_str(team.get("id")) or None
    if not offense:
        notices.append(_notice("drive_missing_offense_team", f"Drive {did} has no team.id; offense unknown.", where="drive.team.id"))
    plays_in: list[ParsedEspnPlay] = []
    for i, pl in enumerate(raw.get("plays") or []):
        if not isinstance(pl, dict):
            notices.append(_notice("play_not_object", f"Drive {did}: play index {i} is not an object.", where="drive.plays[]"))
            continue
        pp = _parse_play(pl, i, notices)
        if pp is not None:
            plays_in.append(pp)
    return ParsedEspnDrive(
        source_drive_id=did,
        drive_order=order,
        offense_espn_team_id=offense,
        plays=tuple(plays_in),
        raw_drive=dict(raw),
    )


def _extract_broadcast(comp: Mapping[str, Any], notices: list[ParseNotice]) -> ParsedEspnBroadcastStatus | None:
    st = comp.get("status")
    if not isinstance(st, dict):
        return None
    typ = st.get("type") if isinstance(st.get("type"), dict) else {}
    assert isinstance(typ, dict)
    period = st.get("period")
    p_int: int | None
    try:
        p_int = int(period) if period is not None else None
    except (TypeError, ValueError):
        notices.append(_notice("status_period_unparsed", f"Could not parse period {period!r}.", where="status.period"))
        p_int = None
    return ParsedEspnBroadcastStatus(
        period=p_int,
        display_clock=_as_str(st.get("displayClock")) or None,
        completed=bool(typ.get("completed")) if "completed" in typ else None,
        type_detail=_as_str(typ.get("detail")) or _as_str(typ.get("shortDetail")) or None,
    )


def parse_espn_game_summary(payload: Mapping[str, Any] | Any) -> EspnSummaryParseResult:
    """
    Parse a decoded ESPN game summary **dict**.

    Raises :class:`EspnSummaryParserError` when no competition or no teams can be read.
    """
    if not isinstance(payload, Mapping):
        raise EspnSummaryParserError("payload_not_object", "Top-level JSON value must be an object.")

    notices: list[ParseNotice] = []
    header = payload.get("header")
    if not isinstance(header, dict):
        raise EspnSummaryParserError("missing_header", "Expected object 'header'.")

    comps = header.get("competitions") or []
    if not comps or not isinstance(comps[0], dict):
        raise EspnSummaryParserError("missing_competition", "header.competitions[0] missing or not an object.")

    comp0: dict[str, Any] = comps[0]
    if len(comps) > 1:
        notices.append(_notice("multiple_competitions", f"Ignoring competitions after index 0 ({len(comps)} total).", where="header.competitions"))

    event_id = _as_str(comp0.get("id"))
    if not event_id:
        notices.append(_notice("missing_event_id", "competition id missing; using empty string for source_event_id.", where="competitions[0].id"))

    competitors = comp0.get("competitors") or []
    teams_out: list[ParsedEspnTeam] = []
    for c in competitors:
        if not isinstance(c, dict):
            notices.append(_notice("competitor_not_object", "Skipping non-object competitor entry.", where="competitors[]"))
            continue
        t = _parse_team(c, notices)
        if t is not None:
            teams_out.append(t)

    if len(teams_out) < 2:
        raise EspnSummaryParserError("missing_teams", "Need at least two valid competitors with home/away and ids.")

    broadcast = _extract_broadcast(comp0, notices)

    drives_out: list[ParsedEspnDrive] = []
    drives = payload.get("drives")
    if not isinstance(drives, dict):
        notices.append(_notice("drives_not_object", "drives missing or not an object; no drives extracted.", where="drives"))
    else:
        prev = drives.get("previous") or []
        if not isinstance(prev, list):
            notices.append(_notice("drives_previous_not_list", "drives.previous is not a list; treated as empty.", where="drives.previous"))
            prev = []

        order = 0
        for d in prev:
            if not isinstance(d, dict):
                notices.append(_notice("drive_not_object", f"Skipping non-object entry in drives.previous at index {order}.", where="drives.previous[]"))
                continue
            parsed = _parse_drive(d, order, synthetic_id=None, notices=notices)
            if parsed is not None:
                drives_out.append(parsed)
                order += 1

        current = drives.get("current")
        if isinstance(current, dict):
            if current.get("plays"):
                parsed_cur = _parse_drive(current, order, synthetic_id=_as_str(current.get("id")) or "__current__", notices=notices)
                if parsed_cur is not None:
                    if not current.get("team"):
                        notices.append(
                            _notice(
                                "current_drive_missing_team",
                                "drives.current has plays but no team; offense unknown for this drive.",
                                where="drives.current.team",
                            )
                        )
                    drives_out.append(parsed_cur)
            elif current:
                notices.append(_notice("current_drive_empty", "drives.current present but has no plays.", where="drives.current"))
        elif current not in (None, {}):
            notices.append(_notice("current_drive_bad_shape", "drives.current is not an object; ignored.", where="drives.current"))

    game = ParsedEspnGame(
        source_format=SOURCE_FORMAT_ESPN_GAME_SUMMARY_V1,
        source_event_id=event_id,
        teams=tuple(teams_out),
        broadcast=broadcast,
        drives=tuple(drives_out),
        raw_header_competition=dict(comp0),
    )
    return EspnSummaryParseResult(game=game, notices=tuple(notices))


def parse_espn_game_summary_json_bytes(data: bytes) -> EspnSummaryParseResult:
    """Decode UTF-8 JSON bytes then :func:`parse_espn_game_summary`."""
    try:
        payload = json.loads(data.decode("utf-8"))
    except UnicodeDecodeError as e:
        raise EspnSummaryParserError("utf8_decode_error", str(e)) from e
    except json.JSONDecodeError as e:
        raise EspnSummaryParserError("json_decode_error", str(e)) from e
    if not isinstance(payload, dict):
        raise EspnSummaryParserError("json_not_object", "JSON root must be an object.")
    return parse_espn_game_summary(payload)


def parse_espn_game_summary_json_file(path: Path) -> EspnSummaryParseResult:
    """Read a UTF-8 file from disk (e.g. exported summary JSON)."""
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise EspnSummaryParserError("file_read_error", f"{path}: {e}") from e
    return parse_espn_game_summary_json_bytes(raw)

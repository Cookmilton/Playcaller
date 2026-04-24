"""
Pure ESPN summary JSON → normalized structs for minimal game ingest.

No SQLAlchemy, no sessions, no imports from ``football_history_warehouse.storage``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from football_history_warehouse.domain.enums import GameStatus
from football_history_warehouse.ingest.exceptions import IngestValidationError


@dataclass(frozen=True, slots=True)
class NormalizedLeague:
    code: str
    display_name: str


@dataclass(frozen=True, slots=True)
class NormalizedSeason:
    league_code: str
    year: int


@dataclass(frozen=True, slots=True)
class NormalizedTeam:
    league_code: str
    external_id: str
    abbreviation: str
    display_name: str
    location: str | None
    nickname: str | None


@dataclass(frozen=True, slots=True)
class NormalizedGame:
    external_id: str
    league_code: str
    season_year: int
    game_date: date
    scheduled_start_utc: datetime | None
    home_team_external_id: str
    away_team_external_id: str
    home_score: int | None
    away_score: int | None
    status: str


@dataclass(frozen=True, slots=True)
class NormalizedGameBundle:
    league: NormalizedLeague
    season: NormalizedSeason
    home_team: NormalizedTeam
    away_team: NormalizedTeam
    game: NormalizedGame


def _req(d: dict[str, Any], key: str, *, ctx: str) -> Any:
    v = d.get(key)
    if v is None:
        raise IngestValidationError(ctx, f"missing required key {key!r}")
    return v


def _parse_iso_date(s: str | None, *, ctx: str) -> date:
    if not s:
        raise IngestValidationError(ctx, "missing or empty date string")
    raw = s.strip()
    if not raw:
        raise IngestValidationError(ctx, "empty date string")
    if "T" in raw:
        raw = raw.split("T", 1)[0]
    try:
        y, m, d = (int(x) for x in raw.split("-", 2))
        return date(y, m, d)
    except (TypeError, ValueError) as e:
        raise IngestValidationError(ctx, f"cannot parse date from {s!r}: {e}") from e


def _parse_iso_datetime_utc(s: str | None) -> datetime | None:
    if not s or not str(s).strip():
        return None
    raw = str(s).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _map_status(competition_status: dict[str, Any] | None) -> str:
    if not competition_status:
        return GameStatus.UNKNOWN.value
    st = competition_status.get("type")
    if isinstance(st, dict):
        name = str(st.get("name") or "").upper()
        if "FINAL" in name:
            return GameStatus.FINAL.value
        if st.get("completed") is True:
            return GameStatus.FINAL.value
        state = str(st.get("state") or "").lower()
        if state == "in":
            return GameStatus.IN_PROGRESS.value
        if state == "pre":
            return GameStatus.SCHEDULED.value
    return GameStatus.UNKNOWN.value


def normalize_espn_summary(
    raw: dict[str, Any],
    *,
    league_code: str | None = None,
    season_year_override: int | None = None,
    league_display_name: str | None = None,
) -> NormalizedGameBundle:
    """
    Parse an ESPN game summary JSON dict (top-level ``header`` shape) into normalized objects.

    Uses only ``.get`` for optional paths; required fields raise :class:`IngestValidationError`.
    """
    header = raw.get("header")
    if not isinstance(header, dict):
        raise IngestValidationError("header", "expected object")

    comps = header.get("competitions")
    if not isinstance(comps, list) or len(comps) < 1:
        raise IngestValidationError("header.competitions", "expected non-empty array")
    comp0 = comps[0]
    if not isinstance(comp0, dict):
        raise IngestValidationError("header.competitions[0]", "expected object")

    event_id = str(_req(header, "id", ctx="header.id")).strip()
    if not event_id:
        raise IngestValidationError("header.id", "empty event id")

    season_block = header.get("season")
    if not isinstance(season_block, dict):
        raise IngestValidationError("header.season", "expected object")
    year = season_year_override if season_year_override is not None else season_block.get("year")
    if year is None:
        raise IngestValidationError("header.season.year", "missing year (provide season_year_override if absent)")
    try:
        year_int = int(year)
    except (TypeError, ValueError) as e:
        raise IngestValidationError("header.season.year", f"invalid year: {year!r}") from e

    lc = (league_code or "NFL").strip().upper()
    if not lc:
        raise IngestValidationError("league_code", "empty")

    league_name_default = {
        "NFL": "National Football League",
    }.get(lc, lc)
    league = NormalizedLeague(code=lc, display_name=(league_display_name or league_name_default).strip())

    season = NormalizedSeason(league_code=lc, year=year_int)

    competitors = comp0.get("competitors")
    if not isinstance(competitors, list) or len(competitors) < 2:
        raise IngestValidationError("competitors", "need at least two competitors")

    home_raw: dict[str, Any] | None = None
    away_raw: dict[str, Any] | None = None
    for c in competitors:
        if not isinstance(c, dict):
            continue
        ha = str(c.get("homeAway") or "").lower()
        if ha == "home":
            home_raw = c
        elif ha == "away":
            away_raw = c
    if home_raw is None or away_raw is None:
        raise IngestValidationError("competitors", "could not find home and away by homeAway")

    def team_from(side: dict[str, Any], *, label: str) -> NormalizedTeam:
        team = side.get("team")
        if not isinstance(team, dict):
            raise IngestValidationError(f"{label}.team", "expected object")
        tid = str(team.get("id") or "").strip()
        if not tid:
            raise IngestValidationError(f"{label}.team.id", "missing team id")
        abbr = str(team.get("abbreviation") or "").strip() or "?"
        display = str(team.get("displayName") or team.get("name") or "").strip() or abbr
        loc = team.get("location")
        nick = team.get("nickname")
        loc_s = str(loc).strip() if loc is not None else None
        nick_s = str(nick).strip() if nick is not None else None
        return NormalizedTeam(
            league_code=lc,
            external_id=tid,
            abbreviation=abbr,
            display_name=display,
            location=loc_s,
            nickname=nick_s,
        )

    home_team = team_from(home_raw, label="home")
    away_team = team_from(away_raw, label="away")

    def score_for(side: dict[str, Any]) -> int | None:
        sc = side.get("score")
        if sc is None:
            return None
        try:
            return int(sc)
        except (TypeError, ValueError):
            return None

    home_score = score_for(home_raw)
    away_score = score_for(away_raw)

    date_str = comp0.get("date")
    if not date_str:
        date_str = header.get("date")
    game_date = _parse_iso_date(str(date_str) if date_str else None, ctx="competition.date")
    sched = _parse_iso_datetime_utc(str(date_str) if date_str else None)

    status = _map_status(comp0.get("status") if isinstance(comp0.get("status"), dict) else None)

    game = NormalizedGame(
        external_id=event_id,
        league_code=lc,
        season_year=year_int,
        game_date=game_date,
        scheduled_start_utc=sched,
        home_team_external_id=home_team.external_id,
        away_team_external_id=away_team.external_id,
        home_score=home_score,
        away_score=away_score,
        status=status,
    )

    return NormalizedGameBundle(
        league=league,
        season=season,
        home_team=home_team,
        away_team=away_team,
        game=game,
    )

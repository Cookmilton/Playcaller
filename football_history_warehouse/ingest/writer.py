"""
Insert :mod:`football_history_warehouse.ingest.normalize` bundles into ORM rows.

Uses existing session patterns and ``LeagueRow`` / ``SeasonRow`` / ``TeamRow`` / ``GameRow``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from football_history_warehouse.domain.enums import CompetitionTier, LeagueFamily
from football_history_warehouse.ingest.normalize import (
    NormalizedGame,
    NormalizedGameBundle,
    NormalizedLeague,
    NormalizedSeason,
    NormalizedTeam,
)
from football_history_warehouse.storage.database.models import GameRow, LeagueRow, SeasonRow, TeamRow

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestResult:
    rows_created: int
    rows_updated: int
    game_id: str
    """Warehouse ``games.game_id`` primary key (string)."""
    was_new: bool


def _league_pk(code: str) -> str:
    return f"lg-{code.strip().lower()}"


def _season_pk(league_id: str, year: int) -> str:
    return f"sn-{league_id}-{year}"


def _team_pk(league_id: str, external_id: str) -> str:
    return f"{league_id}-espn-{external_id}"


def _game_pk(external_event_id: str) -> str:
    return f"espn:{external_event_id}"


def get_or_create_league(session: Session, normalized: NormalizedLeague) -> tuple[LeagueRow, bool]:
    league_id = _league_pk(normalized.code)
    row = session.get(LeagueRow, league_id)
    if row is not None:
        return row, False
    short = normalized.code.strip()[:32]
    row = LeagueRow(
        league_id=league_id,
        family=LeagueFamily.NFL.value if normalized.code.upper() == "NFL" else LeagueFamily.OTHER.value,
        name=normalized.display_name,
        short_code=short or None,
        competition_tier_default=CompetitionTier.REGULAR.value,
        rules_profile_key=None,
    )
    session.add(row)
    session.flush()
    return row, True


def get_or_create_season(session: Session, normalized: NormalizedSeason, league: LeagueRow) -> tuple[SeasonRow, bool]:
    league_id = league.league_id
    season_id = _season_pk(league_id, normalized.year)
    row = session.get(SeasonRow, season_id)
    if row is not None:
        return row, False
    row = SeasonRow(
        season_id=season_id,
        league_id=league_id,
        year_label=str(normalized.year),
        starts_on=None,
        ends_on=None,
    )
    session.add(row)
    session.flush()
    return row, True


def get_or_create_team(session: Session, normalized: NormalizedTeam, league: LeagueRow) -> tuple[TeamRow, bool]:
    league_id = league.league_id
    team_id = _team_pk(league_id, normalized.external_id)
    row = session.get(TeamRow, team_id)
    if row is not None:
        return row, False
    row = TeamRow(
        team_id=team_id,
        league_id=league_id,
        full_name=normalized.display_name,
        abbreviation=normalized.abbreviation or None,
        nickname=normalized.nickname,
        city=normalized.location,
        conference_id=None,
        division_id=None,
    )
    session.add(row)
    session.flush()
    return row, True


def create_or_update_game(
    session: Session,
    normalized: NormalizedGame,
    *,
    season: SeasonRow,
    home: TeamRow,
    away: TeamRow,
) -> tuple[GameRow, bool, bool]:
    """
    Returns ``(row, was_created, was_updated)``.
    """
    gid = _game_pk(normalized.external_id)
    existing = session.get(GameRow, gid)
    ext = {
        "minimal_ingest": True,
        "espn_event_id": normalized.external_id,
    }
    if existing is None:
        row = GameRow(
            game_id=gid,
            season_id=season.season_id,
            league_id=season.league_id,
            home_team_id=home.team_id,
            away_team_id=away.team_id,
            status=normalized.status,
            scheduled_start_utc=normalized.scheduled_start_utc,
            home_score_final=normalized.home_score,
            away_score_final=normalized.away_score,
            regulation_period_count=4,
            overtime_periods_played=None,
            venue_id=None,
            attendance=None,
            neutral_site=None,
            source_extensions=ext,
        )
        session.add(row)
        session.flush()
        return row, True, False

    changed = False
    if existing.status != normalized.status:
        existing.status = normalized.status
        changed = True
    if existing.scheduled_start_utc != normalized.scheduled_start_utc:
        existing.scheduled_start_utc = normalized.scheduled_start_utc
        changed = True
    if existing.home_score_final != normalized.home_score:
        existing.home_score_final = normalized.home_score
        changed = True
    if existing.away_score_final != normalized.away_score:
        existing.away_score_final = normalized.away_score
        changed = True
    merged = dict(existing.source_extensions or {})
    merged.update(ext)
    if merged != existing.source_extensions:
        existing.source_extensions = merged
        changed = True
    if changed:
        existing.row_updated_at = datetime.now(timezone.utc)
        session.flush()
    return existing, False, changed


def ingest_game_bundle(session: Session, bundle: NormalizedGameBundle) -> IngestResult:
    """
    Ingest one game in the current session (no commit). Caller supplies transaction boundaries.

    All-or-nothing: on exception the caller rolls back the transaction.
    """
    created = 0
    updated = 0

    league, c1 = get_or_create_league(session, bundle.league)
    if c1:
        created += 1

    season, c2 = get_or_create_season(session, bundle.season, league)
    if c2:
        created += 1

    home, c3 = get_or_create_team(session, bundle.home_team, league)
    if c3:
        created += 1

    away, c4 = get_or_create_team(session, bundle.away_team, league)
    if c4:
        created += 1

    game_row, g_new, g_upd = create_or_update_game(
        session,
        bundle.game,
        season=season,
        home=home,
        away=away,
    )
    if g_new:
        created += 1
    elif g_upd:
        updated += 1

    logger.info(
        "Ingest complete: leagues=1, seasons=1, teams=2, games=1 (rows_created=%s rows_updated=%s)",
        created,
        updated,
    )
    return IngestResult(
        rows_created=created,
        rows_updated=updated,
        game_id=game_row.game_id,
        was_new=g_new,
    )

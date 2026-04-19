"""
Low-level competition reads: games, drives, plays.

Keeps SQLAlchemy details here so services stay oriented around football semantics.
"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from football_history_warehouse.query.situation.filter import PlaySituationFilter, validate_situation_has_scope
from football_history_warehouse.query.situation.sql import apply_play_situation_filter
from football_history_warehouse.storage.database.models import DriveRow, GameRow, PlayRow


class CompetitionQueryRepository:
    """Session-scoped read access to competition tables."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_game_row(self, game_id: str) -> GameRow | None:
        return self._session.get(GameRow, game_id)

    def fetch_game_rows_page(
        self,
        *,
        league_id: str | None,
        season_id: str | None,
        team_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[GameRow], bool]:
        """
        Return up to ``limit`` games and whether more rows exist after this page.

        Uses a ``limit + 1`` read to set ``has_more`` without a separate COUNT.
        """
        stmt = select(GameRow)
        if league_id is not None:
            stmt = stmt.where(GameRow.league_id == league_id)
        if season_id is not None:
            stmt = stmt.where(GameRow.season_id == season_id)
        if team_id is not None:
            stmt = stmt.where(or_(GameRow.home_team_id == team_id, GameRow.away_team_id == team_id))
        stmt = stmt.order_by(
            GameRow.scheduled_start_utc.asc().nulls_last(),
            GameRow.game_id.asc(),
        ).limit(limit + 1).offset(offset)
        rows = list(self._session.scalars(stmt).all())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    def fetch_drive_rows_for_game(self, game_id: str) -> list[DriveRow]:
        stmt = (
            select(DriveRow)
            .where(DriveRow.game_id == game_id)
            .order_by(DriveRow.drive_order.asc(), DriveRow.drive_id.asc())
        )
        return list(self._session.scalars(stmt).all())

    def fetch_play_rows_for_situation(
        self,
        situation: PlaySituationFilter,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[PlayRow], bool]:
        """
        Plays matching a :class:`~football_history_warehouse.query.situation.filter.PlaySituationFilter`.

        Ordered by ``game_id``, ``sequence_in_game``, ``play_id`` for stable cross-game pages.
        """
        validate_situation_has_scope(situation)
        stmt = select(PlayRow)
        stmt = apply_play_situation_filter(stmt, situation)
        stmt = stmt.order_by(
            PlayRow.game_id.asc(),
            PlayRow.sequence_in_game.asc(),
            PlayRow.play_id.asc(),
        ).limit(limit + 1).offset(offset)
        rows = list(self._session.scalars(stmt).all())
        has_more = len(rows) > limit
        return rows[:limit], has_more

    def fetch_play_rows_for_game(
        self,
        game_id: str,
        situation: PlaySituationFilter | None,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[PlayRow], bool]:
        """Plays for one game, optionally further restricted by ``situation`` (other than game)."""
        merged = replace(situation or PlaySituationFilter(), game_id=game_id)
        return self.fetch_play_rows_for_situation(merged, limit=limit, offset=offset)

    def fetch_all_play_rows_for_game(self, game_id: str, *, max_plays: int = 3500) -> list[PlayRow]:
        """
        All plays for a game in order (for review / analytics bundles).

        Capped to avoid pathological feeds; increase ``max_plays`` if a league exceeds this.
        """
        stmt = (
            select(PlayRow)
            .where(PlayRow.game_id == game_id)
            .order_by(PlayRow.sequence_in_game.asc(), PlayRow.play_id.asc())
            .limit(max_plays)
        )
        return list(self._session.scalars(stmt).all())

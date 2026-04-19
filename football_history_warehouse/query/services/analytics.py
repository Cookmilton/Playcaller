"""
Aggregated play statistics over a :class:`~football_history_warehouse.query.situation.filter.PlaySituationFilter`.

Internal to the warehouse query layer; **playcalling apps** should use
:class:`~football_history_warehouse.consumer.client.FootballWarehouseClient` instead of this type.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from football_history_warehouse.query.situation.filter import PlaySituationFilter, validate_situation_has_scope
from football_history_warehouse.query.situation.sql import apply_play_situation_filter
from football_history_warehouse.storage.database.models import PlayRow


class WarehouseAnalyticsService:
    """Session-scoped SQL aggregates for situation slices (no ORM rows returned)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def offense_play_family_counts(
        self,
        situation: PlaySituationFilter,
    ) -> tuple[dict[str, int], int]:
        """
        Count plays grouped by ``play_family`` for rows matching ``situation``.

        Returns ``(counts, total_plays)``.
        """
        validate_situation_has_scope(situation)
        filtered = apply_play_situation_filter(select(PlayRow), situation)
        sq = filtered.subquery()
        stmt = select(sq.c.play_family, func.count()).group_by(sq.c.play_family)
        rows = self._session.execute(stmt).all()
        counts: dict[str, int] = {str(r[0]): int(r[1]) for r in rows if r[0] is not None}
        total = sum(counts.values())
        return counts, total

    def outcome_category_counts(
        self,
        situation: PlaySituationFilter,
    ) -> tuple[dict[str, int], int]:
        """Count plays grouped by ``result_category``; returns ``(counts, total_plays)``."""
        validate_situation_has_scope(situation)
        filtered = apply_play_situation_filter(select(PlayRow), situation)
        sq = filtered.subquery()
        stmt = select(sq.c.result_category, func.count()).group_by(sq.c.result_category)
        rows = self._session.execute(stmt).all()
        counts = {str(r[0]): int(r[1]) for r in rows if r[0] is not None}
        total = sum(counts.values())
        return counts, total

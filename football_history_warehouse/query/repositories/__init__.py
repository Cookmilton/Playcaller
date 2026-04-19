"""SQLAlchemy-backed read repositories (no domain mapping here)."""

from football_history_warehouse.query.repositories.competition import CompetitionQueryRepository

__all__ = ["CompetitionQueryRepository"]

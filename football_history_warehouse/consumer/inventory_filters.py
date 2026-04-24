"""Filters for warehouse game inventory (operator / review lists)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GameInventoryFilters:
    """Optional filters for :meth:`~football_history_warehouse.consumer.client.FootballWarehouseClient.list_games_inventory`."""

    league_id: str | None = None
    season_id: str | None = None
    """Matches games where this team is home **or** away."""
    team_id: str | None = None
    import_job_id: str | None = None

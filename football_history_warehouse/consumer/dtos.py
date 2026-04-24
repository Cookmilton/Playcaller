"""
Stable DTOs for the **playcalling app boundary** (JSON-serializable summaries).

Domain entities such as :class:`~football_history_warehouse.domain.competition.Play`
are also public via :mod:`football_history_warehouse.consumer` — they describe
on-field facts, not storage layout.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from football_history_warehouse.domain.competition import Play
from football_history_warehouse.domain.enums import PlayResultCategory

_TURNOVER_RESULTS = frozenset(
    {
        PlayResultCategory.INTERCEPTION.value,
        PlayResultCategory.FUMBLE_LOST.value,
    }
)


class PlaysBySituationPage(BaseModel):
    """One page of canonical plays for a situation slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plays: tuple[Play, ...]
    limit: int
    offset: int
    has_more: bool


class WarehouseGameInventoryItem(BaseModel):
    """
    One row in the operator inventory: enough to pick a game and audit import provenance.

    Counts are warehouse facts; ``source_artifact_hint`` is a best-effort label (file name, URI, or ingest URI).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    game_id: str
    league_id: str
    league_name: str
    season_id: str
    season_year_label: str
    scheduled_start_utc: datetime | None = None
    status: str
    home_team_id: str
    away_team_id: str
    home_team_name: str
    away_team_name: str
    home_score_final: int | None = None
    away_score_final: int | None = None
    drive_count: int
    play_count: int
    import_job_id: str | None = None
    imported_at: datetime | None = None
    source_artifact_hint: str | None = None


class GameInventoryPage(BaseModel):
    """Paged inventory list (offset/limit, ``has_more`` probe)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    games: tuple[WarehouseGameInventoryItem, ...]
    limit: int
    offset: int
    has_more: bool


class TeamTendencySummary(BaseModel):
    """
    Offensive play-family histogram for one team over a bounded situation.

    ``situation`` is always interpreted as **offense = team_id** (merged by the client).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    team_id: str
    total_plays: int
    play_family_counts: dict[str, int] = Field(default_factory=dict)


class SituationOutcomeSummary(BaseModel):
    """
    Historical outcome mix for plays matching a situation (warehouse-backed).

    Turnovers are approximated from normalized ``result_category`` values
    (interception, fumble_lost); extend when richer turnover flags are aggregated in SQL.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    total_plays: int
    result_category_counts: dict[str, int] = Field(default_factory=dict)
    touchdowns: int = 0
    turnovers: int = 0
    sacks: int = 0
    incomplete_passes: int = 0

    @classmethod
    def from_category_counts(cls, counts: dict[str, int], total_plays: int) -> SituationOutcomeSummary:
        """Derive rollup fields from SQL ``result_category`` histograms."""
        td = counts.get(PlayResultCategory.TOUCHDOWN.value, 0)
        to = sum(counts.get(c, 0) for c in _TURNOVER_RESULTS)
        sacks = counts.get(PlayResultCategory.SACK.value, 0)
        inc = counts.get(PlayResultCategory.INCOMPLETE.value, 0)
        return cls(
            total_plays=total_plays,
            result_category_counts=dict(counts),
            touchdowns=td,
            turnovers=to,
            sacks=sacks,
            incomplete_passes=inc,
        )

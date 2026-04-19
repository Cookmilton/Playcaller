"""
Per-game normalization context: canonical ids and external→team mapping.

**External team refs:** keys are opaque strings agreed per connector, e.g.
``"espn:401"`` for ESPN internal team id ``401``. Normalization never embeds
vendor assumptions in :class:`~football_history_warehouse.domain` models — only
here when resolving ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from football_history_warehouse.domain.identifiers import GameId, ImportJobId, LeagueId, SeasonId, TeamId


@dataclass(frozen=True, slots=True)
class GameNormalizationContext:
    """
    Everything needed to turn one parsed game into canonical ``Game``/``Drive``/``Play`` rows.

    ``team_id_by_external_ref`` must cover teams that appear in the feed for this game.
    """

    league_id: LeagueId
    season_id: SeasonId
    game_id: GameId
    team_id_by_external_ref: dict[str, TeamId]
    source_system: str = "espn_api"
    import_job_id: ImportJobId | None = None
    observed_at: datetime | None = None
    parser_version: str | None = None
    raw_content_checksum: str | None = None
    """SHA-256 hex of the raw summary JSON bytes (links plays to registered artifact)."""
    source_uri: str | None = None
    """Optional URI for the raw payload (e.g. file URI or API hint) — stored on provenance."""
    extra: dict[str, Any] = field(default_factory=dict)

    def resolve_team(self, connector_key: str, external_id: str) -> TeamId | None:
        """Typical pattern: ``connector_key`` = ``\"espn\"``, ``external_id`` = numeric team id string."""
        k = f"{connector_key}:{external_id}"
        return self.team_id_by_external_ref.get(k)

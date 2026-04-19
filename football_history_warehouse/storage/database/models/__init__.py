"""
ORM table definitions for the warehouse (persistence layer only).

Import this module before Alembic ``env.py`` reads ``Base.metadata`` so all
tables register. Domain Pydantic models remain the semantic source of truth;
these rows map 1:1-ish to those shapes for load/save.
"""

from __future__ import annotations

from football_history_warehouse.storage.database.models.tables_competition import (
    DriveRow,
    GameRow,
    PlayRow,
)
from football_history_warehouse.storage.database.models.tables_import import (
    ImportJobRow,
    SourceArtifactRow,
)
from football_history_warehouse.storage.database.models.tables_org import (
    LeagueRow,
    SeasonRow,
    TeamRow,
)
from football_history_warehouse.storage.database.models.tables_provenance import (
    ProvenanceRecordRow,
)

__all__ = [
    "DriveRow",
    "GameRow",
    "ImportJobRow",
    "LeagueRow",
    "PlayRow",
    "ProvenanceRecordRow",
    "SeasonRow",
    "SourceArtifactRow",
    "TeamRow",
]

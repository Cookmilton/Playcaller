"""
Domain models for normalized football history.

Canonical entities are immutable Pydantic models with explicit provenance.
Import :class:`Play`, :class:`Game`, etc. from this package or from
``football_history_warehouse.domain.models`` (re-export barrel).
"""

from __future__ import annotations

from football_history_warehouse.domain.competition import Drive, Game, Play, PlayOutcome
from football_history_warehouse.domain.organizations import League, Season, Team
from football_history_warehouse.domain.provenance import ImportJob, ProvenanceEntry, SourceMetadata

__all__ = [
    "Drive",
    "Game",
    "ImportJob",
    "League",
    "Play",
    "PlayOutcome",
    "ProvenanceEntry",
    "Season",
    "SourceMetadata",
    "Team",
]

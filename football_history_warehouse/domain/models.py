"""
Barrel re-exports for canonical domain models.

Prefer ``from football_history_warehouse.domain import Play`` or imports from
``organizations``, ``competition``, and ``provenance`` for clearer dependency graphs in larger codebases.
"""

from __future__ import annotations

from football_history_warehouse.domain import (
    Drive,
    Game,
    ImportJob,
    League,
    Play,
    PlayOutcome,
    ProvenanceEntry,
    Season,
    SourceMetadata,
    Team,
)

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

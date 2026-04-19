"""Filter objects for football queries (semantic layer — no SQL)."""

from __future__ import annotations

from dataclasses import dataclass

from football_history_warehouse.domain.enums import PlayFamily, PlayResultCategory


@dataclass(frozen=True, slots=True)
class PlayQueryFilter:
    """
    Optional predicates for play lists. All fields are ANDed.

    Accepts enum members or raw strings (for forward-compatible DB values).
    """

    offense_team_id: str | None = None
    defense_team_id: str | None = None
    play_families: tuple[PlayFamily | str, ...] | None = None
    result_categories: tuple[PlayResultCategory | str, ...] | None = None

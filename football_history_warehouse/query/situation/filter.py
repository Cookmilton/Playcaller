"""
Composable football situation filter for play queries.

Compose with :func:`dataclasses.replace` (or small helpers below) to layer
constraints: e.g. base season filter + red-zone + two-minute bucket.

**Scope:** require at least one of ``game_id``, ``league_id``, or ``season_id``
before running warehouse-wide play queries (enforced in the repository).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from football_history_warehouse.domain.enums import PlayFamily, PlayResultCategory
from football_history_warehouse.query.filters import PlayQueryFilter
from football_history_warehouse.query.situation.buckets import (
    ClockBucket,
    DistanceBucket,
    FieldPositionBucket,
    ScoreDifferentialBucket,
)


@dataclass(frozen=True, slots=True)
class PlaySituationFilter:
    """
    AND-combined predicates for play rows. ``None`` / empty tuple means “no constraint”.

    **Booleans** ``requires_*`` are positive filters only (``True`` = must match).
    Set ``False`` is treated as no constraint; use only ``True`` to enable.
    """

    # --- scope (identity / schedule context) ---
    league_id: str | None = None
    season_id: str | None = None
    game_id: str | None = None
    offense_team_id: str | None = None
    defense_team_id: str | None = None

    # --- clock / structure ---
    quarters: tuple[int, ...] | None = None
    """1-based ``period`` values (regulation + OT per warehouse scheme)."""

    clock_bucket: ClockBucket | None = None

    downs: tuple[int, ...] | None = None
    """Down values 1–4 to include."""

    distance_yards_min: int | None = None
    distance_yards_max: int | None = None
    distance_bucket: DistanceBucket | None = None

    # --- field position ---
    yards_to_goal_min: int | None = None
    yards_to_goal_max: int | None = None
    field_position_bucket: FieldPositionBucket | None = None

    requires_red_zone: bool | None = None
    """``True``: ``yards_to_goal_line <= 20`` (and not null)."""

    requires_backed_up: bool | None = None
    """``True``: ``yards_to_goal_line >= 90``."""

    requires_short_yardage: bool | None = None
    """``True``: ``1 <= distance <= 3`` (and distance not null)."""

    requires_fourth_down: bool | None = None
    """
    ``True``: ``down == 4``.

    **Note:** true “four-down territory” (go-for-it field position heuristics) is
    **deferred** — this flag only selects fourth-down snaps for v1 proof data.
    """

    # --- score ---
    score_differential_bucket: ScoreDifferentialBucket | None = None

    # --- play shape / outcome ---
    play_families: tuple[PlayFamily | str, ...] | None = None
    play_type_detail_contains: str | None = None
    """Case-sensitive SQL ``LIKE`` substring on ``play_type_detail`` (optional)."""

    result_categories: tuple[PlayResultCategory | str, ...] | None = None

    def with_play_query_filter(self, legacy: PlayQueryFilter) -> PlaySituationFilter:
        """Overlay non-``None`` fields from a :class:`~football_history_warehouse.query.filters.PlayQueryFilter`."""
        kwargs: dict = {}
        if legacy.offense_team_id is not None:
            kwargs["offense_team_id"] = legacy.offense_team_id
        if legacy.defense_team_id is not None:
            kwargs["defense_team_id"] = legacy.defense_team_id
        if legacy.play_families:
            kwargs["play_families"] = legacy.play_families
        if legacy.result_categories:
            kwargs["result_categories"] = legacy.result_categories
        return replace(self, **kwargs) if kwargs else self

    def has_scope(self) -> bool:
        """True if the filter restricts league, season, or game."""
        return bool(self.game_id or self.league_id or self.season_id)

    def with_offense_team(self, team_id: str) -> PlaySituationFilter:
        """
        Return a filter narrowed to snaps where ``team_id`` is the offense.

        Raises if ``offense_team_id`` is already set to a different team.
        """
        if self.offense_team_id is not None and self.offense_team_id != team_id:
            raise ValueError(
                f"PlaySituationFilter already has offense_team_id={self.offense_team_id!r}; "
                f"cannot narrow to {team_id!r}"
            )
        return replace(self, offense_team_id=team_id)


def validate_situation_has_scope(situation: PlaySituationFilter) -> None:
    """Used by play queries and analytics; rejects unbounded warehouse scans."""
    if not situation.has_scope():
        raise ValueError(
            "PlaySituationFilter must include at least one of game_id, league_id, or season_id "
            "to bound the play query."
        )

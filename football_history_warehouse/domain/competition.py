"""
Game, drive, play, and outcome — on-field canonical history.

**Situation convention (Play):** ``offense_points_before_snap``,
``defense_points_before_snap``, and ``score_differential_offense_perspective``
refer to the **snap** (or equivalent start-of-play moment), not the post-play
state. Downstream analytics should derive post-play score from the following
play or from game state fields on ``Game`` when final.

**Yards:** ``yards_gained`` is **net** yards credited to the offense for the
play when the feed allows a single number; attachment of penalty yards to the
same play vs the next is **normalization policy** — document per league in
``rules`` later. Use ``None`` when the feed only gives qualitative outcome.

**Period index:** ``period`` is 1-based: ``1..regulation_period_count`` for
regulation; overtime periods continue as ``regulation_period_count + k`` unless
a league-specific scheme is documented and applied consistently in normalization.

**Source-specific data:** only in ``source_extensions``; keys should be
namespaced (e.g. ``espn.play_type_id``) to avoid collisions across providers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from football_history_warehouse.domain.base import CanonicalModel
from football_history_warehouse.domain.enums import (
    DriveResultBucket,
    FieldSide,
    GameStatus,
    PlayFamily,
    PlayResultCategory,
)
from football_history_warehouse.domain.identifiers import (
    DriveId,
    GameId,
    LeagueId,
    PlayId,
    PlayerId,
    SeasonId,
    TeamId,
    VenueId,
)
from football_history_warehouse.domain.provenance import ProvenanceEntry


class Game(CanonicalModel):
    """
    One scheduled or completed match between two teams.

    Scores are **final** when ``status`` is ``FINAL``; for in-progress feeds,
    scores may be partial snapshots — prefer play-by-play reconstruction for
    historical accuracy when possible.
    """

    game_id: GameId
    season_id: SeasonId
    league_id: LeagueId
    home_team_id: TeamId
    away_team_id: TeamId
    status: GameStatus
    scheduled_start_utc: datetime | None = Field(
        default=None,
        description="Kickoff or league-scheduled start in UTC when known.",
    )
    home_score_final: int | None = Field(default=None, ge=0)
    away_score_final: int | None = Field(default=None, ge=0)
    regulation_period_count: int = Field(
        default=4,
        ge=1,
        le=8,
        description="Typically 4; college may use same field with OT handled separately.",
    )
    overtime_periods_played: int | None = Field(
        default=None,
        ge=0,
        description="Count of overtime periods completed; null if unknown or N/A.",
    )
    venue_id: VenueId | None = None
    attendance: int | None = Field(default=None, ge=0)
    neutral_site: bool | None = Field(
        default=None,
        description="Null if unknown; True for neutral-site games.",
    )
    provenance: tuple[ProvenanceEntry, ...] = Field(default_factory=tuple)
    source_extensions: dict[str, Any] = Field(
        default_factory=dict,
        description="Namespaced non-canonical fields retained for audit/debug.",
    )


class Drive(CanonicalModel):
    """A sequence of plays with one offense on the field."""

    drive_id: DriveId
    game_id: GameId
    offense_team_id: TeamId
    defense_team_id: TeamId
    drive_order: int = Field(
        ...,
        ge=0,
        description="Zero-based order of this drive within the game.",
    )
    start_period: int | None = Field(default=None, ge=1)
    end_period: int | None = Field(default=None, ge=1)
    result_bucket: DriveResultBucket | None = None
    net_yards: int | None = None
    play_count_official: int | None = Field(default=None, ge=0)
    time_of_possession_seconds: int | None = Field(default=None, ge=0)
    start_score_offense: int | None = Field(
        default=None,
        ge=0,
        description="Points for the offensive team at drive start.",
    )
    start_score_defense: int | None = Field(
        default=None,
        ge=0,
        description="Points for the defensive team at drive start.",
    )
    provenance: tuple[ProvenanceEntry, ...] = Field(default_factory=tuple)
    source_extensions: dict[str, Any] = Field(default_factory=dict)


class PlayOutcome(CanonicalModel):
    """
    Normalized result of the play for filtering and coaching analytics.

    Flags are **nullable** when the feed does not support them; ``False`` means
    explicitly false from source, not unknown.
    """

    result_category: PlayResultCategory
    is_first_down_gained: bool | None = None
    is_touchdown: bool | None = None
    is_turnover: bool | None = None
    is_safety: bool | None = None
    is_score_on_play: bool | None = Field(
        default=None,
        description="Any scoring change attributed to this play.",
    )
    chain_advanced: bool | None = Field(
        default=None,
        description="True if offense earned a new set of downs on this play.",
    )
    touchback: bool | None = None
    fair_catch: bool | None = None
    down_after_play: int | None = Field(default=None, ge=1, le=4)
    distance_after_play: int | None = Field(default=None, ge=0)
    notes: str | None = Field(
        default=None,
        description="Short normalization note; not shown as primary UI copy.",
    )


class Play(CanonicalModel):
    """
    Atomic play row in canonical history (may include administrative no-ops).

    Participant ids reference ``PlayerId`` rows not modeled in this module yet;
    nulls are expected when roster data is missing or privacy-limited.
    """

    play_id: PlayId
    game_id: GameId
    drive_id: DriveId | None = Field(
        default=None,
        description="Null when drive boundaries are unknown or not yet aligned.",
    )
    sequence_in_game: int = Field(..., ge=0)
    sequence_in_drive: int | None = Field(default=None, ge=0)
    period: int | None = Field(
        default=None,
        ge=1,
        description="1-based period index including overtime per warehouse scheme.",
    )
    clock_seconds_remaining_in_period: int | None = Field(
        default=None,
        ge=0,
        description="Seconds left in the current period; null if clock unknown.",
    )
    down: int | None = Field(default=None, ge=1, le=4)
    distance: int | None = Field(
        default=None,
        ge=0,
        description="Yards to gain for a new first down.",
    )
    yards_to_goal_line: int | None = Field(
        default=None,
        ge=1,
        le=99,
        description="Yards from offense goal line to opponent end zone (standard cube).",
    )
    field_side: FieldSide | None = None
    offense_team_id: TeamId
    defense_team_id: TeamId
    offense_points_before_snap: int | None = Field(default=None, ge=0)
    defense_points_before_snap: int | None = Field(default=None, ge=0)
    score_differential_offense_perspective: int | None = Field(
        default=None,
        description="Offense score minus defense score at snap.",
    )
    play_family: PlayFamily
    play_type_detail: str | None = Field(
        default=None,
        description="Finer type string; normalize to internal vocabulary over time.",
    )
    passer_player_id: PlayerId | None = None
    qb_player_id: PlayerId | None = Field(
        default=None,
        description="When distinct from passer (e.g. trick play).",
    )
    rusher_player_id: PlayerId | None = None
    target_player_id: PlayerId | None = None
    primary_ballcarrier_player_id: PlayerId | None = None
    outcome: PlayOutcome
    flag_penalty: bool = False
    penalty_accepted: bool | None = None
    penalty_yards: int | None = None
    counts_toward_offense_stats: bool | None = Field(
        default=None,
        description="False for some no-plays; null if undetermined.",
    )
    is_sack: bool = False
    is_scramble: bool = False
    is_no_play_from_penalty: bool = False
    is_spike: bool = False
    is_kneel: bool = False
    yards_gained: int | None = Field(
        default=None,
        description="Signed net yards for offense; null if not quantified.",
    )
    description_text: str | None = Field(
        default=None,
        description="Human description from feed; not used for business logic.",
    )
    provenance: tuple[ProvenanceEntry, ...] = Field(default_factory=tuple)
    source_extensions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("clock_seconds_remaining_in_period")
    @classmethod
    def _reasonable_clock(cls, v: int | None) -> int | None:
        if v is None:
            return v
        # Regulation quarters up to 15 min; OT may differ — cap loosely to catch typos.
        if v > 3600:
            raise ValueError("clock_seconds_remaining_in_period unrealistically large")
        return v

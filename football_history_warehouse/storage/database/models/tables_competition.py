"""Games, drives, plays (play outcome columns live on plays for queryability)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from football_history_warehouse.storage.database.base import Base


def _json_type():
    return JSON().with_variant(JSONB(), "postgresql")


class GameRow(Base):
    __tablename__ = "games"
    __table_args__ = (Index("ix_games_league_season", "league_id", "season_id"),)

    game_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    season_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("seasons.season_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    league_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("leagues.league_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    home_team_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("teams.team_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    away_team_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("teams.team_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scheduled_start_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    home_score_final: Mapped[int | None] = mapped_column(Integer)
    away_score_final: Mapped[int | None] = mapped_column(Integer)
    regulation_period_count: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    overtime_periods_played: Mapped[int | None] = mapped_column(Integer)
    venue_id: Mapped[str | None] = mapped_column(String(64))
    attendance: Mapped[int | None] = mapped_column(Integer)
    neutral_site: Mapped[bool | None] = mapped_column(Boolean)
    source_extensions: Mapped[dict[str, Any]] = mapped_column(_json_type(), nullable=False)
    row_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class DriveRow(Base):
    __tablename__ = "drives"
    __table_args__ = (UniqueConstraint("game_id", "drive_order", name="uq_drives_game_order"),)

    drive_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    game_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("games.game_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    offense_team_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("teams.team_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    defense_team_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("teams.team_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    drive_order: Mapped[int] = mapped_column(Integer, nullable=False)
    start_period: Mapped[int | None] = mapped_column(Integer)
    end_period: Mapped[int | None] = mapped_column(Integer)
    result_bucket: Mapped[str | None] = mapped_column(String(32))
    net_yards: Mapped[int | None] = mapped_column(Integer)
    play_count_official: Mapped[int | None] = mapped_column(Integer)
    time_of_possession_seconds: Mapped[int | None] = mapped_column(Integer)
    start_score_offense: Mapped[int | None] = mapped_column(Integer)
    start_score_defense: Mapped[int | None] = mapped_column(Integer)
    source_extensions: Mapped[dict[str, Any]] = mapped_column(_json_type(), nullable=False)
    row_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class PlayRow(Base):
    """
    Play fact row: denormalized league_id + season_id for league/season filters without joining games.

    Must stay consistent with parent game (enforced in application or future trigger).
    """

    __tablename__ = "plays"
    __table_args__ = (
        UniqueConstraint("game_id", "sequence_in_game", name="uq_plays_game_sequence"),
        CheckConstraint("down IS NULL OR (down >= 1 AND down <= 4)", name="ck_plays_down"),
        CheckConstraint(
            "yards_to_goal_line IS NULL OR (yards_to_goal_line >= 1 AND yards_to_goal_line <= 99)",
            name="ck_plays_ytg",
        ),
        CheckConstraint(
            "clock_seconds_remaining_in_period IS NULL OR clock_seconds_remaining_in_period <= 3600",
            name="ck_plays_clock_sane",
        ),
        Index("ix_plays_season_id", "season_id"),
        Index("ix_plays_offense_team", "offense_team_id"),
        Index("ix_plays_defense_team", "defense_team_id"),
        Index("ix_plays_down_distance", "down", "distance"),
        Index("ix_plays_yards_to_goal", "yards_to_goal_line"),
        Index("ix_plays_play_family", "play_family"),
        Index("ix_plays_result_category", "result_category"),
        Index("ix_plays_period_clock", "period", "clock_seconds_remaining_in_period"),
        Index("ix_plays_league_season", "league_id", "season_id"),
    )

    play_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    game_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("games.game_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    season_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("seasons.season_id", ondelete="RESTRICT"),
        nullable=False,
    )
    league_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("leagues.league_id", ondelete="RESTRICT"),
        nullable=False,
    )
    drive_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("drives.drive_id", ondelete="SET NULL"),
        index=True,
    )
    sequence_in_game: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence_in_drive: Mapped[int | None] = mapped_column(Integer)
    period: Mapped[int | None] = mapped_column(Integer, index=True)
    clock_seconds_remaining_in_period: Mapped[int | None] = mapped_column(Integer)
    down: Mapped[int | None] = mapped_column(Integer)
    distance: Mapped[int | None] = mapped_column(Integer)
    yards_to_goal_line: Mapped[int | None] = mapped_column(Integer)
    field_side: Mapped[str | None] = mapped_column(String(16))
    offense_team_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("teams.team_id", ondelete="RESTRICT"),
        nullable=False,
    )
    defense_team_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("teams.team_id", ondelete="RESTRICT"),
        nullable=False,
    )
    offense_points_before_snap: Mapped[int | None] = mapped_column(Integer)
    defense_points_before_snap: Mapped[int | None] = mapped_column(Integer)
    score_differential_offense_perspective: Mapped[int | None] = mapped_column(Integer)
    play_family: Mapped[str] = mapped_column(String(32), nullable=False)
    play_type_detail: Mapped[str | None] = mapped_column(String(128))
    passer_player_id: Mapped[str | None] = mapped_column(String(64))
    qb_player_id: Mapped[str | None] = mapped_column(String(64))
    rusher_player_id: Mapped[str | None] = mapped_column(String(64))
    target_player_id: Mapped[str | None] = mapped_column(String(64))
    primary_ballcarrier_player_id: Mapped[str | None] = mapped_column(String(64))
    result_category: Mapped[str] = mapped_column(String(32), nullable=False)
    is_first_down_gained: Mapped[bool | None] = mapped_column(Boolean)
    is_touchdown: Mapped[bool | None] = mapped_column(Boolean)
    is_turnover: Mapped[bool | None] = mapped_column(Boolean)
    is_safety: Mapped[bool | None] = mapped_column(Boolean)
    is_score_on_play: Mapped[bool | None] = mapped_column(Boolean)
    chain_advanced: Mapped[bool | None] = mapped_column(Boolean)
    touchback: Mapped[bool | None] = mapped_column(Boolean)
    fair_catch: Mapped[bool | None] = mapped_column(Boolean)
    down_after_play: Mapped[int | None] = mapped_column(Integer)
    distance_after_play: Mapped[int | None] = mapped_column(Integer)
    outcome_notes: Mapped[str | None] = mapped_column(Text())
    flag_penalty: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    penalty_accepted: Mapped[bool | None] = mapped_column(Boolean)
    penalty_yards: Mapped[int | None] = mapped_column(Integer)
    counts_toward_offense_stats: Mapped[bool | None] = mapped_column(Boolean)
    is_sack: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_scramble: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_no_play_from_penalty: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_spike: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_kneel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    yards_gained: Mapped[int | None] = mapped_column(Integer)
    description_text: Mapped[str | None] = mapped_column(Text())
    source_extensions: Mapped[dict[str, Any]] = mapped_column(_json_type(), nullable=False)
    row_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

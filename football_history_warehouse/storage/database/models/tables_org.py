"""Leagues, seasons, teams."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from football_history_warehouse.storage.database.base import Base


class LeagueRow(Base):
    __tablename__ = "leagues"

    league_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    family: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    short_code: Mapped[str | None] = mapped_column(String(32), index=True)
    competition_tier_default: Mapped[str] = mapped_column(String(32), nullable=False)
    rules_profile_key: Mapped[str | None] = mapped_column(String(64))
    row_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SeasonRow(Base):
    __tablename__ = "seasons"
    __table_args__ = (
        UniqueConstraint("league_id", "year_label", name="uq_seasons_league_year_label"),
    )

    season_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    league_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("leagues.league_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    year_label: Mapped[str] = mapped_column(String(32), nullable=False)
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    row_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TeamRow(Base):
    __tablename__ = "teams"
    __table_args__ = (Index("ix_teams_league_abbreviation", "league_id", "abbreviation"),)

    team_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    league_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("leagues.league_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    abbreviation: Mapped[str | None] = mapped_column(String(16))
    nickname: Mapped[str | None] = mapped_column(String(128))
    city: Mapped[str | None] = mapped_column(String(128))
    conference_id: Mapped[str | None] = mapped_column(String(64))
    division_id: Mapped[str | None] = mapped_column(String(64))
    row_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

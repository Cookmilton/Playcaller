"""Canonical domain model construction and validation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

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
from football_history_warehouse.domain.enums import (
    CompetitionTier,
    DriveResultBucket,
    GameStatus,
    ImportJobStatus,
    LeagueFamily,
    PlayFamily,
    PlayResultCategory,
)
from football_history_warehouse.domain.identifiers import (
    DriveId,
    GameId,
    ImportJobId,
    LeagueId,
    PlayId,
    PlayerId,
    SeasonId,
    TeamId,
)


def _prov(job: str = "job-1") -> tuple[ProvenanceEntry, ...]:
    mid = ImportJobId(job)
    return (
        ProvenanceEntry(
            import_job_id=mid,
            source=SourceMetadata(
                source_system="test",
                observed_at=datetime(2024, 1, 1, tzinfo=UTC),
            ),
            warehouse_written_at=datetime(2024, 1, 2, tzinfo=UTC),
        ),
    )


def test_play_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Play(
            play_id=PlayId("p1"),
            game_id=GameId("g1"),
            sequence_in_game=1,
            offense_team_id=TeamId("t1"),
            defense_team_id=TeamId("t2"),
            play_family=PlayFamily.PASS,
            outcome=PlayOutcome(result_category=PlayResultCategory.COMPLETE),
            provenance=_prov(),
            typo_field=123,  # type: ignore[call-arg]
        )


def test_play_clock_validator() -> None:
    with pytest.raises(ValidationError):
        Play(
            play_id=PlayId("p1"),
            game_id=GameId("g1"),
            sequence_in_game=1,
            clock_seconds_remaining_in_period=99999,
            offense_team_id=TeamId("t1"),
            defense_team_id=TeamId("t2"),
            play_family=PlayFamily.PASS,
            outcome=PlayOutcome(result_category=PlayResultCategory.COMPLETE),
            provenance=_prov(),
        )


def test_full_graph_minimal() -> None:
    league = League(
        league_id=LeagueId("nfl"),
        family=LeagueFamily.NFL,
        name="National Football League",
        short_code="NFL",
        competition_tier_default=CompetitionTier.REGULAR,
        provenance=_prov(),
    )
    season = Season(
        season_id=SeasonId("2024"),
        league_id=league.league_id,
        year_label="2024",
        provenance=_prov(),
    )
    home = Team(
        team_id=TeamId("sea"),
        league_id=league.league_id,
        full_name="Seattle Seahawks",
        abbreviation="SEA",
        provenance=_prov(),
    )
    away = Team(
        team_id=TeamId("lar"),
        league_id=league.league_id,
        full_name="Los Angeles Rams",
        abbreviation="LAR",
        provenance=_prov(),
    )
    game = Game(
        game_id=GameId("g1"),
        season_id=season.season_id,
        league_id=league.league_id,
        home_team_id=home.team_id,
        away_team_id=away.team_id,
        status=GameStatus.FINAL,
        home_score_final=24,
        away_score_final=17,
        provenance=_prov(),
    )
    drive = Drive(
        drive_id=DriveId("d1"),
        game_id=game.game_id,
        offense_team_id=home.team_id,
        defense_team_id=away.team_id,
        drive_order=0,
        result_bucket=DriveResultBucket.TOUCHDOWN,
        provenance=_prov(),
    )
    play = Play(
        play_id=PlayId("pl1"),
        game_id=game.game_id,
        drive_id=drive.drive_id,
        sequence_in_game=42,
        sequence_in_drive=7,
        period=4,
        clock_seconds_remaining_in_period=128,
        down=3,
        distance=7,
        yards_to_goal_line=42,
        offense_team_id=home.team_id,
        defense_team_id=away.team_id,
        offense_points_before_snap=24,
        defense_points_before_snap=17,
        score_differential_offense_perspective=7,
        play_family=PlayFamily.PASS,
        passer_player_id=PlayerId("qb1"),
        target_player_id=PlayerId("wr1"),
        outcome=PlayOutcome(
            result_category=PlayResultCategory.COMPLETE,
            is_first_down_gained=True,
        ),
        is_sack=False,
        flag_penalty=False,
        yards_gained=12,
        provenance=_prov(),
        source_extensions={"espn.play_id": "abc"},
    )
    assert play.source_extensions["espn.play_id"] == "abc"
    job = ImportJob(
        job_id=ImportJobId("job-1"),
        status=ImportJobStatus.SUCCEEDED,
        started_at=datetime(2024, 9, 1, tzinfo=UTC),
        completed_at=datetime(2024, 9, 1, 1, tzinfo=UTC),
        source_label="espn_week1",
    )
    assert job.records_attempted is None

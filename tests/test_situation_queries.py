"""Football situation filters (composable PlaySituationFilter)."""

from __future__ import annotations

import pytest

from football_history_warehouse.config.database import DatabaseConfig
from football_history_warehouse.domain.enums import PlayFamily, PlayResultCategory
from football_history_warehouse.query import (
    ClockBucket,
    DistanceBucket,
    FieldPositionBucket,
    FootballHistoryQueryService,
    PageParams,
    PlaySituationFilter,
    ScoreDifferentialBucket,
)
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import create_warehouse_engine, session_scope
from football_history_warehouse.storage.database.models import PlayRow
from football_history_warehouse.storage.repositories.transactional import insert_minimal_warehouse_chain


def test_situation_requires_scope(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'sit.sqlite'}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url, echo_sql=False))
    try:
        with session_scope(engine) as session:
            svc = FootballHistoryQueryService(session)
            with pytest.raises(ValueError, match="PlaySituationFilter must include"):
                svc.list_plays_matching_situation(PlaySituationFilter(), page=PageParams(limit=10, offset=0))
    finally:
        engine.dispose()


def test_red_zone_and_clock_and_season_scope(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'sit2.sqlite'}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url, echo_sql=False))
    try:
        with session_scope(engine) as session:
            ids = insert_minimal_warehouse_chain(
                session,
                job_id="job-s1",
                league_id="league-s",
                season_id="season-s",
                home_team_id="team-h",
                away_team_id="team-a",
                game_id="game-s1",
                drive_id="drive-s1",
                play_id="play-s1",
            )
            session.add(
                PlayRow(
                    play_id="play-s2-rz",
                    game_id=ids.game_id,
                    season_id=ids.season_id,
                    league_id=ids.league_id,
                    drive_id=ids.drive_id,
                    sequence_in_game=2,
                    sequence_in_drive=2,
                    period=2,
                    clock_seconds_remaining_in_period=90,
                    down=2,
                    distance=8,
                    yards_to_goal_line=15,
                    field_side=None,
                    offense_team_id=ids.home_team_id,
                    defense_team_id=ids.away_team_id,
                    offense_points_before_snap=7,
                    defense_points_before_snap=7,
                    score_differential_offense_perspective=0,
                    play_family=PlayFamily.PASS.value,
                    play_type_detail="shotgun",
                    passer_player_id=None,
                    qb_player_id=None,
                    rusher_player_id=None,
                    target_player_id=None,
                    primary_ballcarrier_player_id=None,
                    result_category=PlayResultCategory.INCOMPLETE.value,
                    is_first_down_gained=False,
                    is_touchdown=False,
                    is_turnover=False,
                    is_safety=False,
                    is_score_on_play=False,
                    chain_advanced=None,
                    touchback=None,
                    fair_catch=None,
                    down_after_play=None,
                    distance_after_play=None,
                    outcome_notes=None,
                    flag_penalty=False,
                    penalty_accepted=None,
                    penalty_yards=None,
                    counts_toward_offense_stats=None,
                    is_sack=False,
                    is_scramble=False,
                    is_no_play_from_penalty=False,
                    is_spike=False,
                    is_kneel=False,
                    yards_gained=None,
                    description_text=None,
                    source_extensions={},
                )
            )
            p0 = session.get(PlayRow, ids.play_id)
            assert p0 is not None
            p0.distance = 2

        with session_scope(engine) as session:
            svc = FootballHistoryQueryService(session)
            rz = svc.list_plays_matching_situation(
                PlaySituationFilter(
                    season_id=ids.season_id,
                    requires_red_zone=True,
                ),
                page=PageParams(limit=50, offset=0),
            )
            assert len(rz.items) == 1
            assert str(rz.items[0].play_id) == "play-s2-rz"

            two_min = svc.list_plays_matching_situation(
                PlaySituationFilter(
                    league_id=ids.league_id,
                    season_id=ids.season_id,
                    clock_bucket=ClockBucket.TWO_MINUTE_OR_LESS,
                ),
                page=PageParams(limit=50, offset=0),
            )
            assert len(two_min.items) == 1
            assert two_min.items[0].clock_seconds_remaining_in_period == 90

            short = svc.list_plays_matching_situation(
                PlaySituationFilter(
                    game_id=ids.game_id,
                    distance_bucket=DistanceBucket.SHORT,
                ),
                page=PageParams(limit=50, offset=0),
            )
            assert len(short.items) == 1
            assert short.items[0].distance == 2

            tied = svc.list_plays_matching_situation(
                PlaySituationFilter(
                    season_id=ids.season_id,
                    score_differential_bucket=ScoreDifferentialBucket.TIED,
                ),
                page=PageParams(limit=50, offset=0),
            )
            assert len(tied.items) == 2

            detail = svc.list_plays_matching_situation(
                PlaySituationFilter(
                    season_id=ids.season_id,
                    play_type_detail_contains="shotgun",
                ),
                page=PageParams(limit=50, offset=0),
            )
            assert len(detail.items) == 1
    finally:
        engine.dispose()


def test_fourth_down_placeholder(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'sit4.sqlite'}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url, echo_sql=False))
    try:
        with session_scope(engine) as session:
            ids = insert_minimal_warehouse_chain(
                session,
                job_id="job-s4",
                league_id="league-s4",
                season_id="season-s4",
                home_team_id="th4",
                away_team_id="ta4",
                game_id="g4",
                drive_id="d4",
                play_id="p4a",
            )
            p = session.get(PlayRow, "p4a")
            assert p is not None
            p.down = 4
            session.add(
                PlayRow(
                    play_id="p4b",
                    game_id=ids.game_id,
                    season_id=ids.season_id,
                    league_id=ids.league_id,
                    drive_id=ids.drive_id,
                    sequence_in_game=2,
                    sequence_in_drive=2,
                    period=4,
                    clock_seconds_remaining_in_period=400,
                    down=1,
                    distance=10,
                    yards_to_goal_line=65,
                    field_side=None,
                    offense_team_id=ids.home_team_id,
                    defense_team_id=ids.away_team_id,
                    offense_points_before_snap=0,
                    defense_points_before_snap=0,
                    score_differential_offense_perspective=0,
                    play_family=PlayFamily.RUN.value,
                    play_type_detail=None,
                    passer_player_id=None,
                    qb_player_id=None,
                    rusher_player_id=None,
                    target_player_id=None,
                    primary_ballcarrier_player_id=None,
                    result_category=PlayResultCategory.UNKNOWN.value,
                    is_first_down_gained=None,
                    is_touchdown=None,
                    is_turnover=None,
                    is_safety=None,
                    is_score_on_play=None,
                    chain_advanced=None,
                    touchback=None,
                    fair_catch=None,
                    down_after_play=None,
                    distance_after_play=None,
                    outcome_notes=None,
                    flag_penalty=False,
                    penalty_accepted=None,
                    penalty_yards=None,
                    counts_toward_offense_stats=None,
                    is_sack=False,
                    is_scramble=False,
                    is_no_play_from_penalty=False,
                    is_spike=False,
                    is_kneel=False,
                    yards_gained=2,
                    description_text=None,
                    source_extensions={},
                )
            )

        with session_scope(engine) as session:
            svc = FootballHistoryQueryService(session)
            q = svc.list_plays_matching_situation(
                PlaySituationFilter(game_id=ids.game_id, requires_fourth_down=True),
                page=PageParams(limit=50, offset=0),
            )
            assert len(q.items) == 1
            assert q.items[0].down == 4
    finally:
        engine.dispose()


def test_field_position_bucket_backed_up(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'sit5.sqlite'}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url, echo_sql=False))
    try:
        with session_scope(engine) as session:
            ids = insert_minimal_warehouse_chain(
                session,
                job_id="j5",
                league_id="l5",
                season_id="s5",
                home_team_id="h5",
                away_team_id="a5",
                game_id="g5",
                drive_id="d5",
                play_id="p5",
            )
            p = session.get(PlayRow, "p5")
            assert p is not None
            p.yards_to_goal_line = 92

        with session_scope(engine) as session:
            svc = FootballHistoryQueryService(session)
            bu = svc.list_plays_matching_situation(
                PlaySituationFilter(
                    season_id="s5",
                    field_position_bucket=FieldPositionBucket.BACKED_UP,
                ),
                page=PageParams(limit=10, offset=0),
            )
            assert len(bu.items) == 1
    finally:
        engine.dispose()

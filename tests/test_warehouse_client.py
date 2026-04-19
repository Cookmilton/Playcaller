"""Public FootballWarehouseClient boundary (no direct repository usage)."""

from __future__ import annotations

import pytest

from football_history_warehouse.config.database import DatabaseConfig
from football_history_warehouse.consumer import (
    FootballWarehouseClient,
    PlaySituationFilter,
    PageParams,
)
from football_history_warehouse.domain.enums import GameStatus, PlayFamily, PlayResultCategory
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import create_warehouse_engine, session_scope
from football_history_warehouse.storage.database.models import GameRow, PlayRow
from football_history_warehouse.storage.repositories.transactional import insert_minimal_warehouse_chain


def test_client_review_tendency_outcomes(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'client.sqlite'}"
    upgrade_to_head(database_url=url)
    client = FootballWarehouseClient.from_database_url(url)
    try:
        with session_scope(client._engine) as session:
            ids = insert_minimal_warehouse_chain(
                session,
                job_id="job-c1",
                league_id="league-c",
                season_id="season-c",
                home_team_id="team-hc",
                away_team_id="team-ac",
                game_id="game-c1",
                drive_id="drive-c1",
                play_id="play-c1",
            )
            g = session.get(GameRow, ids.game_id)
            assert g is not None
            g.status = GameStatus.FINAL.value
            g.home_score_final = 21
            g.away_score_final = 14
            session.add(
                PlayRow(
                    play_id="play-c2",
                    game_id=ids.game_id,
                    season_id=ids.season_id,
                    league_id=ids.league_id,
                    drive_id=ids.drive_id,
                    sequence_in_game=2,
                    sequence_in_drive=2,
                    period=1,
                    clock_seconds_remaining_in_period=400,
                    down=3,
                    distance=2,
                    yards_to_goal_line=18,
                    field_side=None,
                    offense_team_id=ids.home_team_id,
                    defense_team_id=ids.away_team_id,
                    offense_points_before_snap=7,
                    defense_points_before_snap=7,
                    score_differential_offense_perspective=0,
                    play_family=PlayFamily.PASS.value,
                    play_type_detail=None,
                    passer_player_id=None,
                    qb_player_id=None,
                    rusher_player_id=None,
                    target_player_id=None,
                    primary_ballcarrier_player_id=None,
                    result_category=PlayResultCategory.TOUCHDOWN.value,
                    is_first_down_gained=False,
                    is_touchdown=True,
                    is_turnover=False,
                    is_safety=False,
                    is_score_on_play=True,
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
                    yards_gained=18,
                    description_text="TD pass",
                    source_extensions={},
                )
            )

        review = client.get_game_review_package(ids.game_id)
        assert review is not None
        assert review.score.is_final_on_record is True

        plays_page = client.get_plays_by_situation(
            PlaySituationFilter(game_id=ids.game_id),
            page=PageParams(limit=50, offset=0),
        )
        assert len(plays_page.plays) == 2

        ten = client.get_team_tendency_summary(
            ids.home_team_id,
            situation=PlaySituationFilter(season_id=ids.season_id),
        )
        assert ten.total_plays == 2
        assert ten.play_family_counts.get(PlayFamily.RUN.value) == 1
        assert ten.play_family_counts.get(PlayFamily.PASS.value) == 1

        rz = client.get_situation_outcome_summary(
            PlaySituationFilter(season_id=ids.season_id, requires_red_zone=True),
        )
        assert rz.total_plays == 1
        assert rz.touchdowns >= 1

        conflict = PlaySituationFilter(season_id=ids.season_id, offense_team_id=ids.away_team_id)
        with pytest.raises(ValueError, match="already has offense_team_id"):
            client.get_team_tendency_summary(ids.home_team_id, situation=conflict)
    finally:
        client.dispose()


def test_client_requires_scope_for_plays(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'client2.sqlite'}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url, echo_sql=False))
    client = FootballWarehouseClient(engine)
    try:
        with pytest.raises(ValueError, match="PlaySituationFilter must include"):
            client.get_plays_by_situation(PlaySituationFilter(), page=PageParams(limit=10, offset=0))
    finally:
        client.dispose()

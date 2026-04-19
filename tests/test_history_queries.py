"""Football history query service and repository."""

from __future__ import annotations

from datetime import datetime, timezone

from football_history_warehouse.config.database import DatabaseConfig
from football_history_warehouse.domain.enums import GameStatus, PlayFamily, PlayResultCategory
from football_history_warehouse.query import (
    FootballHistoryQueryService,
    PageParams,
    PlayQueryFilter,
)
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import create_warehouse_engine, session_scope
from football_history_warehouse.storage.database.models import GameRow, PlayRow
from football_history_warehouse.storage.repositories.transactional import insert_minimal_warehouse_chain


def test_history_queries_games_drives_plays(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'hq.sqlite'}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url, echo_sql=False))
    try:
        with session_scope(engine) as session:
            ids = insert_minimal_warehouse_chain(
                session,
                job_id="job-q1",
                league_id="league-q",
                season_id="season-q",
                home_team_id="team-home",
                away_team_id="team-away",
                game_id="game-q1",
                drive_id="drive-q1",
                play_id="play-q1",
            )
            # Second play: different family / result for filters
            session.add(
                PlayRow(
                    play_id="play-q2",
                    game_id=ids.game_id,
                    season_id=ids.season_id,
                    league_id=ids.league_id,
                    drive_id=ids.drive_id,
                    sequence_in_game=2,
                    sequence_in_drive=2,
                    period=1,
                    clock_seconds_remaining_in_period=800,
                    down=2,
                    distance=6,
                    yards_to_goal_line=71,
                    field_side=None,
                    offense_team_id=ids.away_team_id,
                    defense_team_id=ids.home_team_id,
                    offense_points_before_snap=0,
                    defense_points_before_snap=0,
                    score_differential_offense_perspective=0,
                    play_family=PlayFamily.PASS.value,
                    play_type_detail=None,
                    passer_player_id=None,
                    qb_player_id=None,
                    rusher_player_id=None,
                    target_player_id=None,
                    primary_ballcarrier_player_id=None,
                    result_category=PlayResultCategory.COMPLETE.value,
                    is_first_down_gained=True,
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
                    yards_gained=12,
                    description_text=None,
                    source_extensions={},
                )
            )
            # Touch scheduled start for ordering
            g = session.get(GameRow, ids.game_id)
            assert g is not None
            g.scheduled_start_utc = datetime(2024, 9, 8, 17, 0, tzinfo=timezone.utc)

        with session_scope(engine) as session:
            svc = FootballHistoryQueryService(session)
            game = svc.get_game_by_id("missing")
            assert game is None

            game = svc.get_game_by_id(ids.game_id)
            assert game is not None
            assert str(game.game_id) == ids.game_id
            assert str(game.league_id) == ids.league_id

            page = svc.list_games(league_id=ids.league_id, page=PageParams(limit=10, offset=0))
            assert len(page.items) == 1
            assert not page.has_more

            by_team = svc.list_games(team_id=ids.home_team_id, page=PageParams(limit=10, offset=0))
            assert len(by_team.items) == 1

            drives = svc.list_drives_for_game(ids.game_id)
            assert len(drives) == 1
            assert str(drives[0].drive_id) == ids.drive_id

            all_plays = svc.list_plays_for_game(ids.game_id, page=PageParams(limit=50, offset=0))
            assert len(all_plays.items) == 2
            assert not all_plays.has_more

            pass_only = svc.list_plays_for_game(
                ids.game_id,
                play_filter=PlayQueryFilter(play_families=(PlayFamily.PASS,)),
                page=PageParams(limit=50, offset=0),
            )
            assert len(pass_only.items) == 1
            assert pass_only.items[0].play_family == PlayFamily.PASS

            offense_away = svc.list_plays_for_game(
                ids.game_id,
                play_filter=PlayQueryFilter(offense_team_id=ids.away_team_id),
                page=PageParams(limit=50, offset=0),
            )
            assert len(offense_away.items) == 1
            assert str(offense_away.items[0].offense_team_id) == ids.away_team_id

            complete = svc.list_plays_for_game(
                ids.game_id,
                play_filter=PlayQueryFilter(result_categories=(PlayResultCategory.COMPLETE,)),
                page=PageParams(limit=50, offset=0),
            )
            assert len(complete.items) == 1
            assert complete.items[0].outcome.result_category == PlayResultCategory.COMPLETE

            defense_home = svc.list_plays_for_game(
                ids.game_id,
                play_filter=PlayQueryFilter(defense_team_id=ids.home_team_id),
                page=PageParams(limit=50, offset=0),
            )
            assert len(defense_home.items) == 1
    finally:
        engine.dispose()


def test_pagination_has_more(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'hq2.sqlite'}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url, echo_sql=False))
    try:
        with session_scope(engine) as session:
            insert_minimal_warehouse_chain(
                session,
                job_id="job-p1",
                league_id="league-p",
                season_id="season-p",
                home_team_id="th",
                away_team_id="ta",
                game_id="g1",
                drive_id="d1",
                play_id="p1",
            )
            session.add(
                GameRow(
                    game_id="g2",
                    season_id="season-p",
                    league_id="league-p",
                    home_team_id="th",
                    away_team_id="ta",
                    status=GameStatus.SCHEDULED.value,
                    scheduled_start_utc=datetime(2024, 9, 15, 17, 0, tzinfo=timezone.utc),
                    home_score_final=None,
                    away_score_final=None,
                    regulation_period_count=4,
                    overtime_periods_played=None,
                    venue_id=None,
                    attendance=None,
                    neutral_site=None,
                    source_extensions={},
                )
            )

        with session_scope(engine) as session:
            svc = FootballHistoryQueryService(session)
            page = svc.list_games(league_id="league-p", page=PageParams(limit=1, offset=0))
            assert len(page.items) == 1
            assert page.has_more
            page2 = svc.list_games(league_id="league-p", page=PageParams(limit=1, offset=1))
            assert len(page2.items) == 1
            assert not page2.has_more
    finally:
        engine.dispose()

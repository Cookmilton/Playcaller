"""Game review package builder."""

from __future__ import annotations

from football_history_warehouse.config.database import DatabaseConfig
from football_history_warehouse.domain.enums import GameStatus
from football_history_warehouse.review import GameReviewPackage, build_game_review_package
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import create_warehouse_engine, session_scope
from football_history_warehouse.storage.database.models import GameRow
from football_history_warehouse.storage.repositories.transactional import insert_minimal_warehouse_chain


def test_build_game_review_package(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'review.sqlite'}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url, echo_sql=False))
    try:
        with session_scope(engine) as session:
            ids = insert_minimal_warehouse_chain(
                session,
                job_id="job-r1",
                league_id="league-r",
                season_id="season-r",
                home_team_id="team-home-r",
                away_team_id="team-away-r",
                game_id="game-r1",
                drive_id="drive-r1",
                play_id="play-r1",
            )
            g = session.get(GameRow, ids.game_id)
            assert g is not None
            g.status = GameStatus.FINAL.value
            g.home_score_final = 24
            g.away_score_final = 17

        with session_scope(engine) as session:
            pkg = build_game_review_package(session, ids.game_id)
        assert pkg is not None
        assert isinstance(pkg, GameReviewPackage)
        assert pkg.game_id == ids.game_id
        assert pkg.score.is_final_on_record is True
        assert pkg.score.home_points == 24
        assert pkg.score.away_points == 17
        assert len(pkg.drive_timeline) == 1
        assert len(pkg.play_timeline) == 1
        assert pkg.drive_timeline[0].play_count == 1
        assert pkg.matchup.home.team_id == ids.home_team_id
        assert pkg.matchup.season_year_label == "2024"
        assert len(pkg.tendencies.by_offense_team) == 2
        assert pkg.tendencies.by_offense_team[0].total_plays == 1
        assert pkg.tendencies.by_offense_team[1].total_plays == 0
        assert pkg.outcomes.total_touchdowns_scored >= 0
        dumped = pkg.model_dump(mode="json")
        assert dumped["schema_version"] == "1"
        assert "play_timeline" in dumped
    finally:
        engine.dispose()


def test_review_missing_game(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'rev2.sqlite'}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url, echo_sql=False))
    try:
        with session_scope(engine) as session:
            assert build_game_review_package(session, "nope") is None
    finally:
        engine.dispose()

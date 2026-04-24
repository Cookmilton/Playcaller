"""CompetitionQueryRepository: portable ordering for SQLite vs Postgres."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, select

from football_history_warehouse.domain.enums import GameStatus, ImportJobStatus
from football_history_warehouse.query.repositories.competition import (
    CompetitionQueryRepository,
    _game_schedule_order_by,
)
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import session_scope
from football_history_warehouse.storage.database.models import GameRow, ImportJobRow
from football_history_warehouse.storage.repositories.transactional import insert_minimal_warehouse_chain


def test_fetch_game_rows_page_sqlite_does_not_emit_nulls_last_syntax(tmp_path) -> None:
    """Regression: SQLite engines without NULLS LAST support must not see that clause."""
    url = f"sqlite+pysqlite:///{tmp_path / 'comp.sqlite'}"
    upgrade_to_head(database_url=url)
    engine = create_engine(url)
    stmt = select(GameRow.game_id).order_by(*_game_schedule_order_by())
    compiled = str(stmt.compile(dialect=engine.dialect))
    assert "NULLS LAST" not in compiled.upper()
    assert "NULLS FIRST" not in compiled.upper()
    engine.dispose()


def test_fetch_game_rows_page_orders_null_scheduled_start_last(tmp_path) -> None:
    """Games with missing schedule sort after those with a concrete scheduled_start_utc."""
    url = f"sqlite+pysqlite:///{tmp_path / 'comp2.sqlite'}"
    upgrade_to_head(database_url=url)
    engine = create_engine(url)
    try:
        with session_scope(engine) as session:
            insert_minimal_warehouse_chain(
                session,
                job_id="job-a",
                league_id="L",
                season_id="S",
                home_team_id="H",
                away_team_id="A",
                game_id="game-null-sched",
                drive_id="drive-a",
                play_id="play-a",
            )
            now = datetime.now(timezone.utc)
            session.add(
                ImportJobRow(
                    job_id="job-b",
                    status=ImportJobStatus.RUNNING.value,
                    started_at=now,
                    completed_at=None,
                    source_label="integration_test",
                    trigger="test",
                    records_attempted=None,
                    records_succeeded=None,
                    records_failed=None,
                    error_summary=None,
                    config_snapshot={},
                )
            )
            session.add(
                GameRow(
                    game_id="game-dated",
                    season_id="S",
                    league_id="L",
                    home_team_id="H",
                    away_team_id="A",
                    status=GameStatus.SCHEDULED.value,
                    scheduled_start_utc=datetime(2025, 6, 1, 18, 0, tzinfo=timezone.utc),
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
            repo = CompetitionQueryRepository(session)
            rows, _has_more = repo.fetch_game_rows_page(
                league_id=None,
                season_id=None,
                team_id=None,
                limit=20,
                offset=0,
            )
        assert [r.game_id for r in rows] == ["game-dated", "game-null-sched"]
    finally:
        engine.dispose()

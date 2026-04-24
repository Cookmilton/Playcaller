"""Warehouse game inventory via FootballWarehouseClient (consumer boundary)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, select

from football_history_warehouse.consumer import FootballWarehouseClient, GameInventoryFilters
from football_history_warehouse.domain.enums import GameStatus, ImportJobStatus
from football_history_warehouse.query.services.inventory import _game_inventory_order_by
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import session_scope
from football_history_warehouse.storage.database.models import GameRow, ImportJobRow
from football_history_warehouse.storage.repositories.transactional import insert_minimal_warehouse_chain


def test_list_games_inventory_minimal_chain(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'inv.sqlite'}"
    upgrade_to_head(database_url=url)
    client = FootballWarehouseClient.from_database_url(url)
    try:
        with session_scope(client._engine) as session:
            insert_minimal_warehouse_chain(
                session,
                job_id="job-inv-1",
                league_id="league-inv",
                season_id="season-inv",
                home_team_id="team-h-inv",
                away_team_id="team-a-inv",
                game_id="game-inv-1",
                drive_id="drive-inv-1",
                play_id="play-inv-1",
            )
        page = client.list_games_inventory(GameInventoryFilters())
        assert len(page.games) == 1
        g = page.games[0]
        assert g.game_id == "game-inv-1"
        assert g.league_id == "league-inv"
        assert g.season_id == "season-inv"
        assert g.drive_count == 1
        assert g.play_count == 1
        assert g.import_job_id == "job-inv-1"

        filtered = client.list_games_inventory(GameInventoryFilters(league_id="league-inv"))
        assert len(filtered.games) == 1

        miss = client.list_games_inventory(GameInventoryFilters(league_id="nope"))
        assert len(miss.games) == 0
    finally:
        client.dispose()


def test_list_games_inventory_filter_import_job(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'inv2.sqlite'}"
    upgrade_to_head(database_url=url)
    client = FootballWarehouseClient.from_database_url(url)
    try:
        with session_scope(client._engine) as session:
            insert_minimal_warehouse_chain(
                session,
                job_id="job-xyz",
                league_id="L",
                season_id="S",
                home_team_id="H",
                away_team_id="A",
                game_id="G2",
                drive_id="D2",
                play_id="P2",
            )
        hit = client.list_games_inventory(GameInventoryFilters(import_job_id="job-xyz"))
        assert len(hit.games) == 1
        miss = client.list_games_inventory(GameInventoryFilters(import_job_id="other"))
        assert len(miss.games) == 0
    finally:
        client.dispose()


def test_list_games_inventory_sqlite_does_not_emit_nulls_last_syntax(tmp_path) -> None:
    """Regression: SQLite engines without NULLS LAST support must not see that clause."""
    url = f"sqlite+pysqlite:///{tmp_path / 'inv3.sqlite'}"
    upgrade_to_head(database_url=url)
    engine = create_engine(url)
    stmt = select(GameRow.game_id).order_by(*_game_inventory_order_by())
    compiled = str(stmt.compile(dialect=engine.dialect))
    assert "NULLS LAST" not in compiled.upper()
    assert "NULLS FIRST" not in compiled.upper()
    engine.dispose()


def test_list_games_inventory_orders_null_scheduled_start_last(tmp_path) -> None:
    """Games with missing schedule sort after those with a concrete scheduled_start_utc."""
    url = f"sqlite+pysqlite:///{tmp_path / 'inv4.sqlite'}"
    upgrade_to_head(database_url=url)
    client = FootballWarehouseClient.from_database_url(url)
    try:
        with session_scope(client._engine) as session:
            insert_minimal_warehouse_chain(
                session,
                job_id="job-a",
                league_id="L",
                season_id="S",
                home_team_id="H",
                away_team_id="A",
                game_id="game-null-first-id",
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
                    game_id="game-dated-second-id",
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
        page = client.list_games_inventory(GameInventoryFilters())
        assert len(page.games) == 2
        ids = [g.game_id for g in page.games]
        assert ids == ["game-dated-second-id", "game-null-first-id"]
    finally:
        client.dispose()

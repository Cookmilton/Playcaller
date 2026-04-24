"""Warehouse inventory page state detection (env, schema, counts, failures)."""

from __future__ import annotations

from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import session_scope
from football_history_warehouse.storage.repositories.transactional import insert_minimal_warehouse_chain

from playcaller.ui.warehouse_page_state import (
    WarehouseInventoryState,
    detect_warehouse_inventory_state,
    format_warehouse_sidebar_pill_html,
)


def test_detect_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("FOOTBALL_WAREHOUSE_DATABASE_URL", raising=False)
    monkeypatch.delenv("PLAYCALLER_DEV_MODE", raising=False)
    ctx = detect_warehouse_inventory_state()
    assert ctx.state == WarehouseInventoryState.NOT_CONFIGURED
    assert ctx.client is None
    assert "Not configured" in format_warehouse_sidebar_pill_html(ctx)


def test_detect_schema_not_initialized(monkeypatch, tmp_path) -> None:
    path = tmp_path / "noschema.sqlite"
    url = f"sqlite+pysqlite:///{path}"
    monkeypatch.setenv("FOOTBALL_WAREHOUSE_DATABASE_URL", url)
    ctx = detect_warehouse_inventory_state()
    try:
        assert ctx.state == WarehouseInventoryState.SCHEMA_NOT_INITIALIZED
        assert ctx.client is not None
    finally:
        if ctx.client is not None:
            ctx.client.dispose()


def test_detect_empty(monkeypatch, tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'empty.sqlite'}"
    upgrade_to_head(database_url=url)
    monkeypatch.setenv("FOOTBALL_WAREHOUSE_DATABASE_URL", url)
    ctx = detect_warehouse_inventory_state()
    try:
        assert ctx.state == WarehouseInventoryState.EMPTY
        assert ctx.game_count == 0
        assert ctx.client is not None
    finally:
        if ctx.client is not None:
            ctx.client.dispose()


def test_detect_populated(monkeypatch, tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'pop.sqlite'}"
    upgrade_to_head(database_url=url)
    client = None
    try:
        from football_history_warehouse.consumer import FootballWarehouseClient

        client = FootballWarehouseClient.from_database_url(url)
        with session_scope(client._engine) as session:
            insert_minimal_warehouse_chain(
                session,
                job_id="job-wps",
                league_id="L-wps",
                season_id="S-wps",
                home_team_id="H-wps",
                away_team_id="A-wps",
                game_id="game-wps",
                drive_id="drive-wps",
                play_id="play-wps",
            )
    finally:
        if client is not None:
            client.dispose()

    monkeypatch.setenv("FOOTBALL_WAREHOUSE_DATABASE_URL", url)
    ctx = detect_warehouse_inventory_state()
    try:
        assert ctx.state == WarehouseInventoryState.POPULATED
        assert ctx.game_count == 1
        assert ctx.client is not None
    finally:
        if ctx.client is not None:
            ctx.client.dispose()


def test_detect_query_failed_corrupt_file(monkeypatch, tmp_path) -> None:
    path = tmp_path / "bad.sqlite"
    path.write_bytes(b"this is not sqlite")
    url = f"sqlite+pysqlite:///{path}"
    monkeypatch.setenv("FOOTBALL_WAREHOUSE_DATABASE_URL", url)
    ctx = detect_warehouse_inventory_state()
    try:
        assert ctx.state == WarehouseInventoryState.QUERY_FAILED
        assert ctx.exc_type is not None
        assert ctx.traceback_text is not None
    finally:
        if ctx.client is not None:
            ctx.client.dispose()

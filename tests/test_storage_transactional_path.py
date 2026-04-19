"""Transactional insert path: import → competition graph → provenance (SQLite + optional Postgres)."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select

from football_history_warehouse.config.database import DatabaseConfig
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import create_warehouse_engine, session_scope
from football_history_warehouse.storage.database.models import (
    GameRow,
    ImportJobRow,
    PlayRow,
    ProvenanceRecordRow,
)
from football_history_warehouse.storage.repositories import insert_minimal_warehouse_chain


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _run_chain_and_assert(url: str) -> None:
    upgrade_to_head(database_url=url)
    cfg = DatabaseConfig(database_url=url)
    engine = create_warehouse_engine(cfg)
    try:
        ids = _unique
        job_id = ids("job")
        league_id = ids("league")
        season_id = ids("season")
        home_id = ids("home")
        away_id = ids("away")
        game_id = ids("game")
        drive_id = ids("drive")
        play_id = ids("play")

        with session_scope(engine) as session:
            out = insert_minimal_warehouse_chain(
                session,
                job_id=job_id,
                league_id=league_id,
                season_id=season_id,
                home_team_id=home_id,
                away_team_id=away_id,
                game_id=game_id,
                drive_id=drive_id,
                play_id=play_id,
                extra_provenance_entities=(("game", game_id),),
            )
            assert out.play_id == play_id

        with session_scope(engine) as session:
            job = session.scalar(select(ImportJobRow).where(ImportJobRow.job_id == job_id))
            assert job is not None
            assert job.config_snapshot == {}

            game = session.scalar(select(GameRow).where(GameRow.game_id == game_id))
            assert game is not None
            assert game.source_extensions == {}
            assert game.league_id == league_id
            assert game.season_id == season_id

            play = session.scalar(select(PlayRow).where(PlayRow.play_id == play_id))
            assert play is not None
            assert play.league_id == league_id
            assert play.season_id == season_id
            assert play.game_id == game_id

            prov = session.scalars(
                select(ProvenanceRecordRow).where(ProvenanceRecordRow.import_job_id == job_id)
            ).all()
            kinds = {(p.entity_type, p.entity_id) for p in prov}
            assert ("play", play_id) in kinds
            assert ("game", game_id) in kinds
    finally:
        engine.dispose()


def test_transactional_insert_sqlite_file(tmp_path) -> None:
    dbfile = tmp_path / "wh_tx.sqlite"
    url = f"sqlite+pysqlite:///{dbfile}"
    _run_chain_and_assert(url)


def test_transactional_insert_postgres_optional() -> None:
    """
    Set FOOTBALL_WAREHOUSE_TEST_POSTGRES_URL to a disposable Postgres URL to
    validate JSON defaults and DDL against a live server (e.g. local docker).
    """
    url = os.environ.get("FOOTBALL_WAREHOUSE_TEST_POSTGRES_URL", "").strip()
    if not url.startswith("postgresql"):
        pytest.skip("FOOTBALL_WAREHOUSE_TEST_POSTGRES_URL not set to a postgresql URL")
    _run_chain_and_assert(url)

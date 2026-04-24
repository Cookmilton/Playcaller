"""End-to-end minimal ingest: fixture → SQLite → row counts and idempotency."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select

from football_history_warehouse.ingest.from_json import (
    ingest_espn_summary_payload,
    ingest_from_json_file,
    league_code_and_display_for_espn_sport,
)
from football_history_warehouse.ingest.normalize import normalize_espn_summary
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database.models import GameRow, LeagueRow, SeasonRow, TeamRow
from football_history_warehouse.storage.database.session import session_scope

FIXTURE_PACKERS = Path(__file__).resolve().parent / "fixtures" / "espn_summary_packers_lions_401772891.json"


def test_e2e_ingest_idempotent(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'e2e.sqlite'}"
    upgrade_to_head(database_url=url)

    r1 = ingest_from_json_file(FIXTURE_PACKERS, database_url=url)
    assert r1.game_id == "espn:401772891"
    assert r1.was_new is True

    engine = __import__("football_history_warehouse.storage.database.engine", fromlist=["create_warehouse_engine"]).create_warehouse_engine(
        __import__("football_history_warehouse.config.database", fromlist=["DatabaseConfig"]).DatabaseConfig(database_url=url)
    )
    try:
        with session_scope(engine) as s:
            assert int(s.scalar(select(func.count()).select_from(LeagueRow)) or 0) == 1
            assert int(s.scalar(select(func.count()).select_from(SeasonRow)) or 0) == 1
            assert int(s.scalar(select(func.count()).select_from(TeamRow)) or 0) == 2
            assert int(s.scalar(select(func.count()).select_from(GameRow)) or 0) == 1
            g = s.get(GameRow, r1.game_id)
            assert g is not None
            assert g.home_score_final == 24 and g.away_score_final == 31
    finally:
        engine.dispose()

    r2 = ingest_from_json_file(FIXTURE_PACKERS, database_url=url)
    assert r2.rows_updated >= 1
    assert r2.rows_created == 0

    engine = __import__("football_history_warehouse.storage.database.engine", fromlist=["create_warehouse_engine"]).create_warehouse_engine(
        __import__("football_history_warehouse.config.database", fromlist=["DatabaseConfig"]).DatabaseConfig(database_url=url)
    )
    try:
        with session_scope(engine) as s:
            assert int(s.scalar(select(func.count()).select_from(GameRow)) or 0) == 1
    finally:
        engine.dispose()

    raw = json.loads(FIXTURE_PACKERS.read_text(encoding="utf-8"))
    b = normalize_espn_summary(raw)
    assert b.game.external_id == "401772891"


def test_ingest_espn_summary_payload_matches_file_ingest(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'dict.sqlite'}"
    upgrade_to_head(database_url=url)
    raw = json.loads(FIXTURE_PACKERS.read_text(encoding="utf-8"))
    r = ingest_espn_summary_payload(raw, database_url=url, league="NFL")
    assert r is not None
    assert r.game_id == "espn:401772891"
    assert r.was_new is True


def test_league_code_and_display_for_espn_sport() -> None:
    assert league_code_and_display_for_espn_sport("nfl") == ("NFL", None)
    assert league_code_and_display_for_espn_sport("college-football") == ("NCAAF", "NCAA Football")
    assert league_code_and_display_for_espn_sport("ufl") == ("UFL", "United Football League")

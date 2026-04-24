"""Tests for football_history_warehouse.ingest.writer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from football_history_warehouse.ingest.normalize import normalize_espn_summary
from football_history_warehouse.config.database import DatabaseConfig
from football_history_warehouse.ingest.writer import (
    create_or_update_game,
    get_or_create_league,
    get_or_create_season,
    get_or_create_team,
    ingest_game_bundle,
)
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import create_warehouse_engine
from football_history_warehouse.storage.database.session import session_scope

FIXTURE_PACKERS = Path(__file__).resolve().parent / "fixtures" / "espn_summary_packers_lions_401772891.json"


def _engine(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path / 'w.sqlite'}"
    upgrade_to_head(database_url=url)
    return create_warehouse_engine(DatabaseConfig(database_url=url))


def test_get_or_create_league_idempotent(tmp_path) -> None:
    engine = _engine(tmp_path)
    raw = json.loads(FIXTURE_PACKERS.read_text(encoding="utf-8"))
    bundle = normalize_espn_summary(raw)
    with session_scope(engine) as s:
        r1, c1 = get_or_create_league(s, bundle.league)
        r2, c2 = get_or_create_league(s, bundle.league)
    assert c1 is True and c2 is False
    assert r1.league_id == r2.league_id


def test_ingest_game_twice_updates_scores(tmp_path) -> None:
    engine = _engine(tmp_path)
    raw = json.loads(FIXTURE_PACKERS.read_text(encoding="utf-8"))
    bundle = normalize_espn_summary(raw)
    with session_scope(engine) as s:
        r1 = ingest_game_bundle(s, bundle)
    assert r1.was_new is True
    assert r1.rows_created >= 1

    raw2 = json.loads(FIXTURE_PACKERS.read_text(encoding="utf-8"))
    bundle2 = normalize_espn_summary(raw2)
    with session_scope(engine) as s:
        r2 = ingest_game_bundle(s, bundle2)
    assert r2.was_new is False
    assert r2.rows_updated >= 1


def test_transaction_rollback_on_error(tmp_path) -> None:
    engine = _engine(tmp_path)
    raw = json.loads(FIXTURE_PACKERS.read_text(encoding="utf-8"))
    bundle = normalize_espn_summary(raw)
    with pytest.raises(RuntimeError), session_scope(engine) as s:
        ingest_game_bundle(s, bundle)
        raise RuntimeError("abort")

    from sqlalchemy import func, select

    from football_history_warehouse.storage.database.models import GameRow

    with session_scope(engine) as s:
        n = s.scalar(select(func.count()).select_from(GameRow))
    assert int(n or 0) == 0


def test_constraint_violation_rolls_back(tmp_path) -> None:
    """Duplicate game PK in the same transaction fails; nothing commits."""
    engine = _engine(tmp_path)
    raw = json.loads(FIXTURE_PACKERS.read_text(encoding="utf-8"))
    bundle = normalize_espn_summary(raw)
    from football_history_warehouse.storage.database.models import GameRow

    gid = f"espn:{bundle.game.external_id}"
    with pytest.raises(IntegrityError):
        with session_scope(engine) as s:
            league, _ = get_or_create_league(s, bundle.league)
            season, _ = get_or_create_season(s, bundle.season, league)
            home, _ = get_or_create_team(s, bundle.home_team, league)
            away, _ = get_or_create_team(s, bundle.away_team, league)
            create_or_update_game(s, bundle.game, season=season, home=home, away=away)
            s.add(
                GameRow(
                    game_id=gid,
                    season_id=season.season_id,
                    league_id=league.league_id,
                    home_team_id=home.team_id,
                    away_team_id=away.team_id,
                    status=bundle.game.status,
                    scheduled_start_utc=bundle.game.scheduled_start_utc,
                    home_score_final=bundle.game.home_score,
                    away_score_final=bundle.game.away_score,
                    regulation_period_count=4,
                    source_extensions={},
                )
            )
            s.flush()

    from sqlalchemy import func, select

    with session_scope(engine) as s:
        n = s.scalar(select(func.count()).select_from(GameRow))
    assert int(n or 0) == 0

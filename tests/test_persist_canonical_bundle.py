"""Persist CanonicalGameBundle → ORM (SQLite + optional Postgres)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select

from football_history_warehouse.config.database import DatabaseConfig
from football_history_warehouse.domain.identifiers import GameId, ImportJobId, LeagueId, SeasonId, TeamId
from football_history_warehouse.normalization.context import GameNormalizationContext
from football_history_warehouse.normalization.espn import normalize_espn_summary_parse_result
from football_history_warehouse.parsers.espn_summary import parse_espn_game_summary_json_file
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import create_warehouse_engine, session_scope
from football_history_warehouse.storage.database.models import (
    DriveRow,
    GameRow,
    ImportJobRow,
    PlayRow,
    ProvenanceRecordRow,
)
from football_history_warehouse.storage.repositories import (
    PersistCanonicalBundleParams,
    persist_canonical_game_bundle,
)
from football_history_warehouse.validation import validate_canonical_game_bundle
from football_history_warehouse.validation.issues import ValidationFailedError

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_live_synthetic.json"


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _ctx(job_id: str, game_id: str) -> GameNormalizationContext:
    return GameNormalizationContext(
        league_id=LeagueId("league-nfl-test"),
        season_id=SeasonId("season-2024-test"),
        game_id=GameId(game_id),
        team_id_by_external_ref={
            "espn:10": TeamId("team-nyg"),
            "espn:14": TeamId("team-lar"),
        },
        import_job_id=ImportJobId(job_id),
        observed_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        parser_version="test-parser",
    )


def _bundle_for_url(job_id: str, game_id: str):
    parsed = parse_espn_game_summary_json_file(FIXTURE)
    return normalize_espn_summary_parse_result(parsed, _ctx(job_id, game_id))


def _run_persist_and_assert(url: str) -> None:
    upgrade_to_head(database_url=url)
    cfg = DatabaseConfig(database_url=url)
    engine = create_warehouse_engine(cfg)
    try:
        job_id = _unique("job")
        game_id = _unique("game")
        bundle = _bundle_for_url(job_id, game_id)

        v = validate_canonical_game_bundle(bundle)
        assert v.ok_to_persist

        with session_scope(engine) as session:
            out = persist_canonical_game_bundle(
                session,
                bundle,
                PersistCanonicalBundleParams(import_job_id=job_id, validation_result=v),
            )
            assert out.game_id == game_id
            assert len(out.drive_ids) == 2
            assert len(out.play_ids) == 4
            assert out.provenance_rows_written == 4

        with session_scope(engine) as session:
            job = session.scalar(select(ImportJobRow).where(ImportJobRow.job_id == job_id))
            assert job is not None

            game = session.scalar(select(GameRow).where(GameRow.game_id == game_id))
            assert game is not None
            assert game.league_id == str(bundle.game.league_id)
            assert game.season_id == str(bundle.game.season_id)

            drives = session.scalars(select(DriveRow).where(DriveRow.game_id == game_id)).all()
            assert len(drives) == 2

            plays = session.scalars(select(PlayRow).where(PlayRow.game_id == game_id)).all()
            assert len(plays) == 4
            for pl in plays:
                assert pl.league_id == game.league_id
                assert pl.season_id == game.season_id

            prov_n = session.scalar(
                select(func.count()).select_from(ProvenanceRecordRow).where(
                    ProvenanceRecordRow.import_job_id == job_id
                )
            )
            assert prov_n == 4
    finally:
        engine.dispose()


def test_persist_canonical_bundle_sqlite(tmp_path) -> None:
    dbfile = tmp_path / "wh_canon.sqlite"
    url = f"sqlite+pysqlite:///{dbfile}"
    _run_persist_and_assert(url)


def test_persist_canonical_bundle_postgres_optional() -> None:
    url = os.environ.get("FOOTBALL_WAREHOUSE_TEST_POSTGRES_URL", "").strip()
    if not url.startswith("postgresql"):
        pytest.skip("FOOTBALL_WAREHOUSE_TEST_POSTGRES_URL not set to a postgresql URL")
    _run_persist_and_assert(url)


def test_persist_rejects_mismatched_provenance_job_id() -> None:
    """All provenance entries must reference the same import_job_id as params."""
    from football_history_warehouse.domain import Game
    from football_history_warehouse.domain.enums import GameStatus
    from football_history_warehouse.domain.provenance import ProvenanceEntry, SourceMetadata
    from football_history_warehouse.normalization.bundle import CanonicalGameBundle

    now = datetime.now(timezone.utc)
    sm = SourceMetadata(
        source_system="x",
        source_record_id="1",
        observed_at=now,
    )
    bad_entry = ProvenanceEntry(
        import_job_id=ImportJobId("other-job"),
        source=sm,
        warehouse_written_at=now,
    )
    g = Game(
        game_id=GameId("g1"),
        season_id=SeasonId("s1"),
        league_id=LeagueId("l1"),
        home_team_id=TeamId("h"),
        away_team_id=TeamId("a"),
        status=GameStatus.SCHEDULED,
        provenance=(bad_entry,),
    )
    bundle = CanonicalGameBundle(game=g, drives=(), plays=(), notices=())
    cfg = DatabaseConfig(database_url="sqlite+pysqlite:///:memory:")
    engine = create_warehouse_engine(cfg)
    upgrade_to_head(database_url=str(engine.url))
    with pytest.raises(ValueError, match="Provenance import_job_id"):
        with session_scope(engine) as session:
            persist_canonical_game_bundle(
                session,
                bundle,
                PersistCanonicalBundleParams(import_job_id="expected-job"),
            )
    engine.dispose()


def test_persist_blocked_when_validation_fails() -> None:
    from football_history_warehouse.domain import Game
    from football_history_warehouse.domain.enums import GameStatus
    from football_history_warehouse.normalization.bundle import CanonicalGameBundle

    g = Game(
        game_id=GameId("g-bad"),
        season_id=SeasonId("s"),
        league_id=LeagueId("l"),
        home_team_id=TeamId("t1"),
        away_team_id=TeamId("t1"),
        status=GameStatus.SCHEDULED,
    )
    bundle = CanonicalGameBundle(game=g, drives=(), plays=(), notices=())
    v = validate_canonical_game_bundle(bundle)
    assert not v.ok_to_persist

    cfg = DatabaseConfig(database_url="sqlite+pysqlite:///:memory:")
    engine = create_warehouse_engine(cfg)
    upgrade_to_head(database_url=str(engine.url))
    with pytest.raises(ValidationFailedError):
        with session_scope(engine) as session:
            persist_canonical_game_bundle(
                session,
                bundle,
                PersistCanonicalBundleParams(import_job_id="job", validation_result=v),
            )
    engine.dispose()

"""End-to-end ESPN summary import (SQLite)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from sqlalchemy import select

from football_history_warehouse.config.database import DatabaseConfig
from football_history_warehouse.pipeline.espn_summary_import import (
    EspnSummaryImportSpec,
    import_espn_summary_game_file,
    load_manifest,
    spec_from_manifest_entry,
)
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import create_warehouse_engine, session_scope
from football_history_warehouse.query import get_import_job_pipeline_report
from football_history_warehouse.storage.database.models import GameRow, ImportJobRow

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_live_synthetic.json"
FIXTURE2 = Path(__file__).resolve().parent / "fixtures" / "espn_summary_live_synthetic_002.json"


def _spec() -> EspnSummaryImportSpec:
    return EspnSummaryImportSpec(
        league_id="league-pipe-test",
        season_id="season-2024-pipe",
        season_year_label="2024",
        team_id_by_external_ref={
            "espn:10": "team-nyg",
            "espn:14": "team-lar",
        },
    )


def test_import_persists_game_sqlite(tmp_path) -> None:
    dbfile = tmp_path / "pipe.sqlite"
    url = f"sqlite+pysqlite:///{dbfile}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url, echo_sql=False))
    try:
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        with session_scope(engine) as session:
            r = import_espn_summary_game_file(
                session,
                json_path=FIXTURE,
                spec=_spec(),
                job_id=job_id,
            )
        assert r.outcome == "persisted"
        assert r.game_id == "espn-401test001"
        assert r.checksum_sha256 is not None

        with session_scope(engine) as session:
            g = session.scalar(select(GameRow).where(GameRow.game_id == "espn-401test001"))
            assert g is not None
            assert "warehouse.raw_checksum_sha256" in (g.source_extensions or {})
            job = session.get(ImportJobRow, job_id)
            assert job is not None
            assert job.pipeline_report is not None
            assert job.pipeline_report.get("outcome") == "persisted_ok"
            assert job.pipeline_report.get("import_job_id") == job_id
            loaded = get_import_job_pipeline_report(session, job_id)
            assert loaded == job.pipeline_report
    finally:
        engine.dispose()


def test_duplicate_game_skipped(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'dup_game.sqlite'}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url, echo_sql=False))
    try:
        spec = _spec()
        with session_scope(engine) as session:
            r1 = import_espn_summary_game_file(session, json_path=FIXTURE, spec=spec, job_id="job-a")
        assert r1.outcome == "persisted"

        spec2 = EspnSummaryImportSpec(
            league_id=spec.league_id,
            season_id=spec.season_id,
            team_id_by_external_ref=spec.team_id_by_external_ref,
            game_id_override="espn-401test001",
        )
        with session_scope(engine) as session:
            r2 = import_espn_summary_game_file(session, json_path=FIXTURE2, spec=spec2, job_id="job-b")
        assert r2.outcome == "duplicate_game_skipped"
    finally:
        engine.dispose()


def test_duplicate_raw_skipped(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'dup_raw.sqlite'}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url, echo_sql=False))
    try:
        spec = _spec()
        with session_scope(engine) as session:
            r1 = import_espn_summary_game_file(session, json_path=FIXTURE, spec=spec, job_id="job-1")
        assert r1.outcome == "persisted"

        with session_scope(engine) as session:
            r2 = import_espn_summary_game_file(
                session,
                json_path=FIXTURE,
                spec=spec,
                job_id="job-2",
            )
        assert r2.outcome == "duplicate_raw_skipped"
        assert r2.artifact_id is not None
    finally:
        engine.dispose()


def test_manifest_spec_resolution(tmp_path) -> None:
    mpath = tmp_path / "m.json"
    mpath.write_text(
        json.dumps(
            {
                "league_id": "L1",
                "season_id": "S1",
                "team_map": {"10": "t1", "14": "t2"},
                "games": [{"path": "g.json"}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "g.json").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    defaults, games, mdir = load_manifest(mpath)
    path, spec = spec_from_manifest_entry(mdir, defaults, games[0])
    assert path.exists()
    assert spec.team_id_by_external_ref["espn:10"] == "t1"


def test_second_distinct_fixture_imports(tmp_path) -> None:
    url = f"sqlite+pysqlite:///{tmp_path / 'two_games.sqlite'}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url, echo_sql=False))
    try:
        spec = _spec()
        with session_scope(engine) as session:
            r1 = import_espn_summary_game_file(session, json_path=FIXTURE, spec=spec, job_id="j1")
            r2 = import_espn_summary_game_file(session, json_path=FIXTURE2, spec=spec, job_id="j2")
        assert r1.outcome == "persisted"
        assert r2.outcome == "persisted"
        assert r1.game_id == "espn-401test001"
        assert r2.game_id == "espn-401test002"
    finally:
        engine.dispose()

"""Raw ingest: import jobs + source artifacts (pre-normalization)."""

from __future__ import annotations

import uuid

import pytest

from football_history_warehouse.config.database import DatabaseConfig
from football_history_warehouse.domain.enums import ImportJobStatus
from football_history_warehouse.ingest.checksum import sha256_hex, sha256_hex_iter
from football_history_warehouse.ingest.exceptions import RawIngestError
from football_history_warehouse.ingest.raw import (
    RawIngestService,
    RegisterRawGameFileRequest,
    create_raw_import_job,
    finalize_import_job,
)
from football_history_warehouse.ingest.raw.enums import RawArtifactKind, SourceArtifactIngestStatus
from football_history_warehouse.reporting.raw_adapters import raw_ingest_artifact_report, raw_ingest_job_report
from football_history_warehouse.storage.bootstrap import upgrade_to_head
from football_history_warehouse.storage.database import create_warehouse_engine, session_scope
from football_history_warehouse.storage.database.models import ImportJobRow, SourceArtifactRow


def _jid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def test_sha256_hex_iter_matches_whole_buffer() -> None:
    data = b"abc"
    assert sha256_hex(data) == sha256_hex_iter([data])


def test_register_raw_game_file_persists_artifact(tmp_path) -> None:
    dbfile = tmp_path / "raw.sqlite"
    url = f"sqlite+pysqlite:///{dbfile}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url))
    job_id = _jid("job")
    svc = RawIngestService()
    try:
        with session_scope(engine) as session:
            create_raw_import_job(
                session,
                job_id=job_id,
                source_label="pytest",
                config_snapshot={"batch": "unit"},
            )
            payload = b'{"game": "raw-only"}'
            res = svc.register_raw_game_file(
                session,
                RegisterRawGameFileRequest(
                    import_job_id=job_id,
                    source_system="test_provider",
                    parser_version="0.0.1",
                    content=payload,
                    league_key="nfl",
                    logical_name="game.json",
                    media_type="application/json",
                    extra_metadata={"feed_game_id": "abc"},
                ),
            )
            assert res.checksum_sha256 == sha256_hex(payload)
            assert res.byte_length == len(payload)
            assert res.ingest_status == SourceArtifactIngestStatus.REGISTERED.value

        with session_scope(engine) as session:
            art = session.get(SourceArtifactRow, res.artifact_id)
            assert art is not None
            assert art.artifact_kind == RawArtifactKind.RAW_GAME_FILE.value
            assert art.parser_version == "0.0.1"
            assert art.league_key == "nfl"
            assert art.ingest_status == "registered"
            rep = raw_ingest_artifact_report(art)
            assert rep.content_checksum == res.checksum_sha256
            job = session.get(ImportJobRow, job_id)
            assert job is not None
            assert job.records_attempted == 1
            assert job.records_succeeded == 1
            jr = raw_ingest_job_report(job)
            assert jr.job_id == job_id
    finally:
        engine.dispose()


def test_register_requires_existing_job(tmp_path) -> None:
    dbfile = tmp_path / "raw2.sqlite"
    url = f"sqlite+pysqlite:///{dbfile}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url))
    try:
        with session_scope(engine) as session:
            svc = RawIngestService()
            with pytest.raises(RawIngestError) as ei:
                svc.register_raw_game_file(
                    session,
                    RegisterRawGameFileRequest(
                        import_job_id="missing",
                        source_system="x",
                        parser_version="1",
                        content=b"data",
                    ),
            )
            assert ei.value.code == "import_job_missing"
    finally:
        engine.dispose()


def test_checksum_mismatch_raises(tmp_path) -> None:
    dbfile = tmp_path / "raw3.sqlite"
    url = f"sqlite+pysqlite:///{dbfile}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url))
    job_id = _jid("job")
    try:
        with session_scope(engine) as session:
            create_raw_import_job(session, job_id=job_id, source_label="t", config_snapshot={})
            svc = RawIngestService()
            with pytest.raises(RawIngestError) as ei:
                svc.register_raw_game_file(
                    session,
                    RegisterRawGameFileRequest(
                        import_job_id=job_id,
                        source_system="x",
                        parser_version="1",
                        content=b"data",
                        checksum_sha256="0" * 64,
                    ),
                )
            assert ei.value.code == "checksum_mismatch"
    finally:
        engine.dispose()


def test_create_job_idempotent_conflict(tmp_path) -> None:
    dbfile = tmp_path / "raw4.sqlite"
    url = f"sqlite+pysqlite:///{dbfile}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url))
    job_id = _jid("job")
    try:
        with session_scope(engine) as session:
            create_raw_import_job(session, job_id=job_id, source_label="t", config_snapshot={})
        with session_scope(engine) as session:
            with pytest.raises(RawIngestError) as ei:
                create_raw_import_job(session, job_id=job_id, source_label="t2", config_snapshot={})
            assert ei.value.code == "import_job_exists"
    finally:
        engine.dispose()


def test_register_from_path(tmp_path) -> None:
    dbfile = tmp_path / "raw5.sqlite"
    f = tmp_path / "game.json"
    f.write_bytes(b"{}\n")
    url = f"sqlite+pysqlite:///{dbfile}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url))
    job_id = _jid("job")
    try:
        with session_scope(engine) as session:
            create_raw_import_job(session, job_id=job_id, source_label="t", config_snapshot={})
            svc = RawIngestService()
            res = svc.register_raw_game_file_from_path(
                session,
                path=f,
                import_job_id=job_id,
                source_system="fs",
                parser_version="1.0.0",
            )
            assert res.byte_length == len(b"{}\n")
            art = session.get(SourceArtifactRow, res.artifact_id)
            assert art is not None
            assert art.logical_name == "game.json"
            assert art.uri is not None and art.uri.startswith("file:")
    finally:
        engine.dispose()


def test_finalize_job(tmp_path) -> None:
    dbfile = tmp_path / "raw6.sqlite"
    url = f"sqlite+pysqlite:///{dbfile}"
    upgrade_to_head(database_url=url)
    engine = create_warehouse_engine(DatabaseConfig(database_url=url))
    job_id = _jid("job")
    try:
        with session_scope(engine) as session:
            create_raw_import_job(session, job_id=job_id, source_label="t", config_snapshot={})
            finalize_import_job(session, job_id=job_id, status=ImportJobStatus.SUCCEEDED)
        with session_scope(engine) as session:
            job = session.get(ImportJobRow, job_id)
            assert job is not None
            assert job.status == ImportJobStatus.SUCCEEDED.value
            assert job.completed_at is not None
    finally:
        engine.dispose()

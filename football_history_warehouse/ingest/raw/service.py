"""
Raw ingest service: register bytes and metadata before normalization.

Persists :class:`~football_history_warehouse.storage.database.models.SourceArtifactRow`
rows and links them to :class:`~football_history_warehouse.storage.database.models.ImportJobRow`.
Does not parse vendor formats or write ``plays`` / ``games`` tables.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from football_history_warehouse.domain.enums import ImportJobStatus
from football_history_warehouse.ingest.checksum import sha256_hex
from football_history_warehouse.ingest.exceptions import RawIngestError
from football_history_warehouse.ingest.raw.enums import RawArtifactKind, SourceArtifactIngestStatus
from football_history_warehouse.ingest.raw.models import RegisterRawGameFileRequest, RegisterRawGameFileResult
from football_history_warehouse.storage.database.models import ImportJobRow, SourceArtifactRow
from football_history_warehouse.storage.database.sqlite_pk import allocate_sqlite_bigint_pk


def create_raw_import_job(
    session: Session,
    *,
    job_id: str,
    source_label: str,
    config_snapshot: dict,
    trigger: str | None = "raw_ingest",
) -> ImportJobRow:
    """
    Insert a new import job row. Raises :class:`RawIngestError` if ``job_id`` exists.
    """
    existing = session.get(ImportJobRow, job_id)
    if existing is not None:
        raise RawIngestError("import_job_exists", f"Import job already exists: {job_id!r}")
    now = datetime.now(timezone.utc)
    row = ImportJobRow(
        job_id=job_id,
        status=ImportJobStatus.RUNNING.value,
        started_at=now,
        completed_at=None,
        source_label=source_label,
        trigger=trigger,
        records_attempted=0,
        records_succeeded=0,
        records_failed=0,
        error_summary=None,
        config_snapshot=config_snapshot,
    )
    session.add(row)
    session.flush()
    return row


def get_import_job(session: Session, job_id: str) -> ImportJobRow | None:
    return session.get(ImportJobRow, job_id)


def finalize_import_job(
    session: Session,
    *,
    job_id: str,
    status: ImportJobStatus,
    error_summary: str | None = None,
    pipeline_report: dict[str, Any] | None = None,
) -> ImportJobRow:
    """
    Set terminal job fields. Raises :class:`RawIngestError` if the job is missing.

    When ``pipeline_report`` is set, it is persisted for operator inspection (JSON /
    JSONB); omit to leave any existing value unchanged.
    """
    row = session.get(ImportJobRow, job_id)
    if row is None:
        raise RawIngestError("import_job_missing", f"Unknown import job: {job_id!r}")
    row.status = status.value
    row.completed_at = datetime.now(timezone.utc)
    row.error_summary = error_summary
    if pipeline_report is not None:
        row.pipeline_report = pipeline_report
    session.flush()
    return row


class RawIngestService:
    """Register raw game files and related artifacts (transaction boundaries are caller-owned)."""

    def register_raw_game_file(
        self,
        session: Session,
        request: RegisterRawGameFileRequest,
    ) -> RegisterRawGameFileResult:
        job = session.get(ImportJobRow, request.import_job_id)
        if job is None:
            raise RawIngestError(
                "import_job_missing",
                f"No import job {request.import_job_id!r}; create one with create_raw_import_job first.",
            )

        if not request.parser_version.strip():
            raise RawIngestError("invalid_parser_version", "parser_version must be a non-empty string.")

        if not request.source_system.strip():
            raise RawIngestError("invalid_source_system", "source_system must be a non-empty string.")

        content = request.content
        if not content:
            raise RawIngestError("empty_payload", "Raw game payload is empty.")

        computed = sha256_hex(content)
        if request.checksum_sha256 is not None:
            digest = request.checksum_sha256.strip().lower()
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise RawIngestError(
                    "invalid_checksum",
                    "checksum_sha256 must be a 64-char hex SHA-256 digest when provided.",
                )
            if digest != computed:
                raise RawIngestError(
                    "checksum_mismatch",
                    "checksum_sha256 does not match the provided content bytes.",
                )
        else:
            digest = computed

        observed = request.observed_at or datetime.now(timezone.utc)
        uri = request.uri
        if uri is None and request.logical_name:
            uri = f"inline:{request.logical_name}"

        pk_alloc = allocate_sqlite_bigint_pk(session, SourceArtifactRow, count=1)
        artifact_kw: dict = dict(
            import_job_id=request.import_job_id,
            artifact_kind=RawArtifactKind.RAW_GAME_FILE.value,
            source_system=request.source_system.strip(),
            uri=uri,
            content_checksum=digest,
            byte_length=len(content),
            media_type=request.media_type,
            observed_at=observed,
            extra_metadata=dict(request.extra_metadata),
            league_key=request.league_key,
            parser_version=request.parser_version.strip(),
            ingest_status=SourceArtifactIngestStatus.REGISTERED.value,
            logical_name=request.logical_name,
        )
        if pk_alloc is not None:
            artifact_kw["id"] = pk_alloc[0]

        artifact = SourceArtifactRow(**artifact_kw)
        session.add(artifact)
        session.flush()

        job.records_attempted = (job.records_attempted or 0) + 1
        job.records_succeeded = (job.records_succeeded or 0) + 1
        session.flush()

        return RegisterRawGameFileResult(
            artifact_id=int(artifact.id),
            import_job_id=request.import_job_id,
            checksum_sha256=digest,
            byte_length=len(content),
            ingest_status=artifact.ingest_status,
            observed_at=observed,
        )

    def register_raw_game_file_from_path(
        self,
        session: Session,
        *,
        path: Path,
        import_job_id: str,
        source_system: str,
        parser_version: str,
        league_key: str | None = None,
        media_type: str | None = None,
        extra_metadata: dict | None = None,
    ) -> RegisterRawGameFileResult:
        """
        Read ``path`` into memory, then :meth:`register_raw_game_file`.

        ``uri`` is set to ``path.resolve().as_uri()``; ``logical_name`` to ``path.name``.
        """
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise RawIngestError("raw_file_read_failed", f"{path}: {exc}") from exc
        req = RegisterRawGameFileRequest(
            import_job_id=import_job_id,
            source_system=source_system,
            parser_version=parser_version,
            content=content,
            league_key=league_key,
            logical_name=path.name,
            media_type=media_type,
            uri=path.resolve().as_uri(),
            extra_metadata=dict(extra_metadata or {}),
        )
        return self.register_raw_game_file(session, req)

    def mark_artifact_failed(
        self,
        session: Session,
        *,
        artifact_id: int,
        message: str,
    ) -> None:
        """Set ingest_status to ``failed`` and attach a short operator note in extra_metadata."""
        row = session.get(SourceArtifactRow, artifact_id)
        if row is None:
            raise RawIngestError("artifact_missing", f"No source_artifacts row id={artifact_id}")
        row.ingest_status = SourceArtifactIngestStatus.FAILED.value
        meta = dict(row.extra_metadata or {})
        meta["failure_message"] = message
        row.extra_metadata = meta
        job = session.get(ImportJobRow, row.import_job_id)
        if job is not None:
            job.records_failed = (job.records_failed or 0) + 1
        session.flush()

    def list_artifacts_for_job(self, session: Session, import_job_id: str) -> list[SourceArtifactRow]:
        return list(
            session.scalars(
                select(SourceArtifactRow).where(SourceArtifactRow.import_job_id == import_job_id)
            )
        )

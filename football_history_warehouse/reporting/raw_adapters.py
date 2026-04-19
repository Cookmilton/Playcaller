"""Map ORM rows to reporting dataclasses (no heavy joins)."""

from __future__ import annotations

from football_history_warehouse.reporting.import_report import RawIngestArtifactReport, RawIngestJobReport
from football_history_warehouse.storage.database.models import ImportJobRow, SourceArtifactRow


def raw_ingest_job_report(row: ImportJobRow) -> RawIngestJobReport:
    return RawIngestJobReport(
        job_id=row.job_id,
        status=row.status,
        source_label=row.source_label,
        started_at=row.started_at,
        completed_at=row.completed_at,
        records_attempted=row.records_attempted,
        records_succeeded=row.records_succeeded,
        records_failed=row.records_failed,
        error_summary=row.error_summary,
    )


def raw_ingest_artifact_report(row: SourceArtifactRow) -> RawIngestArtifactReport:
    return RawIngestArtifactReport(
        artifact_id=int(row.id),
        import_job_id=row.import_job_id,
        artifact_kind=row.artifact_kind,
        source_system=row.source_system,
        league_key=row.league_key,
        parser_version=row.parser_version,
        ingest_status=row.ingest_status,
        logical_name=row.logical_name,
        uri=row.uri,
        content_checksum=row.content_checksum,
        byte_length=row.byte_length,
        observed_at=row.observed_at,
    )

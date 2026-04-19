"""
Import run reporting types (skeleton).

Structured summaries for logs, dashboards, or operator email — without embedding
large raw payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ImportRunSummary:
    """Minimal placeholder for a completed import run header."""

    run_id: str
    source_label: str


@dataclass(frozen=True, slots=True)
class RawIngestJobReport:
    """Snapshot of an import job after raw registration work (canonical tables optional)."""

    job_id: str
    status: str
    source_label: str
    started_at: datetime
    completed_at: datetime | None
    records_attempted: int | None
    records_succeeded: int | None
    records_failed: int | None
    error_summary: str | None


@dataclass(frozen=True, slots=True)
class RawIngestArtifactReport:
    """One persisted raw artifact row (for operator dashboards / audit)."""

    artifact_id: int
    import_job_id: str
    artifact_kind: str
    source_system: str
    league_key: str | None
    parser_version: str | None
    ingest_status: str
    logical_name: str | None
    uri: str | None
    content_checksum: str | None
    byte_length: int | None
    observed_at: datetime

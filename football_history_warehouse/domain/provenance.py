"""
Import jobs and per-record source metadata for end-to-end traceability.

Every canonical entity carries ``provenance`` so audits can answer: which
batch, which upstream system, and which raw record produced this row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from football_history_warehouse.domain.enums import ImportJobStatus
from football_history_warehouse.domain.identifiers import ImportJobId


class SourceMetadata(BaseModel):
    """
    One upstream snapshot of a record (append-only friendly).

    **Required:** ``source_system`` identifies the logical feed (not necessarily
    a hostname). **Optional:** line-level ids and hashes when the feed provides them.

    ``source_system`` examples: ``"espn_api"``, ``"nfl_gsis"``, ``"internal_csv"``.
    Prefer lowercase snake identifiers; version the *meaning* in normalization,
    not in this string alone.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_system: str = Field(..., min_length=1, description="Logical upstream name.")
    source_record_id: str | None = Field(
        default=None,
        description="Vendor primary key or stable row id when available.",
    )
    source_subresource: str | None = Field(
        default=None,
        description="Secondary pointer (e.g. play id within game payload).",
    )
    ingest_uri: str | None = Field(
        default=None,
        description="URI or path hint for debugging only; may be redacted in prod.",
    )
    content_checksum: str | None = Field(
        default=None,
        description="Hash of normalized raw fragment used to build this entity.",
    )
    observed_at: datetime = Field(
        ...,
        description="When this source snapshot was seen during ingest.",
    )
    source_payload_version: str | None = Field(
        default=None,
        description="Optional feed schema or API version string.",
    )


class ProvenanceEntry(BaseModel):
    """Links a canonical row to one import job and its source metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    import_job_id: ImportJobId
    source: SourceMetadata
    warehouse_written_at: datetime = Field(
        ...,
        description="When the warehouse materialized this version of the entity.",
    )
    superseded_by_job_id: ImportJobId | None = Field(
        default=None,
        description="If republished, optional pointer to the correcting job.",
    )


class ImportJob(BaseModel):
    """
    A single batch or run of ingest + normalization.

    **Required:** identity, status, and timing. **Optional:** aggregates and
    operator notes. Detailed per-record failures belong in reporting tables or logs later, not embedded in full here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: ImportJobId
    status: ImportJobStatus
    started_at: datetime
    completed_at: datetime | None = None
    source_label: str = Field(..., min_length=1, description="Human/ops label for the run.")
    trigger: str | None = Field(
        default=None,
        description="scheduler, manual, backfill, etc.",
    )
    records_attempted: int | None = Field(default=None, ge=0)
    records_succeeded: int | None = Field(default=None, ge=0)
    records_failed: int | None = Field(default=None, ge=0)
    error_summary: str | None = Field(
        default=None,
        description="Short operator-facing summary when status is failed/partial.",
    )
    config_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-secret parameters for reproducibility (version pins, league scope).",
    )

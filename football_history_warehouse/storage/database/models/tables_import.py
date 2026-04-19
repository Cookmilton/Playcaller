"""Import jobs and raw source artifact pointers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from football_history_warehouse.storage.database.base import Base


def _json_type():
    """JSONB on PostgreSQL, generic JSON elsewhere (SQLite tests)."""
    return JSON().with_variant(JSONB(), "postgresql")


class ImportJobRow(Base):
    __tablename__ = "import_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_label: Mapped[str] = mapped_column(String(256), nullable=False)
    trigger: Mapped[str | None] = mapped_column(String(64))
    records_attempted: Mapped[int | None] = mapped_column(Integer)
    records_succeeded: Mapped[int | None] = mapped_column(Integer)
    records_failed: Mapped[int | None] = mapped_column(Integer)
    error_summary: Mapped[str | None] = mapped_column(Text())
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(_json_type(), nullable=False)
    pipeline_report: Mapped[dict[str, Any] | None] = mapped_column(_json_type(), nullable=True)
    """Serialized :class:`~football_history_warehouse.reporting.pipeline_report.ImportJobPipelineReport` (or stage failure envelope)."""


class SourceArtifactRow(Base):
    """
    Raw feed handles: pointers + checksums + ingest lifecycle.

    Bytes may live in object storage; this row is the durable registry for audit,
    reprocessing, and batch status. ``league_key`` is a feed-scoped label (not
    necessarily a canonical ``leagues.league_id`` until normalization runs.
    """

    __tablename__ = "source_artifacts"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    import_job_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("import_jobs.job_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    artifact_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_system: Mapped[str] = mapped_column(String(128), nullable=False)
    uri: Mapped[str | None] = mapped_column(Text())
    content_checksum: Mapped[str | None] = mapped_column(String(128))
    byte_length: Mapped[int | None] = mapped_column(BigInteger)
    media_type: Mapped[str | None] = mapped_column(String(128))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(_json_type(), nullable=False)
    league_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingest_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="registered",
        default="registered",
    )
    logical_name: Mapped[str | None] = mapped_column(String(512), nullable=True)

"""Per-entity provenance rows (many entries per canonical entity over time)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from football_history_warehouse.storage.database.base import Base


class ProvenanceRecordRow(Base):
    __tablename__ = "provenance_records"
    __table_args__ = (
        Index("ix_provenance_entity", "entity_type", "entity_id"),
        Index("ix_provenance_import_job", "import_job_id"),
        # SQLite only autoincrements INTEGER PRIMARY KEY; this enables AUTOINCREMENT.
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    import_job_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("import_jobs.job_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_system: Mapped[str] = mapped_column(String(128), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(String(256))
    source_subresource: Mapped[str | None] = mapped_column(String(256))
    ingest_uri: Mapped[str | None] = mapped_column(Text())
    content_checksum: Mapped[str | None] = mapped_column(String(128))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_payload_version: Mapped[str | None] = mapped_column(String(64))
    warehouse_written_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_by_job_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("import_jobs.job_id", ondelete="SET NULL"),
    )

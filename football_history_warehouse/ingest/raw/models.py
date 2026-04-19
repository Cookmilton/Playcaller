"""Dataclasses for raw ingest API boundaries (not canonical domain plays)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class RegisterRawGameFileRequest:
    """
    Register a raw game payload before normalization.

    ``source_system`` identifies the upstream provider or connector.
    ``league_key`` is feed-scoped (may differ from canonical ``league_id``).
    """

    import_job_id: str
    source_system: str
    parser_version: str
    content: bytes
    league_key: str | None = None
    logical_name: str | None = None
    media_type: str | None = None
    uri: str | None = None
    observed_at: datetime | None = None
    checksum_sha256: str | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RegisterRawGameFileResult:
    """Outcome of a successful raw registration (no canonical rows created)."""

    artifact_id: int
    import_job_id: str
    checksum_sha256: str
    byte_length: int
    ingest_status: str
    observed_at: datetime

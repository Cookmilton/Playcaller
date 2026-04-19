"""Strings stored in ``source_artifacts`` columns (stable for SQL + migrations)."""

from __future__ import annotations

from enum import Enum


class RawArtifactKind(str, Enum):
    """High-level classification for ``SourceArtifactRow.artifact_kind``."""

    RAW_GAME_FILE = "raw_game_file"
    RAW_FEED_PAYLOAD = "raw_feed_payload"
    MANIFEST = "manifest"
    OTHER = "other"


class SourceArtifactIngestStatus(str, Enum):
    """Lifecycle for a single artifact row (batch-friendly)."""

    REGISTERED = "registered"
    STORED = "stored"
    FAILED = "failed"
    SKIPPED = "skipped"

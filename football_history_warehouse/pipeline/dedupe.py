"""
Lightweight duplicate detection for raw payloads and canonical games.

Not a distributed dedupe system — enough to make manual re-imports and batch
replays safe without surprise double writes.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from football_history_warehouse.storage.database.models import GameRow, SourceArtifactRow


def raw_payload_already_registered(
    session: Session,
    *,
    content_checksum_sha256: str,
    source_system: str,
) -> SourceArtifactRow | None:
    """
    Return an existing ``source_artifacts`` row with the same checksum and source, if any.

    Same bytes re-uploaded under the same ``source_system`` are treated as duplicates
    before creating a new import job.
    """
    return session.scalar(
        select(SourceArtifactRow).where(
            SourceArtifactRow.content_checksum == content_checksum_sha256,
            SourceArtifactRow.source_system == source_system,
        )
    )


def canonical_game_exists(session: Session, game_id: str) -> bool:
    return session.get(GameRow, game_id) is not None

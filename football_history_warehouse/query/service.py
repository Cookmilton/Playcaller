"""
Warehouse query service (skeleton).

Future: explicit methods such as games_for_season, plays_for_game, etc.,
backed by repositories and indexes. Implementations belong here or in
co-located modules, not in UI code.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from football_history_warehouse.storage.database.models import ImportJobRow


def get_import_job_pipeline_report(session: Session, job_id: str) -> dict[str, Any] | None:
    """
    Return the stored pipeline report JSON for a finished (or failed) import job, if any.

    ``None`` means the job row is missing or no report was written (e.g. job still running,
    or pre-migration rows).
    """
    row = session.get(ImportJobRow, job_id)
    if row is None:
        return None
    return row.pipeline_report

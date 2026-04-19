"""
Structured import pipeline report: normalization skips, validation, persistence outcome.

Designed for logs, JSON APIs, and reprocessing jobs — small, stable payloads (no raw bytes).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from football_history_warehouse.normalization.bundle import CanonicalGameBundle
from football_history_warehouse.normalization.notices import NormalizationNotice
from football_history_warehouse.validation.issues import (
    CanonicalBundleValidationResult,
    ValidationIssue,
)


class PipelineOutcome(str, Enum):
    """High-level result for an import job after validate (and optionally persist)."""

    VALIDATION_FAILED = "validation_failed"
    """Fatal validation issues — do not persist."""

    PERSISTED_OK = "persisted_ok"
    """Persisted; no validation warnings (normalization skips may still exist)."""

    PERSISTED_WITH_WARNINGS = "persisted_with_warnings"
    """Persisted; validation warnings and/or normalization notices only."""

    PERSISTENCE_FAILED = "persistence_failed"
    """Validation passed but database write failed."""

    NOT_PERSISTED = "not_persisted"
    """Validated only (or not yet persisted)."""


@dataclass(frozen=True, slots=True)
class SkippedRecordReport:
    """
    A row or segment skipped during normalization (not a validation failure).

    Sourced from :class:`~football_history_warehouse.normalization.notices.NormalizationNotice`.
    """

    code: str
    detail: str
    where: str | None = None


@dataclass(frozen=True, slots=True)
class PersistenceAttemptReport:
    """Outcome of a persistence call (no ORM objects — serializable)."""

    attempted: bool
    succeeded: bool
    error_type: str | None = None
    error_message: str | None = None
    persisted_game_id: str | None = None
    drive_count: int | None = None
    play_count: int | None = None
    provenance_rows_written: int | None = None


@dataclass(frozen=True, slots=True)
class ImportJobPipelineReport:
    """
    Machine-readable summary for one canonical game import under one ``import_job_id``.

    Store or log this object as JSON for operator dashboards and batch replays.
    """

    schema_version: str
    import_job_id: str
    canonical_game_id: str
    league_id: str
    season_id: str
    created_at_utc: datetime
    outcome: PipelineOutcome
    normalization_skips: tuple[SkippedRecordReport, ...]
    validation: dict[str, Any]
    persistence: PersistenceAttemptReport | None
    summary: str

    def to_json_dict(self) -> dict[str, Any]:
        """JSON-serializable dict (datetimes as ISO 8601)."""

        def _dt(v: datetime | None) -> str | None:
            if v is None:
                return None
            return v.isoformat()

        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "import_job_id": self.import_job_id,
            "canonical_game_id": self.canonical_game_id,
            "league_id": self.league_id,
            "season_id": self.season_id,
            "created_at_utc": _dt(self.created_at_utc),
            "outcome": self.outcome.value,
            "normalization_skips": [
                {"code": s.code, "detail": s.detail, "where": s.where} for s in self.normalization_skips
            ],
            "validation": self.validation,
            "summary": self.summary,
        }
        if self.persistence is not None:
            p = self.persistence
            out["persistence"] = {
                "attempted": p.attempted,
                "succeeded": p.succeeded,
                "error_type": p.error_type,
                "error_message": p.error_message,
                "persisted_game_id": p.persisted_game_id,
                "drive_count": p.drive_count,
                "play_count": p.play_count,
                "provenance_rows_written": p.provenance_rows_written,
            }
        else:
            out["persistence"] = None
        return out


def validation_issue_to_dict(issue: ValidationIssue) -> dict[str, Any]:
    return {
        "code": issue.code,
        "severity": issue.severity.value,
        "message": issue.message,
        "entity_type": issue.entity_type,
        "entity_id": issue.entity_id,
        "field": issue.field,
    }


def validation_result_to_dict(result: CanonicalBundleValidationResult) -> dict[str, Any]:
    return {
        "ok_to_persist": result.ok_to_persist,
        "fatal_count": len(result.fatal_issues),
        "warning_count": len(result.warnings),
        "fatal_issues": [validation_issue_to_dict(i) for i in result.fatal_issues],
        "warnings": [validation_issue_to_dict(i) for i in result.warnings],
    }


def normalization_notices_to_skips(notices: tuple[NormalizationNotice, ...]) -> tuple[SkippedRecordReport, ...]:
    return tuple(SkippedRecordReport(code=n.code, detail=n.detail, where=n.where) for n in notices)


def build_import_pipeline_report(
    *,
    import_job_id: str,
    bundle: CanonicalGameBundle,
    validation: CanonicalBundleValidationResult,
    persistence: PersistenceAttemptReport | None = None,
    created_at_utc: datetime | None = None,
) -> ImportJobPipelineReport:
    """
    Assemble a pipeline report from normalization + validation (+ optional persistence).

    ``outcome`` is derived from validation fatals and persistence success — callers may
    override by constructing :class:`ImportJobPipelineReport` manually if needed.
    """
    g = bundle.game
    created = created_at_utc or datetime.now(timezone.utc)
    skips = normalization_notices_to_skips(bundle.notices)
    vdict = validation_result_to_dict(validation)

    if not validation.ok_to_persist:
        outcome = PipelineOutcome.VALIDATION_FAILED
        summary = (
            f"Validation failed: {vdict['fatal_count']} fatal issue(s), "
            f"{vdict['warning_count']} warning(s); game {str(g.game_id)!r} not eligible for persist."
        )
    elif persistence is None:
        outcome = PipelineOutcome.NOT_PERSISTED
        summary = (
            f"Validated ok ({vdict['warning_count']} warning(s)); persistence not run for game {str(g.game_id)!r}."
        )
    elif persistence.succeeded:
        if validation.has_warnings:
            outcome = PipelineOutcome.PERSISTED_WITH_WARNINGS
            summary = (
                f"Persisted game {str(g.game_id)!r} with {vdict['warning_count']} validation warning(s); "
                f"{len(skips)} normalization skip record(s)."
            )
        else:
            outcome = PipelineOutcome.PERSISTED_OK
            summary = (
                f"Persisted game {str(g.game_id)!r} cleanly; {len(skips)} normalization skip record(s)."
            )
    else:
        outcome = PipelineOutcome.PERSISTENCE_FAILED
        summary = (
            f"Validation passed but persistence failed for game {str(g.game_id)!r}: "
            f"{persistence.error_message!r}."
        )

    return ImportJobPipelineReport(
        schema_version="1",
        import_job_id=import_job_id,
        canonical_game_id=str(g.game_id),
        league_id=str(g.league_id),
        season_id=str(g.season_id),
        created_at_utc=created,
        outcome=outcome,
        normalization_skips=skips,
        validation=vdict,
        persistence=persistence,
        summary=summary,
    )

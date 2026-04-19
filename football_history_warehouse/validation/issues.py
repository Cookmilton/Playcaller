"""Structured validation issues for canonical bundles (machine-readable codes)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class ValidationSeverity(str, Enum):
    """Whether an issue blocks persistence or is advisory."""

    FATAL = "fatal"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """
    One detectable problem on a :class:`~football_history_warehouse.normalization.bundle.CanonicalGameBundle`.

    ``code`` is stable for dashboards, alerts, and reprocessing filters.
    """

    code: str
    severity: ValidationSeverity
    message: str
    entity_type: Literal["game", "drive", "play"] | None = None
    entity_id: str | None = None
    field: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalBundleValidationResult:
    """Output of :func:`~football_history_warehouse.validation.bundle.validate_canonical_game_bundle`."""

    issues: tuple[ValidationIssue, ...]

    @property
    def fatal_issues(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == ValidationSeverity.FATAL)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == ValidationSeverity.WARNING)

    @property
    def ok_to_persist(self) -> bool:
        return len(self.fatal_issues) == 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0


class ValidationFailedError(ValueError):
    """Raised when persistence is attempted with a failing validation result (optional guard)."""

    def __init__(self, result: CanonicalBundleValidationResult) -> None:
        codes = ", ".join(i.code for i in result.fatal_issues)
        super().__init__(f"Canonical bundle validation failed: {codes}")
        self.result = result

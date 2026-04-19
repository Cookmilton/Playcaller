"""
Pre-persistence validation for canonical bundles (cross-row checks and feed heuristics).

Use :func:`validate_canonical_game_bundle` after normalization and before
:class:`~football_history_warehouse.storage.repositories.persist_canonical_game_bundle`,
optionally passing the result via ``PersistCanonicalBundleParams.validation_result`` to block bad writes.
"""

from football_history_warehouse.validation.bundle import validate_canonical_game_bundle
from football_history_warehouse.validation.issues import (
    CanonicalBundleValidationResult,
    ValidationFailedError,
    ValidationIssue,
    ValidationSeverity,
)

__all__ = [
    "CanonicalBundleValidationResult",
    "ValidationFailedError",
    "ValidationIssue",
    "ValidationSeverity",
    "validate_canonical_game_bundle",
]

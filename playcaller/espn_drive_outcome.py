"""
Map ESPN completed-drive ``result`` / ``displayResult`` onto Playcaller ``DRIVE_END_*`` kinds.

Used at import time so ``Drive.result`` matches the feed. Unmapped ESPN strings are logged
and return ``None`` so the caller can fall back to play inference.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from playcaller.game import (
    DRIVE_END_END_OF_GAME,
    DRIVE_END_END_OF_HALF,
    DRIVE_END_FIELD_GOAL,
    DRIVE_END_FIELD_GOAL_MISS,
    DRIVE_END_PUNT,
    DRIVE_END_TOUCHDOWN,
    DRIVE_END_TURNOVER_FUMBLE,
    DRIVE_END_TURNOVER_INT,
    DRIVE_END_TURNOVER_ON_DOWNS,
    DRIVE_END_UNKNOWN,
    DriveFeedAuditSnapshot,
)

logger = logging.getLogger(__name__)

# Coarse ESPN buckets → stored kind. SAFETY stays unknown until we model it.
_ESPN_BUCKET_TO_KIND = {
    "TD": DRIVE_END_TOUCHDOWN,
    "FG": DRIVE_END_FIELD_GOAL,
    "FG_MISS": DRIVE_END_FIELD_GOAL_MISS,
    "PUNT": DRIVE_END_PUNT,
    "INT": DRIVE_END_TURNOVER_INT,
    "FUMBLE": DRIVE_END_TURNOVER_FUMBLE,
    "DOWNS": DRIVE_END_TURNOVER_ON_DOWNS,
    "END_HALF": DRIVE_END_END_OF_HALF,
    "END_GAME": DRIVE_END_END_OF_GAME,
    "SAFETY": DRIVE_END_UNKNOWN,
}


def _norm_espn_text(*parts: str) -> str:
    return " ".join(p for p in parts if (p or "").strip()).upper().strip()


def espn_drive_outcome_bucket(audit: Optional[DriveFeedAuditSnapshot]) -> str:
    """Coarse ESPN result label from ``feed_audit`` (empty when ESPN gave nothing)."""
    if not audit:
        return ""
    s = _norm_espn_text(audit.espn_display_result, audit.espn_result_code)
    if not s:
        return ""
    if "TOUCHDOWN" in s or s in ("TD", "TDS"):
        return "TD"
    if "FIELD GOAL" in s:
        if "MISS" in s or "NO GOOD" in s or "BLOCK" in s:
            return "FG_MISS"
        return "FG"
    if "PUNT" in s:
        return "PUNT"
    if "INTERCEPT" in s or " INT" in s or s == "INT":
        return "INT"
    if "FUMBLE" in s:
        return "FUMBLE"
    if "DOWNS" in s or "TURNOVER ON DOWNS" in s:
        return "DOWNS"
    if "SAFETY" in s:
        return "SAFETY"
    if "END OF HALF" in s or "END HALF" in s:
        return "END_HALF"
    if "END OF GAME" in s or "END GAME" in s:
        return "END_GAME"
    return s[:32]


def drive_result_kind_from_espn_audit(
    audit: Optional[DriveFeedAuditSnapshot],
) -> Tuple[Optional[str], str]:
    """
    Map ESPN drive metadata to a ``DRIVE_END_*`` kind.

    Returns ``(kind, bucket)`` when ESPN provided a recognized signal.
    Returns ``(None, "")`` when ESPN left result empty — caller should infer from plays.
    Returns ``(None, raw_bucket)`` when ESPN text was present but unmapped (also logs a warning).
    """
    bucket = espn_drive_outcome_bucket(audit)
    if not bucket:
        return None, ""
    kind = _ESPN_BUCKET_TO_KIND.get(bucket)
    if kind is not None:
        return kind, bucket
    logger.warning(
        "playcaller: unmapped ESPN drive outcome %r (display=%r code=%r) — falling back to play inference",
        bucket,
        getattr(audit, "espn_display_result", None) if audit else None,
        getattr(audit, "espn_result_code", None) if audit else None,
    )
    return None, bucket

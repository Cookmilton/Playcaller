"""
Feed import scope: which ESPN-side drives/plays enter the session (our / opponent / both).

Display and merge use the same mode strings as :mod:`playcaller.live_data.drive_display`.
Unknown team attribution is conservative: excluded from single-team modes, allowed only for **both**.
"""

from __future__ import annotations

from typing import Optional

from playcaller.live_data.drive_display import (
    PREVIOUS_DRIVES_FILTER_BOTH,
    PREVIOUS_DRIVES_FILTER_OPPONENT,
    PREVIOUS_DRIVES_FILTER_OUR,
)
from playcaller.live_data.types import FeedCompletedDrive


def normalize_feed_team_scope(raw: Optional[str]) -> str:
    m = str(raw or "").strip().lower()
    if m in (PREVIOUS_DRIVES_FILTER_OUR, PREVIOUS_DRIVES_FILTER_OPPONENT, PREVIOUS_DRIVES_FILTER_BOTH):
        return m
    return PREVIOUS_DRIVES_FILTER_OUR


def classify_feed_team_id_vs_coached(team_espn_id: str, coached_team_id: str) -> str:
    t = str(team_espn_id or "").strip()
    c = str(coached_team_id or "").strip()
    if not t or not c:
        return "unknown"
    return "our" if t == c else "opp"


def feed_completed_drive_matches_scope(
    fd: FeedCompletedDrive,
    *,
    scope: str,
    coached_team_id: str,
) -> bool:
    """Whether a ``drives.previous`` row should be merged into ``Game.drives`` for this scope."""
    sc = normalize_feed_team_scope(scope)
    if sc == PREVIOUS_DRIVES_FILTER_BOTH:
        return True
    side = classify_feed_team_id_vs_coached(fd.team_espn_id, coached_team_id)
    if side == "unknown":
        return False
    if sc == PREVIOUS_DRIVES_FILTER_OUR:
        return side == "our"
    if sc == PREVIOUS_DRIVES_FILTER_OPPONENT:
        return side == "opp"
    return True


def current_feed_plays_merge_allowed(
    *,
    scope: str,
    coached_team_id: str,
    current_drive_team_espn_id: Optional[str],
    possession_team_id: Optional[str],
) -> tuple[bool, str]:
    """
    Whether ``drives.current.plays`` should merge into the live DriveLogger.

    The live log is **always coached-team only**, regardless of ``scope``. Scope
    ``both`` widens completed-drive storage / Previous-drives UI only — never the
    in-progress logger. Uses ``drives.current.team.id`` when present, else
    ``situation`` possession team id.
    """
    _ = normalize_feed_team_scope(scope)  # accepted for call-site / audit compatibility
    cid = str(coached_team_id or "").strip()
    if not cid:
        return False, "current-drive merge skipped (coached_team_id required for live DriveLogger)"

    tid = str(current_drive_team_espn_id or "").strip() or str(possession_team_id or "").strip()
    side = classify_feed_team_id_vs_coached(tid, cid)
    if side == "unknown":
        return False, (
            "current-drive merge skipped (cannot resolve possessing team id for live DriveLogger; "
            "wait for possession metadata)"
        )
    if side != "our":
        return False, (
            "current-drive merge skipped (live DriveLogger is coached-team only; "
            "current feed drive belongs to opponent)"
        )
    return True, ""

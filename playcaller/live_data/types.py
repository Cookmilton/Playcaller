from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

ClockResolutionSource = Literal["display_clock", "numeric_status", "play_text"]
# Which ESPN block supplied the live situation (see ``playcaller.live_data.espn_situation``).
SituationSource = Literal["scoreboard", "last_play_end"]

from playcaller.domain import ActualPlayResult
from playcaller.game import DriveFeedAuditSnapshot


@dataclass(frozen=True)
class FeedPlayEvent:
    """One play row from a vendor feed (for optional auto-logging)."""

    event_id: str
    summary_text: str
    yards_gained: Optional[int]
    type_hint: str  # rush | pass | penalty | kick | unknown


@dataclass(frozen=True)
class FeedCompletedDrive:
    """One finished drive from a feed payload (e.g. ESPN ``drives.previous``), ready to merge into ``Game``."""

    stable_key: str
    team_espn_id: str
    plays: Tuple[ActualPlayResult, ...]
    team_abbreviation: str = ""
    team_display_name: str = ""
    feed_audit: Optional[DriveFeedAuditSnapshot] = None


@dataclass
class NormalizedGameSnapshot:
    """Vendor-neutral game state aligned to this app's ``Game`` / sidebar widgets."""

    provider: str
    external_game_id: str
    sport: Literal["nfl", "college-football", "ufl"]
    fetched_at_epoch: float
    status_detail: str
    quarter: Optional[int]
    clock_seconds_in_period: Optional[int]
    # Situation fields are **raw** feed values (never clamped) so ``apply_snapshot`` can
    # report an out-of-range field instead of silently coercing it.
    down: Optional[int]
    distance: Optional[int]
    abs_yards_from_own_goal: Optional[int]
    possession_team_id: Optional[str]
    possession_is_our_team: Optional[bool]
    our_score: Optional[int]
    opponent_score: Optional[int]
    our_timeouts: Optional[int]
    opponent_timeouts: Optional[int]
    is_final: bool
    new_plays: Tuple[FeedPlayEvent, ...] = ()
    debug_notes: Tuple[str, ...] = ()
    # Which ESPN branch supplied ``clock_seconds_in_period`` (``None`` if clock unresolved).
    clock_resolution: Optional[ClockResolutionSource] = None
    coached_team_id: Optional[str] = None
    completed_feed_drives: Tuple[FeedCompletedDrive, ...] = ()
    # Raw ``drives.current.plays`` JSON rows (full list) for in-progress merge into ``DriveLogger``.
    current_feed_drive_plays: Tuple[Dict[str, Any], ...] = ()
    # ``drives.current.id`` when ESPN provides it (seen-play-id reset is keyed on this, not board possession).
    current_feed_drive_id: Optional[str] = None
    # ``drives.current.team.id`` when ESPN provides it (feed scope + merge diagnostics).
    current_feed_drive_team_espn_id: Optional[str] = None
    # Which block supplied down / distance / field position / possession / timeouts.
    # ``None`` means neither source had a situation this sync (see ``espn_situation``).
    situation_source: Optional[SituationSource] = None
    # Raw yards-to-opponent-goal behind ``abs_yards_from_own_goal`` (kept for range reporting).
    yards_to_endzone: Optional[int] = None


@dataclass
class FetchResult:
    ok: bool
    snapshot: Optional[NormalizedGameSnapshot] = None
    error: Optional[str] = None
    raw_excerpt: Optional[str] = None
    used_insecure_ssl_fallback: bool = False
    # Top-level ESPN summary JSON (same dict as fetch_json returns).
    raw_summary: Optional[Dict[str, Any]] = None


@dataclass
class SyncResult:
    """What the UI should show after ``apply_snapshot``."""

    ok: bool
    applied_fields: List[str] = field(default_factory=list)
    # Section-level skips are strings; per-field situation skips are
    # ``{"field": ..., "reason": ...}`` dicts (see ``sync.SITUATION_FIELDS``).
    skipped_reasons: List[Any] = field(default_factory=list)
    plays_appended: int = 0
    drives_imported: int = 0
    completed_drive_plays_imported: int = 0
    current_drive_plays_merged: int = 0
    drive_log_rows_before: int = 0
    drive_log_rows_after: int = 0
    situation_source: Optional[SituationSource] = None
    message: str = ""
    error: Optional[str] = None

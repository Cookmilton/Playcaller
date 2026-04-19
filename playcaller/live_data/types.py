from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

from playcaller.domain import ActualPlayResult


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
    coached_team_id: Optional[str] = None
    completed_feed_drives: Tuple[FeedCompletedDrive, ...] = ()
    # Raw ``drives.current.plays`` JSON rows (full list) for in-progress merge into ``DriveLogger``.
    current_feed_drive_plays: Tuple[Dict[str, Any], ...] = ()
    # ``drives.current.team.id`` when ESPN provides it (feed scope + merge diagnostics).
    current_feed_drive_team_espn_id: Optional[str] = None


@dataclass
class FetchResult:
    ok: bool
    snapshot: Optional[NormalizedGameSnapshot] = None
    error: Optional[str] = None
    raw_excerpt: Optional[str] = None
    used_insecure_ssl_fallback: bool = False


@dataclass
class SyncResult:
    """What the UI should show after ``apply_snapshot``."""

    ok: bool
    applied_fields: List[str] = field(default_factory=list)
    skipped_reasons: List[str] = field(default_factory=list)
    plays_appended: int = 0
    drives_imported: int = 0
    current_drive_plays_merged: int = 0
    message: str = ""
    error: Optional[str] = None

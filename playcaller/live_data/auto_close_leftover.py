"""G2.2: auto-archive a leftover DriveLogger when the ESPN current drive id moves on."""

from __future__ import annotations

from typing import Any, MutableMapping, Optional, Sequence, Set

from playcaller.espn_drive_outcome import drive_result_kind_from_espn_audit
from playcaller.game import Game
from playcaller.live_data.drive_boundaries import matching_completed_drive_for_open_log
from playcaller.live_data.espn_current_drive_merge import top_up_open_drive_log_from_completed_drives
from playcaller.live_data.types import FeedCompletedDrive
from playcaller.possession import end_drive_blocked_reason
from playcaller.services.drive_archive import ARCHIVE_KIND_AUTO, archive_open_drive
from playcaller.state import DriveLogger
from playcaller.streamlit_state.keys import (
    LIVE_FEED_AUTO_CLOSE_SUPPRESS_KEYS,
    LIVE_FEED_SEEN_PLAY_IDS,
)


def completed_drive_has_espn_result(fd: Optional[FeedCompletedDrive]) -> bool:
    if fd is None:
        return False
    kind, _bucket = drive_result_kind_from_espn_audit(fd.feed_audit)
    return kind is not None


def _suppress_keys(ss: MutableMapping[str, Any]) -> Set[str]:
    raw = ss.get(LIVE_FEED_AUTO_CLOSE_SUPPRESS_KEYS)
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return set()
    return {str(x) for x in raw if str(x).strip()}


def try_auto_close_leftover_drive(
    *,
    game: Game,
    session: MutableMapping[str, Any],
    drive_log: DriveLogger,
    completed: Sequence[FeedCompletedDrive],
) -> bool:
    """
    Archive the leftover logger through the shared End-drive function when safe.

    Returns True when a drive was archived. Never writes widget-bound ``ui_*`` keys.
    """
    if not drive_log.results:
        return False
    if end_drive_blocked_reason(game.possession):
        return False
    fd = matching_completed_drive_for_open_log(drive_log, completed)
    if not completed_drive_has_espn_result(fd):
        return False
    assert fd is not None
    if fd.stable_key in _suppress_keys(session):
        return False

    seen: Set[str] = set(str(x) for x in (session.get(LIVE_FEED_SEEN_PLAY_IDS) or []))
    top_up_open_drive_log_from_completed_drives(
        drive_log=drive_log,
        completed=completed,
        seen_play_ids=seen,
        snap_review_audit=game.recommendation_audit,
    )
    session[LIVE_FEED_SEEN_PLAY_IDS] = sorted(seen)

    res = archive_open_drive(
        session,
        kind=ARCHIVE_KIND_AUTO,
        feed_audit=fd.feed_audit,
        espn_drive_key=fd.stable_key,
        feed_team_espn_id=fd.team_espn_id,
        feed_team_abbr=fd.team_abbreviation,
        feed_team_display_name=fd.team_display_name,
        update_board=False,
    )
    return res.archived is not None and res.refused is None

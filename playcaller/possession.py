"""
Pure possession rules: ``offense`` | ``defense`` | ``None`` and the gating that follows.

Leaf module — imports nothing from ``playcaller`` — so ``playcaller/game.py`` can import it at
module level. ``playcaller/streamlit_state/possession.py`` re-exports these and adds the
session-aware helpers.
"""

from __future__ import annotations

from typing import Any, Optional

POSSESSION_OFFENSE = "offense"
POSSESSION_DEFENSE = "defense"

UI_POSSESSION_UNSET = "Not set"
UI_POSSESSION_OUR = "Our team"
UI_POSSESSION_OPPONENT = "Opponent"
POSSESSION_RADIO_OPTIONS: tuple[str, str, str] = (
    UI_POSSESSION_UNSET,
    UI_POSSESSION_OUR,
    UI_POSSESSION_OPPONENT,
)

GENERATE_OPPONENT_REASON = "Opponent has the ball — Generate is for our snaps."
GENERATE_UNSET_POSSESSION_REASON = "Set possession or sync from ESPN"
LOG_RESULT_UNSET_POSSESSION_REASON = GENERATE_UNSET_POSSESSION_REASON
END_DRIVE_UNSET_POSSESSION_REASON = GENERATE_UNSET_POSSESSION_REASON


def possession_from_ui_label(label: Any) -> Optional[str]:
    """Map the possession chip label to ``Game.possession`` (``None`` if unset)."""
    if label == UI_POSSESSION_OUR:
        return POSSESSION_OFFENSE
    if label == UI_POSSESSION_OPPONENT:
        return POSSESSION_DEFENSE
    return None


def possession_side_radio_label(*, possession: Optional[str]) -> str:
    """Sidebar chip label for who has the ball. ``Not set`` when possession is unset."""
    if possession == POSSESSION_OFFENSE:
        return UI_POSSESSION_OUR
    if possession == POSSESSION_DEFENSE:
        return UI_POSSESSION_OPPONENT
    return UI_POSSESSION_UNSET


def possession_is_opponent(possession: Optional[str]) -> bool:
    """True only when the opponent has the ball — not when possession is unset."""
    return possession == POSSESSION_DEFENSE


def possession_is_unset(possession: Optional[str]) -> bool:
    return possession not in (POSSESSION_OFFENSE, POSSESSION_DEFENSE)


def generate_blocked_reason_for_possession(possession: Optional[str]) -> Optional[str]:
    """Why Generate must not run, or ``None`` when our offense has the ball."""
    if possession_is_unset(possession):
        return GENERATE_UNSET_POSSESSION_REASON
    if possession_is_opponent(possession):
        return GENERATE_OPPONENT_REASON
    return None


def generate_skip_debug_reason(possession: Optional[str]) -> Optional[str]:
    """Stable ``generate_skipped`` reason token for snap-review debug."""
    if possession_is_unset(possession):
        return "possession_unset"
    if possession_is_opponent(possession):
        return "opponent_possession"
    return None


def log_result_blocked_reason(possession: Optional[str]) -> Optional[str]:
    """Why **Log result** must not run. Unknown possession would misattribute the play."""
    if possession_is_unset(possession):
        return LOG_RESULT_UNSET_POSSESSION_REASON
    return None


def end_drive_blocked_reason(possession: Optional[str]) -> Optional[str]:
    """
    Why **End drive** must not run.

    Archiving with unknown possession is the only remaining UI path into the
    ``Drive.possessing_team`` ``None`` → ``offense`` coercion, which would file the drive
    under our offense on a board where nobody set a side. Opponent possession is allowed:
    ending their drive is a normal sideline action.
    """
    if possession_is_unset(possession):
        return END_DRIVE_UNSET_POSSESSION_REASON
    return None


def flipped_possession(possession: Optional[str]) -> Optional[str]:
    """
    Other side of the ball after a change of possession.

    Unknown stays unknown: flipping ``None`` to ``defense`` would assert the opponent has
    the ball on a board where nobody ever set a side. Sole flip helper — callers (including
    :func:`playcaller.game.flip_possession_after_drive`) must not reimplement it.
    """
    if possession == POSSESSION_OFFENSE:
        return POSSESSION_DEFENSE
    if possession == POSSESSION_DEFENSE:
        return POSSESSION_OFFENSE
    return None


END_DRIVE_MIXED_FEED_TEAMS_REASON = (
    "End drive refused: logger plays carry mixed feed team ids — archive after cleaning the log."
)


def possessing_team_from_feed_plays(
    plays: Any,
    *,
    coached_team_id: str,
    fallback_possession: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """
    Map play-level ``feed_possession_team_id`` through ``coached_team_id`` → offense/defense.

    Returns ``(possessing_team, refuse_reason)``. When no play carries a feed team id,
    falls back to ``fallback_possession`` (typically ``game.possession``). Mixed feed
    team ids refuse archival (contaminated logger).

    Kickoff rows are ignored: ESPN ``start.team`` is the kicking team, which would
    otherwise look like opponent contamination on a coached drive that opens with a return.
    """
    ids: set[str] = set()
    for play in plays or ():
        if str(getattr(play, "result_type", "") or "").strip().lower() == "kickoff":
            continue
        tid = str(getattr(play, "feed_possession_team_id", None) or "").strip()
        if tid:
            ids.add(tid)
    if not ids:
        return fallback_possession, None
    if len(ids) > 1:
        return None, END_DRIVE_MIXED_FEED_TEAMS_REASON
    tid = next(iter(ids))
    cid = str(coached_team_id or "").strip()
    if not cid:
        return fallback_possession, None
    return (POSSESSION_OFFENSE if tid == cid else POSSESSION_DEFENSE), None

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

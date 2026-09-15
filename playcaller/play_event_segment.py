"""
Coarse event classification for logged plays (review, replay chain, analytics).

Single source of truth for “is this an offensive scrimmage snap?” vs special teams.
Not used for recommendation scoring.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from playcaller.domain import ActualPlayResult


class PlayEventSegment(str, Enum):
    """How a logged play should be treated in review and tendency analytics."""

    OFFENSE = "offense"
    KICKOFF = "kickoff"
    PUNT = "punt"
    FIELD_GOAL = "field_goal"
    PAT = "pat"
    OTHER_SPECIAL = "other_special"
    ADMIN = "admin"


def segment_from_actual(act: Optional[ActualPlayResult]) -> PlayEventSegment:
    if act is None:
        return PlayEventSegment.OFFENSE
    rt = (act.result_type or "").strip().lower()
    pt = (act.play_type or "").strip().lower()
    fam = (act.family or "").strip().lower()
    desc = (act.description or "").lower()
    concept = (act.concept_name or "").lower()

    if rt == "kickoff":
        return PlayEventSegment.KICKOFF
    if rt == "punt":
        return PlayEventSegment.PUNT
    if rt in ("field_goal", "field_goal_miss"):
        return PlayEventSegment.FIELD_GOAL
    if rt in ("extra_point", "extra_point_miss"):
        return PlayEventSegment.PAT
    # Clock / timeout / period markers (even if they slipped past ingest skip).
    if (
        "official timeout" in desc
        or "official timeout" in concept
        or "timeout #" in desc
        or concept in ("official timeout", "end of half", "end of quarter", "end of game")
        or "end of half" in desc
        or "end of quarter" in desc
        or "end of game" in desc
        or "two-minute warning" in desc
    ):
        return PlayEventSegment.ADMIN
    if pt == "admin" or rt in ("no_play",):
        return PlayEventSegment.ADMIN
    if fam == "two_point" or rt == "two_point":
        return PlayEventSegment.OTHER_SPECIAL
    if pt == "special" and rt not in ("punt", "field_goal", "field_goal_miss", "kickoff", "extra_point"):
        return PlayEventSegment.OTHER_SPECIAL
    return PlayEventSegment.OFFENSE


def is_offensive_scrm_play(act: Optional[ActualPlayResult]) -> bool:
    return segment_from_actual(act) == PlayEventSegment.OFFENSE


def counts_as_offensive_snap(act: Optional[ActualPlayResult]) -> bool:
    """
    Whether the row counts toward drive ``play_count`` / snap-oriented stats.

    Administrative clock rows are excluded; kickoffs and kicks still count as rows
    on the drive chart (they are not offensive tendency snaps — use
    :func:`is_offensive_scrm_play` for that).
    """
    if act is None:
        return False
    return segment_from_actual(act) != PlayEventSegment.ADMIN


def counts_toward_offensive_yards(act: Optional[ActualPlayResult]) -> bool:
    """
    Whether ``yards_gained`` on this row enters drive ``computed_yards``.

    Matches ESPN completed-drive ``yards``: sum of possessing-offense play nets,
    excluding kickoff/punt/FG/PAT rows and interception-return yardage. Penalty rows
    that changed field position still count (net already in ``yards_gained``).

    Fumble rows keep the offensive net (loss/gain before COP). Interception return
    yards belong to the defense — excluded. Return plays stay on the drive for
    outcome/boundary truth; only yard attribution differs.
    """
    if act is None:
        return False
    rt = (act.result_type or "").strip().lower()
    # INT return yards are the defense's; never the possessing offense's.
    if rt == "interception":
        return False
    seg = segment_from_actual(act)
    if seg in (
        PlayEventSegment.KICKOFF,
        PlayEventSegment.PUNT,
        PlayEventSegment.FIELD_GOAL,
        PlayEventSegment.PAT,
        PlayEventSegment.ADMIN,
    ):
        # Pure admin (timeouts) out; penalty/no_play still ADMIN — those count via penalty flag.
        if bool(getattr(act, "penalty", False)):
            return True
        return False
    return True


def play_net_yards_for_drive(act: Optional[ActualPlayResult]) -> int:
    """Single net for drive sums: ``yards_gained`` only (never + ``penalty_yards``)."""
    if act is None or not counts_toward_offensive_yards(act):
        return 0
    return int(act.yards_gained)

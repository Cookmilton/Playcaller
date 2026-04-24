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

    if rt == "kickoff":
        return PlayEventSegment.KICKOFF
    if rt == "punt":
        return PlayEventSegment.PUNT
    if rt in ("field_goal", "field_goal_miss"):
        return PlayEventSegment.FIELD_GOAL
    if rt in ("extra_point", "extra_point_miss"):
        return PlayEventSegment.PAT
    if pt == "admin" or rt in ("no_play",):
        return PlayEventSegment.ADMIN
    if fam == "two_point" or rt == "two_point":
        return PlayEventSegment.OTHER_SPECIAL
    if pt == "special" and rt not in ("punt", "field_goal", "field_goal_miss", "kickoff", "extra_point"):
        return PlayEventSegment.OTHER_SPECIAL
    return PlayEventSegment.OFFENSE


def is_offensive_scrm_play(act: Optional[ActualPlayResult]) -> bool:
    return segment_from_actual(act) == PlayEventSegment.OFFENSE

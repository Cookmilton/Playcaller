from __future__ import annotations

import logging
import re
from enum import StrEnum
from typing import Final

logger = logging.getLogger(__name__)


class PlayType(StrEnum):
    RUN = "RUN"
    PASS = "PASS"
    SACK = "SACK"
    SCRAMBLE = "SCRAMBLE"
    PUNT = "PUNT"
    KICKOFF = "KICKOFF"
    FIELD_GOAL = "FIELD_GOAL"
    EXTRA_POINT = "EXTRA_POINT"
    TWO_POINT = "TWO_POINT"
    PENALTY_NO_PLAY = "PENALTY_NO_PLAY"
    SPIKE = "SPIKE"
    KNEEL = "KNEEL"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


class PlayResult(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    INTERCEPTION = "INTERCEPTION"
    FUMBLE_LOST = "FUMBLE_LOST"
    FUMBLE_RECOVERED_OWN = "FUMBLE_RECOVERED_OWN"
    RUSH_GAIN = "RUSH_GAIN"
    RUSH_LOSS = "RUSH_LOSS"
    RUSH_NO_GAIN = "RUSH_NO_GAIN"
    SACK_TAKEN = "SACK_TAKEN"
    SCRAMBLE_GAIN = "SCRAMBLE_GAIN"
    PUNT_NORMAL = "PUNT_NORMAL"
    PUNT_BLOCKED = "PUNT_BLOCKED"
    PUNT_TOUCHBACK = "PUNT_TOUCHBACK"
    PUNT_FAIR_CATCH = "PUNT_FAIR_CATCH"
    PUNT_DOWNED = "PUNT_DOWNED"
    KICKOFF_NORMAL = "KICKOFF_NORMAL"
    KICKOFF_TOUCHBACK = "KICKOFF_TOUCHBACK"
    KICKOFF_ONSIDE = "KICKOFF_ONSIDE"
    KICKOFF_RETURN_TD = "KICKOFF_RETURN_TD"
    FIELD_GOAL_MADE = "FIELD_GOAL_MADE"
    FIELD_GOAL_MISSED = "FIELD_GOAL_MISSED"
    FIELD_GOAL_BLOCKED = "FIELD_GOAL_BLOCKED"
    EXTRA_POINT_MADE = "EXTRA_POINT_MADE"
    EXTRA_POINT_MISSED = "EXTRA_POINT_MISSED"
    EXTRA_POINT_BLOCKED = "EXTRA_POINT_BLOCKED"
    TWO_POINT_GOOD = "TWO_POINT_GOOD"
    TWO_POINT_FAILED = "TWO_POINT_FAILED"
    PENALTY_OFFENSE = "PENALTY_OFFENSE"
    PENALTY_DEFENSE = "PENALTY_DEFENSE"
    PENALTY_OFFSETTING = "PENALTY_OFFSETTING"
    TOUCHDOWN_RUN = "TOUCHDOWN_RUN"
    TOUCHDOWN_PASS = "TOUCHDOWN_PASS"
    TOUCHDOWN_RETURN = "TOUCHDOWN_RETURN"
    SAFETY = "SAFETY"
    SPIKE = "SPIKE"
    KNEEL = "KNEEL"
    NO_PLAY = "NO_PLAY"
    UNKNOWN = "UNKNOWN"


def _compile_patterns() -> list[tuple[re.Pattern[str], PlayResult]]:
    return [
        # Administrative / clock
        (re.compile(r"^\s*timeout\b|\btimeout\b\s*(?:#|no\.|\d)", re.I), PlayResult.NO_PLAY),
        (re.compile(r"penalty.*no\s+play", re.I), PlayResult.NO_PLAY),
        (re.compile(r"\bspiked\s+the\s+ball\b|\bspike\b", re.I), PlayResult.SPIKE),
        (re.compile(r"\bkneels?\b", re.I), PlayResult.KNEEL),
        # Punts (specific before generic yardage)
        (
            re.compile(r"\bpunts?\b.*\bblocked\b|\bblocked\b.*\bpunts?\b", re.I),
            PlayResult.PUNT_BLOCKED,
        ),
        (re.compile(r"\bpunts?\b.*\btouchback\b", re.I), PlayResult.PUNT_TOUCHBACK),
        (re.compile(r"\bpunts?\s+\d+\s+yards?", re.I), PlayResult.PUNT_NORMAL),
        (re.compile(r"\bfair\s+catch\b", re.I), PlayResult.PUNT_FAIR_CATCH),
        (re.compile(r"\bdowned\b", re.I), PlayResult.PUNT_DOWNED),
        # Field goals
        (re.compile(r"field\s+goal.*\bblocked\b|\bblocked\b.*field\s+goal", re.I), PlayResult.FIELD_GOAL_BLOCKED),
        (
            re.compile(
                r"field\s+goal\s+is\s+no\s+good|field\s+goal\s+missed|"
                r"field\s+goal\s+no\s+good|no\s+good.*field\s+goal",
                re.I,
            ),
            PlayResult.FIELD_GOAL_MISSED,
        ),
        (re.compile(r"field\s+goal\s+is\s+good|field\s+goal\s+good\b", re.I), PlayResult.FIELD_GOAL_MADE),
        # Extra point / two-point
        (
            re.compile(
                r"extra\s+point.*\bblocked\b|\bblocked\b.*extra\s+point",
                re.I,
            ),
            PlayResult.EXTRA_POINT_BLOCKED,
        ),
        (
            re.compile(
                r"extra\s+point.*no\s+good|extra\s+point.*missed|"
                r"extra\s+point.*failed",
                re.I,
            ),
            PlayResult.EXTRA_POINT_MISSED,
        ),
        (
            re.compile(
                r"two[-\s]point.*(?:no\s+good|failed|not\s+good)",
                re.I,
            ),
            PlayResult.TWO_POINT_FAILED,
        ),
        (
            re.compile(
                r"extra\s+point.*(?:is\s+)?good|extra\s+point\s+good\b",
                re.I,
            ),
            PlayResult.EXTRA_POINT_MADE,
        ),
        (
            re.compile(
                r"two[-\s]point.*(?:is\s+)?good|two[-\s]point\s+conversion\s+good",
                re.I,
            ),
            PlayResult.TWO_POINT_GOOD,
        ),
        # Kickoffs
        (re.compile(r"\bkickoff\b.*\bonside\b|\bonside\b.*\bkick\b", re.I), PlayResult.KICKOFF_ONSIDE),
        (
            re.compile(
                r"\bkickoff\b.*\btouchback\b|\btouchback\b.*\bkickoff\b|\bkicks?\b.*\btouchback\b",
                re.I,
            ),
            PlayResult.KICKOFF_TOUCHBACK,
        ),
        (
            re.compile(
                r"kick(?:off)?\s+return.*touchdown|returned\s+.*\btouchdown\b|"
                r"kickoff.*\btouchdown\b.*\breturn\b",
                re.I,
            ),
            PlayResult.KICKOFF_RETURN_TD,
        ),
        (re.compile(r"\bkickoff\b", re.I), PlayResult.KICKOFF_NORMAL),
        # Passes (order: incomplete / pick before complete)
        (re.compile(r"\bpass\s+incomplete\b", re.I), PlayResult.INCOMPLETE),
        (re.compile(r"\bpass\b.*\bintercepted\b|\bintercepted\b.*\bpass\b", re.I), PlayResult.INTERCEPTION),
        (re.compile(r"\bpass\s+complete\b", re.I), PlayResult.COMPLETE),
        (re.compile(r"\bpass\b.*\bfor\s+no\s+gain\b", re.I), PlayResult.COMPLETE),
        (re.compile(r"\bpass\b.*\bfor\s+\d+\s+yards", re.I), PlayResult.COMPLETE),
        # Sack / scramble / rush
        (re.compile(r"\bsacked\b", re.I), PlayResult.SACK_TAKEN),
        (re.compile(r"\bscramble\b.*\btouchdown\b", re.I), PlayResult.TOUCHDOWN_RUN),
        (re.compile(r"\bscramble\b.*\bfor\s+\d+\s+yards|\bscrambles\b", re.I), PlayResult.SCRAMBLE_GAIN),
        (re.compile(r"\bfor\s+no\s+gain\b", re.I), PlayResult.RUSH_NO_GAIN),
        (re.compile(r"\bloss\s+of\s+\d+", re.I), PlayResult.RUSH_LOSS),
        (re.compile(r"\brushes?\b.*\bfor\s+\d+\s+yards|\brun\b.*\bfor\s+\d+\s+yards", re.I), PlayResult.RUSH_GAIN),
        # Fumbles (explicit parentheticals from coaching notes)
        (
            re.compile(r"fumble.*recovered\s+by.*\(same\s+team\)", re.I),
            PlayResult.FUMBLE_RECOVERED_OWN,
        ),
        (
            re.compile(r"fumble.*recovered\s+by.*\(other\s+team\)", re.I),
            PlayResult.FUMBLE_LOST,
        ),
        # Touchdowns / safety
        (re.compile(r"\bpass\b.*\btouchdown\b|\btouchdown\b.*\bpass\b", re.I), PlayResult.TOUCHDOWN_PASS),
        (re.compile(r"\brushes?\b.*\btouchdown\b|\brun\b.*\btouchdown\b", re.I), PlayResult.TOUCHDOWN_RUN),
        (re.compile(r"\breturn\b.*\btouchdown\b|\btouchdown\b.*\breturn\b", re.I), PlayResult.TOUCHDOWN_RETURN),
        (re.compile(r"\bsafety\b", re.I), PlayResult.SAFETY),
        # Penalties (when play still described as penalty)
        (re.compile(r"penalty.*offense|offensive\s+penalty", re.I), PlayResult.PENALTY_OFFENSE),
        (re.compile(r"penalty.*defense|defensive\s+penalty", re.I), PlayResult.PENALTY_DEFENSE),
        (re.compile(r"offsetting\s+penalties|penalties\s+offset", re.I), PlayResult.PENALTY_OFFSETTING),
    ]


PLAY_RESULT_PATTERNS: Final[list[tuple[re.Pattern[str], PlayResult]]] = _compile_patterns()

_PLAY_TYPE_FALLBACK: Final[dict[PlayType, PlayResult]] = {
    PlayType.RUN: PlayResult.RUSH_NO_GAIN,
    PlayType.PASS: PlayResult.UNKNOWN,
    PlayType.SACK: PlayResult.SACK_TAKEN,
    PlayType.SCRAMBLE: PlayResult.SCRAMBLE_GAIN,
    PlayType.PUNT: PlayResult.PUNT_NORMAL,
    PlayType.KICKOFF: PlayResult.KICKOFF_NORMAL,
    PlayType.FIELD_GOAL: PlayResult.UNKNOWN,
    PlayType.EXTRA_POINT: PlayResult.UNKNOWN,
    PlayType.TWO_POINT: PlayResult.UNKNOWN,
    PlayType.PENALTY_NO_PLAY: PlayResult.NO_PLAY,
    PlayType.SPIKE: PlayResult.SPIKE,
    PlayType.KNEEL: PlayResult.KNEEL,
    PlayType.TIMEOUT: PlayResult.NO_PLAY,
    PlayType.UNKNOWN: PlayResult.UNKNOWN,
}


def normalize_play_result(
    raw_text: str | None,
    play_type: PlayType | None = None,
    *,
    scoring_team_is_offense: bool | None = None,
) -> PlayResult:
    """Map a free-text play description to a normalized :class:`PlayResult`.

    ``scoring_team_is_offense`` is reserved for future disambiguation (e.g. scoring
    plays); it does not affect classification today.
    """
    _ = scoring_team_is_offense

    if raw_text is None or not str(raw_text).strip():
        logger.debug("normalize_play_result: missing or blank raw_text; returning UNKNOWN")
        return PlayResult.UNKNOWN

    text = str(raw_text).strip()
    for pattern, result in PLAY_RESULT_PATTERNS:
        if pattern.search(text):
            return result

    if play_type is not None:
        return _PLAY_TYPE_FALLBACK.get(play_type, PlayResult.UNKNOWN)
    return PlayResult.UNKNOWN

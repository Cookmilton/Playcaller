"""
Map ESPN summary play type + description strings to canonical enums and flags.

This module is **ESPN-specific** and lives under ``normalization/espn`` so
:class:`~football_history_warehouse.domain.enums` stay vendor-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass

from football_history_warehouse.domain.enums import DriveResultBucket, PlayFamily, PlayResultCategory


@dataclass(frozen=True, slots=True)
class InferredPlaySemantics:
    play_family: PlayFamily
    result_category: PlayResultCategory
    is_touchdown: bool | None
    is_turnover: bool | None
    is_sack: bool
    is_scramble: bool
    is_no_play_from_penalty: bool
    flag_penalty: bool


def infer_play_semantics(
    play_type_text: str | None,
    description_text: str | None,
) -> InferredPlaySemantics:
    """
    Heuristic mapping — summary feeds omit explicit down/distance and sometimes blur categories.

    Unknown or ambiguous inputs map to ``UNKNOWN`` / ``OTHER`` with null flags.
    """
    pt = (play_type_text or "").strip().lower()
    desc = (description_text or "").strip().lower()
    blob = f"{pt} {desc}"

    # Administrative / no substantive play
    if "no play" in blob or "penalty offset" in blob or "measurement" in blob:
        return InferredPlaySemantics(
            PlayFamily.NO_PLAY,
            PlayResultCategory.OTHER,
            None,
            None,
            False,
            False,
            True,
            "penalty" in blob,
        )

    if "spike" in blob:
        return InferredPlaySemantics(
            PlayFamily.PASS,
            PlayResultCategory.SPIKE,
            False,
            False,
            False,
            False,
            False,
            False,
        )
    if "kneel" in blob or "kneels" in blob:
        return InferredPlaySemantics(
            PlayFamily.RUN,
            PlayResultCategory.KNEEL,
            False,
            False,
            False,
            False,
            False,
            False,
        )

    td = "touchdown" in blob or "touchdown" in pt
    if td:
        return InferredPlaySemantics(
            PlayFamily.PASS if "pass" in blob or "pass" in pt else PlayFamily.RUN,
            PlayResultCategory.TOUCHDOWN,
            True,
            False,
            False,
            False,
            False,
            False,
        )

    if "interception" in blob or "intercepted" in blob:
        return InferredPlaySemantics(
            PlayFamily.PASS,
            PlayResultCategory.INTERCEPTION,
            False,
            True,
            False,
            False,
            False,
            False,
        )

    if "fumble" in blob and ("recovered" in blob or "lost" in blob):
        lost = "lost" in blob or "opponent" in blob
        return InferredPlaySemantics(
            PlayFamily.OTHER,
            PlayResultCategory.FUMBLE_LOST if lost else PlayResultCategory.FUMBLE,
            False,
            True,
            False,
            False,
            False,
            False,
        )

    if "sack" in blob or pt == "sack":
        return InferredPlaySemantics(
            PlayFamily.PASS,
            PlayResultCategory.SACK,
            False,
            False,
            True,
            False,
            False,
            False,
        )

    if "scramble" in blob:
        return InferredPlaySemantics(
            PlayFamily.PASS,
            PlayResultCategory.SCRAMBLE,
            False,
            False,
            False,
            True,
            False,
            False,
        )

    if "incomplete" in blob or "incompletion" in pt:
        return InferredPlaySemantics(
            PlayFamily.PASS,
            PlayResultCategory.INCOMPLETE,
            False,
            False,
            False,
            False,
            False,
            False,
        )

    if "pass" in pt or "pass" in blob:
        complete = "complete" in blob or "reception" in pt or "reception" in blob
        return InferredPlaySemantics(
            PlayFamily.PASS,
            PlayResultCategory.COMPLETE if complete else PlayResultCategory.INCOMPLETE,
            False,
            False,
            False,
            False,
            False,
            False,
        )

    if "rush" in pt or "run" in pt or "rushing" in blob:
        return InferredPlaySemantics(
            PlayFamily.RUN,
            PlayResultCategory.OTHER,
            False,
            False,
            False,
            False,
            False,
            False,
        )

    if "punt" in pt or "punt" in blob:
        return InferredPlaySemantics(
            PlayFamily.PUNT,
            PlayResultCategory.PUNT,
            False,
            False,
            False,
            False,
            False,
            False,
        )

    if "field goal" in blob or "field goal" in pt:
        good = "good" in blob or "is good" in blob
        miss = "no good" in blob or "miss" in blob
        if good:
            rc = PlayResultCategory.FIELD_GOAL_GOOD
        elif miss:
            rc = PlayResultCategory.FIELD_GOAL_NO_GOOD
        else:
            rc = PlayResultCategory.OTHER
        return InferredPlaySemantics(
            PlayFamily.FIELD_GOAL,
            rc,
            False,
            False,
            False,
            False,
            False,
            False,
        )

    if "kickoff" in blob or pt == "kickoff":
        return InferredPlaySemantics(
            PlayFamily.KICKOFF,
            PlayResultCategory.KICKOFF,
            False,
            False,
            False,
            False,
            False,
            False,
        )

    if "penalty" in blob:
        return InferredPlaySemantics(
            PlayFamily.PENALTY_ONLY,
            PlayResultCategory.PENALTY,
            None,
            None,
            False,
            False,
            False,
            True,
        )

    if "timeout" in blob:
        return InferredPlaySemantics(
            PlayFamily.OTHER,
            PlayResultCategory.TIMEOUT,
            None,
            None,
            False,
            False,
            False,
            False,
        )

    return InferredPlaySemantics(
        PlayFamily.UNKNOWN,
        PlayResultCategory.UNKNOWN,
        None,
        None,
        False,
        False,
        False,
        False,
    )


def infer_drive_result_bucket_from_last_play(
    play_type_text: str | None,
    description_text: str | None,
) -> DriveResultBucket:
    sem = infer_play_semantics(play_type_text, description_text)
    if sem.is_touchdown:
        return DriveResultBucket.TOUCHDOWN
    if sem.result_category == PlayResultCategory.FIELD_GOAL_GOOD:
        return DriveResultBucket.FIELD_GOAL
    if sem.result_category == PlayResultCategory.FIELD_GOAL_NO_GOOD:
        return DriveResultBucket.FIELD_GOAL_MISS
    if sem.result_category == PlayResultCategory.PUNT or sem.play_family == PlayFamily.PUNT:
        return DriveResultBucket.PUNT
    if sem.is_turnover or sem.result_category in (
        PlayResultCategory.INTERCEPTION,
        PlayResultCategory.FUMBLE_LOST,
    ):
        return DriveResultBucket.TURNOVER
    blob = (description_text or "").lower()
    if "fourth" in blob and "down" in blob:
        return DriveResultBucket.TURNOVER_ON_DOWNS
    return DriveResultBucket.UNKNOWN

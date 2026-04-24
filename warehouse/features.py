from __future__ import annotations

from warehouse.models import DerivedPlayFeatures, Game, Play
from warehouse.taxonomy import PlayResult, PlayType


def _was_scoring_for_new_drive(prev: Play) -> bool:
    if prev.touchdown:
        return True
    if prev.play_result in (
        PlayResult.FIELD_GOAL_MADE,
        PlayResult.SAFETY,
        PlayResult.EXTRA_POINT_MADE,
        PlayResult.TWO_POINT_GOOD,
    ):
        return True
    return False


def _possession_changed(prev: Play, curr: Play) -> bool:
    a, b = prev.possession_team, curr.possession_team
    if a is None or b is None:
        return False
    return a != b


def _should_increment_drive(prev: Play, curr: Play) -> bool:
    if _possession_changed(prev, curr):
        return True
    if _was_scoring_for_new_drive(prev):
        return True
    if prev.play_type == PlayType.KICKOFF:
        return True
    return False


def _score_diff_bucket(diff: int) -> str:
    if diff <= -17:
        return "blowout_trail"
    if -16 <= diff <= -9:
        return "trail"
    if -8 <= diff <= -1:
        return "one_score_trail"
    if diff == 0:
        return "tied"
    if 1 <= diff <= 8:
        return "one_score_lead"
    if 9 <= diff <= 16:
        return "lead"
    return "blowout_lead"


def _field_zone(yardline_100: int | None) -> str:
    if yardline_100 is None:
        return "na"
    y = int(yardline_100)
    if 80 <= y <= 100:
        return "own_deep"
    if 50 <= y <= 79:
        return "own"
    if 21 <= y <= 49:
        return "opp"
    if 0 <= y <= 20:
        return "red_zone"
    return "na"


def _distance_bucket(distance: int | None) -> str:
    if distance is None:
        return "na"
    d = int(distance)
    if 1 <= d <= 3:
        return "short"
    if 4 <= d <= 7:
        return "medium"
    if d >= 8:
        return "long"
    return "na"


def _game_script(play: Play, score_diff: int) -> str:
    q = play.quarter
    t = play.clock_seconds
    raw_remaining = (4 - q) * 900 + (t if t is not None else 0)
    game_seconds_remaining = max(0, raw_remaining)
    diff = score_diff

    if diff >= 14 and game_seconds_remaining <= 900 and q == 4:
        return "protect_lead"
    if diff <= -14 and game_seconds_remaining <= 900:
        return "desperate"
    if diff <= -8:
        return "catch_up"
    if diff >= 8:
        return "protect_lead"
    return "neutral"


def compute_features(
    plays: list[Play],
    *,
    game: Game,
) -> list[DerivedPlayFeatures]:
    out: list[DerivedPlayFeatures] = []
    drive_number = 1
    prev: Play | None = None

    for play in plays:
        prev_same_drive: Play | None = None
        if prev is None:
            pass
        elif _should_increment_drive(prev, play):
            drive_number += 1
        else:
            prev_same_drive = prev

        prev_play_type: str | None = (
            None
            if prev_same_drive is None
            else prev_same_drive.play_type.value
        )

        y = play.yardline_100
        d_down = play.down
        d_dist = play.distance

        red_zone = y is not None and y <= 20
        goal_to_go = (
            d_down is not None
            and d_dist is not None
            and y is not None
            and d_dist >= y
        )
        four_down_territory = (
            d_down == 4 and y is not None and y <= 55
        )
        two_minute = (
            play.quarter in (2, 4)
            and play.clock_seconds is not None
            and play.clock_seconds <= 120
        )

        score_diff = int(play.score_offense) - int(play.score_defense)
        score_bucket = _score_diff_bucket(score_diff)
        fz = _field_zone(y)
        dist_b = _distance_bucket(d_dist)
        script = _game_script(play, score_diff)

        out.append(
            DerivedPlayFeatures(
                play_id=play.id,
                red_zone=red_zone,
                goal_to_go=goal_to_go,
                four_down_territory=four_down_territory,
                two_minute=two_minute,
                score_diff=score_diff,
                score_diff_bucket=score_bucket,
                field_zone=fz,
                distance_bucket=dist_b,
                game_script=script,
                previous_play_type=prev_play_type,
                drive_number=drive_number,
            )
        )
        prev = play

    return out

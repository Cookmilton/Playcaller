"""Per-drive letter grades from reconciled truth + replay rows."""

from __future__ import annotations

from typing import List, Literal, Sequence

from playcaller.game import (
    DRIVE_END_FIELD_GOAL,
    DRIVE_END_FIELD_GOAL_MISS,
    DRIVE_END_PUNT,
    DRIVE_END_TOUCHDOWN,
    DRIVE_END_TURNOVER_FUMBLE,
    DRIVE_END_TURNOVER_INT,
    DRIVE_END_TURNOVER_ON_DOWNS,
    DRIVE_END_UNKNOWN,
    Drive,
)
from playcaller.play_event_segment import PlayEventSegment, segment_from_actual
from playcaller.reconciliation.drive_reconciler import ReconciledDrive
from playcaller.review.unified_review import UnifiedReviewRow
from playcaller.review_insights.drive_failure import explain_drive_failure
from playcaller.review_insights.models import DriveGrade
from playcaller.review_insights.scoring_weights import (
    EFFICIENCY_POINTS_TIER_HIGH,
    EFFICIENCY_POINTS_TIER_LOW,
    EFFICIENCY_POINTS_TIER_MID,
    EFFICIENCY_POINTS_TIER_MID_HIGH,
    EFFICIENCY_POINTS_TIER_MIN,
    EFFICIENCY_YPP_GREAT_MIN,
    EFFICIENCY_YPP_GOOD_MIN,
    EFFICIENCY_YPP_OK_MIN,
    EFFICIENCY_YPP_WEAK_MIN,
    GRADE_A_MIN,
    GRADE_B_MIN,
    GRADE_C_MIN,
    GRADE_D_MIN,
    MODEL_AGREE_NEUTRAL_POINTS,
    MODEL_AGREE_TIER_HIGH,
    MODEL_AGREE_TIER_MID,
    MODEL_WEIGHT_MAX,
    NEGATIVE_PLAY_YARDS_THRESHOLD,
    OUTCOME_POSSESSING_END_OF_HALF,
    OUTCOME_POSSESSING_FIELD_GOAL,
    OUTCOME_POSSESSING_FIELD_GOAL_MISS,
    OUTCOME_POSSESSING_PUNT_BACKED_UP,
    OUTCOME_POSSESSING_PUNT_OPEN_FIELD,
    OUTCOME_POSSESSING_SAFETY,
    OUTCOME_POSSESSING_TOUCHDOWN,
    OUTCOME_POSSESSING_TURNOVER,
    OUTCOME_POSSESSING_TURNOVER_ON_DOWNS,
    OUTCOME_POSSESSING_UNKNOWN_NEUTRAL,
    OUTCOME_WEIGHT_MAX,
    PUNT_BACKED_UP_YARD_LINE_MIN,
    SITUATIONAL_NO_DRIVE_KILLER_PENALTY_BONUS,
    SITUATIONAL_NO_NEGATIVE_EXPLOSIVE_BONUS,
    SITUATIONAL_THIRD_CONVERSION_CAP,
    SITUATIONAL_THIRD_CONVERSION_POINTS_EACH,
    SITUATIONAL_WEIGHT_MAX,
)


def _scr_plays(drive: Drive) -> List:
    return [p for p in (drive.plays or []) if segment_from_actual(p) == PlayEventSegment.OFFENSE]


def is_kneel_only_drive(drive: Drive) -> bool:
    pl = drive.plays or []
    if len(pl) != 1:
        return False
    p = pl[0]
    rt = (p.result_type or "").strip().lower()
    if rt == "kneel":
        return True
    return "kneel" in (p.description or "").lower()


def _possessing_outcome_base(reconciled: ReconciledDrive, drive: Drive) -> int:
    esp = reconciled.espn_coarse_bucket or ""
    kind = reconciled.outcome_kind

    if esp == "END_HALF":
        return OUTCOME_POSSESSING_END_OF_HALF
    if esp == "SAFETY":
        return OUTCOME_POSSESSING_SAFETY
    if kind == DRIVE_END_TOUCHDOWN:
        return OUTCOME_POSSESSING_TOUCHDOWN
    if kind == DRIVE_END_FIELD_GOAL:
        return OUTCOME_POSSESSING_FIELD_GOAL
    if kind == DRIVE_END_FIELD_GOAL_MISS:
        return OUTCOME_POSSESSING_FIELD_GOAL_MISS
    if kind == DRIVE_END_PUNT:
        yl = reconciled.start_field_position.yard_line
        if yl is not None and int(yl) >= PUNT_BACKED_UP_YARD_LINE_MIN:
            return OUTCOME_POSSESSING_PUNT_BACKED_UP
        return OUTCOME_POSSESSING_PUNT_OPEN_FIELD
    if kind in (DRIVE_END_TURNOVER_INT, DRIVE_END_TURNOVER_FUMBLE):
        return OUTCOME_POSSESSING_TURNOVER
    if kind == DRIVE_END_TURNOVER_ON_DOWNS:
        return OUTCOME_POSSESSING_TURNOVER_ON_DOWNS
    if kind == DRIVE_END_UNKNOWN and reconciled.possession_points > 0:
        if esp == "TD":
            return OUTCOME_POSSESSING_TOUCHDOWN
        if esp == "FG":
            return OUTCOME_POSSESSING_FIELD_GOAL
    if kind == DRIVE_END_UNKNOWN:
        return OUTCOME_POSSESSING_UNKNOWN_NEUTRAL
    return OUTCOME_POSSESSING_UNKNOWN_NEUTRAL


def _outcome_points(
    reconciled: ReconciledDrive,
    drive: Drive,
    *,
    perspective: Literal["possession_offense", "defense"],
) -> int:
    """``possession_offense`` = grade the team with the ball; ``defense`` = our defensive grade."""
    q = _possessing_outcome_base(reconciled, drive)
    if perspective == "possession_offense":
        return max(-5, min(OUTCOME_WEIGHT_MAX, q))
    # Defense: high when their possession quality is low.
    if reconciled.espn_coarse_bucket == "SAFETY":
        return OUTCOME_WEIGHT_MAX
    adj = OUTCOME_WEIGHT_MAX - q
    return max(0, min(OUTCOME_WEIGHT_MAX, adj))


def _efficiency_points(drive: Drive) -> int:
    scr = _scr_plays(drive)
    if not scr:
        return EFFICIENCY_POINTS_TIER_MIN
    net = sum(int(p.yards_gained) + (int(p.penalty_yards) if p.penalty else 0) for p in scr)
    ypp = net / max(1, len(scr))
    if ypp >= EFFICIENCY_YPP_GREAT_MIN:
        return EFFICIENCY_POINTS_TIER_HIGH
    if ypp >= EFFICIENCY_YPP_GOOD_MIN:
        return EFFICIENCY_POINTS_TIER_MID_HIGH
    if ypp >= EFFICIENCY_YPP_OK_MIN:
        return EFFICIENCY_POINTS_TIER_MID
    if ypp >= EFFICIENCY_YPP_WEAK_MIN:
        return EFFICIENCY_POINTS_TIER_LOW
    return EFFICIENCY_POINTS_TIER_MIN


def _situational_points(drive: Drive) -> int:
    scr = _scr_plays(drive)
    conv = 0
    for p in scr:
        try:
            d0 = int(p.feed_presnap_down) if p.feed_presnap_down is not None else 0
        except (TypeError, ValueError):
            d0 = 0
        if d0 == 3 and (p.first_down or p.touchdown):
            conv += 1
    conv_pts = min(SITUATIONAL_THIRD_CONVERSION_CAP, SITUATIONAL_THIRD_CONVERSION_POINTS_EACH * conv)

    neg = False
    for p in scr:
        if p.sack:
            neg = True
            break
        try:
            y = int(p.yards_gained)
        except (TypeError, ValueError):
            y = 0
        if y <= NEGATIVE_PLAY_YARDS_THRESHOLD:
            neg = True
            break
    no_neg = 0 if neg else SITUATIONAL_NO_NEGATIVE_EXPLOSIVE_BONUS

    killer = False
    for p in scr:
        if not p.penalty:
            continue
        try:
            d0 = int(p.feed_presnap_down) if p.feed_presnap_down is not None else 0
        except (TypeError, ValueError):
            d0 = 0
        if d0 != 3:
            continue
        desc = (p.description or "").lower()
        if "hold" in desc or "false start" in desc:
            killer = True
            break
    no_killer = 0 if killer else SITUATIONAL_NO_DRIVE_KILLER_PENALTY_BONUS

    total = conv_pts + no_neg + no_killer
    return max(0, min(SITUATIONAL_WEIGHT_MAX, total))


def _model_agreement_points(rows: Sequence[UnifiedReviewRow]) -> int:
    """
    Replay exposes one recommendation per snap; we treat run/pass + bucket + family alignment
    (where present) as a stand-in for “top-call” agreement when ranked alternatives are absent.
    """
    scored: List[bool] = []
    for r in rows:
        if r.event_segment != PlayEventSegment.OFFENSE:
            continue
        if r.replay_error:
            continue
        c = r.comparison
        bits = [c.run_pass_match, c.summary_bucket_match, c.family_match]
        usable = [b for b in bits if b is not None]
        if not usable:
            continue
        scored.append(all(b is True for b in usable))
    if not scored:
        return MODEL_AGREE_NEUTRAL_POINTS
    rate = sum(1 for x in scored if x) / len(scored)
    if rate >= MODEL_AGREE_TIER_HIGH:
        return MODEL_WEIGHT_MAX
    if rate >= MODEL_AGREE_TIER_MID:
        return 6
    return 2


def _letter(total: int) -> str:
    if total >= GRADE_A_MIN:
        return "A"
    if total >= GRADE_B_MIN:
        return "B"
    if total >= GRADE_C_MIN:
        return "C"
    if total >= GRADE_D_MIN:
        return "D"
    return "F"


def compute_drive_grade(
    drive: Drive,
    drive_review_rows: Sequence[UnifiedReviewRow],
    reconciled: ReconciledDrive,
    *,
    perspective: Literal["possession_offense", "defense"],
) -> DriveGrade:
    """
    Grade a single drive using reconciled outcome + archived plays + review rows for that drive.

    * ``perspective='possession_offense'`` — grade the offensive possession (our OC when we have the ball).
    * ``perspective='defense'`` — grade our defensive performance when the opponent possessed the ball.
    """
    if is_kneel_only_drive(drive):
        return DriveGrade(
            letter="—",
            total_score=None,
            outcome_component=None,
            efficiency_component=None,
            situational_component=None,
            model_component=None,
            failure_explanations=(),
        )

    oc = _outcome_points(reconciled, drive, perspective=perspective)
    eff = _efficiency_points(drive)
    sit = _situational_points(drive)
    mod = _model_agreement_points(drive_review_rows)

    total = max(0, min(100, oc + eff + sit + mod))
    letter = _letter(total)
    failures = ()
    if letter in ("C", "D", "F"):
        failures = tuple(explain_drive_failure(drive, drive_review_rows, reconciled))
    return DriveGrade(
        letter=letter,
        total_score=int(total),
        outcome_component=int(oc),
        efficiency_component=int(eff),
        situational_component=int(sit),
        model_component=int(mod),
        failure_explanations=failures,
    )

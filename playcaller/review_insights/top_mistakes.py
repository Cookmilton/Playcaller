"""Ranked play-level mistakes for Review Session (deterministic severity model)."""

from __future__ import annotations

from typing import List, Sequence

from playcaller.evaluation.metrics import actual_fields_is_turnover
from playcaller.game import Game
from playcaller.play_event_segment import PlayEventSegment
from playcaller.review.unified_review import UnifiedReviewRow
from playcaller.review_insights.comparison_format import (
    actual_family_match_rank,
    build_model_top_three_lines,
    format_actual_comparison_line,
    format_film_room_timestamp,
    normalized_top_families,
)
from playcaller.review_insights.models import PlayMistake
from playcaller.review_insights.situational import (
    filter_our_offense_rows,
    offensive_success,
    row_matches_situation,
)
from playcaller.review_insights.thresholds import (
    MIN_TOP_MISTAKE_SEVERITY,
    MODEL_CONF_HIGH,
    MODEL_CONF_MID,
)
from playcaller.ui.format_play_context import format_play_context


def _down_dist(pre: dict) -> tuple[int | None, int | None]:
    try:
        d_raw = pre.get("down")
        d = int(d_raw) if d_raw is not None else None
    except (TypeError, ValueError):
        d = None
    try:
        dist_raw = pre.get("distance")
        dist = int(dist_raw) if dist_raw is not None else None
    except (TypeError, ValueError):
        dist = None
    return d, dist


def mistake_context_summary(row: UnifiedReviewRow, *, game: Game) -> str:
    """Canonical presnap line for mistake cards (same as film room / situational)."""
    return format_play_context(row.pre_snap, row.event_segment, game=game, drive_id=row.drive_id)


def _model_disagreement_points(row: UnifiedReviewRow) -> int:
    if row.event_segment != PlayEventSegment.OFFENSE:
        return 0
    c = row.comparison
    if not any(v is False for v in (c.run_pass_match, c.summary_bucket_match, c.family_match)):
        tops = normalized_top_families(row.model_structured)
        af = str(row.actual_structured.get("family") or "").strip()
        rank = actual_family_match_rank(row) if tops else None
        if tops and af and rank is None:
            return min(40, 10)
        return 0

    conf = float(row.confidence) if row.confidence is not None else 0.0
    if conf >= MODEL_CONF_HIGH:
        base = 40
    elif conf >= MODEL_CONF_MID:
        base = 25
    else:
        base = 15

    tops = normalized_top_families(row.model_structured)
    af = str(row.actual_structured.get("family") or "").strip()
    rank = actual_family_match_rank(row) if tops else None
    extra = 10 if (tops and af and rank is None) else 0
    return min(40, base + extra)


def _outcome_damage_points(game: Game, row: UnifiedReviewRow) -> int:
    struct = row.actual_structured
    if actual_fields_is_turnover(struct):
        return 40
    try:
        yds = int(struct.get("yards_gained", 0) or 0)
    except (TypeError, ValueError):
        yds = 0
    pre = row.pre_snap
    d, dist = _down_dist(pre)
    rt = str(struct.get("result_type") or "").lower()
    is_sack = bool(struct.get("sack")) or "sack" in rt

    candidates: list[int] = []
    if d is not None and d >= 3 and yds < 0 and (is_sack or "tfl" in rt or yds < 0):
        candidates.append(30)

    success = offensive_success(game, row)
    if d in (3, 4) and success is False and not actual_fields_is_turnover(struct):
        candidates.append(25)

    if d in (1, 2) and yds < 0:
        candidates.append(15)

    if d == 3 and dist is not None and dist <= 3 and yds == 0:
        candidates.append(20)

    return max(candidates) if candidates else 0


def _situational_weight_points(row: UnifiedReviewRow) -> int:
    pre = row.pre_snap
    weights: list[int] = []
    if row_matches_situation(row, "red_zone"):
        weights.append(20)
    if row_matches_situation(row, "two_minute"):
        weights.append(15)
    d, _ = _down_dist(pre)
    if d in (3, 4):
        weights.append(15)
    try:
        q = int(pre.get("quarter", 0))
        sd = int(pre.get("score_diff", 0))
    except (TypeError, ValueError):
        q, sd = 0, 0
    if q >= 4 and sd < 0:
        weights.append(15)
    return max(weights) if weights else 0


def _why_it_matters(
    game: Game,
    row: UnifiedReviewRow,
    *,
    md: int,
    od: int,
    sw: int,
) -> str:
    parts: list[str] = []
    success = offensive_success(game, row)
    if od >= 40:
        parts.append("Turnover-level damage on the play.")
    elif od >= 30:
        parts.append("Major setback (negative play in a late-down passing situation).")
    elif od >= 25:
        parts.append("Failed to convert a critical down.")
    elif od >= 15:
        parts.append("Lost field position on an early down.")

    if md >= 40:
        parts.append("The model favored a different call with strong confidence.")
    elif md >= 25:
        parts.append("Meaningful model disagreement at medium confidence.")
    elif md >= 10:
        parts.append("The logged concept was outside the model's top families.")

    if sw >= 20:
        parts.append("Happened in the red zone where possessions are scarce.")
    elif sw >= 15:
        parts.append("High-leverage game situation (late down, two-minute, or trailing late).")

    if success is False and not parts:
        parts.append("Drive momentum stalled after this snap.")

    return " ".join(parts) if parts else "High composite severity versus session baseline."


def rank_top_mistakes(
    game: Game,
    rows: Sequence[UnifiedReviewRow],
    *,
    our_coached_espn_id: str,
    limit: int = 5,
    min_severity: int = MIN_TOP_MISTAKE_SEVERITY,
) -> List[PlayMistake]:
    """
    Return the worst offensive mistakes for the coached team (severity order).

    Empty when nothing clears ``min_severity`` — no fabricated mistakes.
    """
    candidates = filter_our_offense_rows(game, list(rows), our_coached_espn_id=our_coached_espn_id)
    scored: list[tuple[int, UnifiedReviewRow]] = []
    for row in candidates:
        if row.event_segment != PlayEventSegment.OFFENSE:
            continue
        md = _model_disagreement_points(row)
        od = _outcome_damage_points(game, row)
        sw = _situational_weight_points(row)
        total = md + od + sw
        if total < min_severity:
            continue
        scored.append((total, row))
    scored.sort(key=lambda t: (-t[0], t[1].drive_id, t[1].play_index_on_drive))

    out: list[PlayMistake] = []
    for total, row in scored[:limit]:
        lines, _, _ = build_model_top_three_lines(row)
        model_top = lines[0] if lines else (row.model_headline or "—")
        header_ctx = mistake_context_summary(row, game=game)
        md = _model_disagreement_points(row)
        od = _outcome_damage_points(game, row)
        sw = _situational_weight_points(row)
        why = _why_it_matters(game, row, md=md, od=od, sw=sw)
        out.append(
            PlayMistake(
                play_id=f"{row.drive_id}:{row.play_index_on_drive}",
                drive_number=row.drive_id + 1,
                play_number=row.play_index_on_drive,
                severity=total,
                context_summary=header_ctx,
                actual_summary=format_actual_comparison_line(row),
                model_top=model_top,
                why_it_matters=why,
                when_label=format_film_room_timestamp(row.pre_snap),
                drive_id=row.drive_id,
            )
        )
    return out

"""Situational filters and aggregates for Review Session (deterministic)."""

from __future__ import annotations

from collections import Counter
from typing import List, Literal, Optional, Sequence, Tuple

from playcaller.domain import ActualPlayResult
from playcaller.game import Game
from playcaller.live_data.drive_display import classify_drive_team_side
from playcaller.play_event_segment import PlayEventSegment
from playcaller.review.unified_review import UnifiedReviewRow
from playcaller.review_insights.models import SituationAggregate
from playcaller.review_insights.thresholds import (
    BACKED_UP_MAX_OWN_YARDLINE,
    RED_ZONE_MAX_OPP_YARDLINE,
    SECOND_LONG_MIN_DISTANCE,
    TWO_MINUTE_MAX_SECONDS,
)

SituationKey = Literal[
    "all",
    "1st_down",
    "2nd_long",
    "3rd_down",
    "red_zone",
    "backed_up",
    "two_minute",
    "4th_down",
]

SITUATION_ORDER: Tuple[SituationKey, ...] = (
    "all",
    "1st_down",
    "2nd_long",
    "3rd_down",
    "red_zone",
    "backed_up",
    "two_minute",
    "4th_down",
)

SITUATION_LABELS: Dict[SituationKey, str] = {
    "all": "All",
    "1st_down": "1st Down",
    "2nd_long": "2nd & Long",
    "3rd_down": "3rd Down",
    "red_zone": "Red Zone",
    "backed_up": "Backed Up",
    "two_minute": "2-Minute Drill",
    "4th_down": "4th Down",
}


def filter_our_offense_rows(
    game: Game,
    rows: Sequence[UnifiedReviewRow],
    *,
    our_coached_espn_id: str,
) -> List[UnifiedReviewRow]:
    """Offensive scrimmage rows where the coached team has the ball."""
    out: List[UnifiedReviewRow] = []
    for r in rows:
        if r.event_segment != PlayEventSegment.OFFENSE:
            continue
        if r.team_side == "our":
            out.append(r)
        elif r.team_side is None and our_coached_espn_id and 0 <= r.drive_id < len(game.drives):
            if classify_drive_team_side(game.drives[r.drive_id], our_coached_espn_id=our_coached_espn_id) == "our":
                out.append(r)
    return out


def _down_dist(pre: Dict[str, object]) -> Tuple[Optional[int], Optional[int]]:
    try:
        d = pre.get("down")
        di = int(d) if d is not None else None
    except (TypeError, ValueError):
        di = None
    try:
        dist = pre.get("distance")
        dist_i = int(dist) if dist is not None else None
    except (TypeError, ValueError):
        dist_i = None
    return di, dist_i


def _is_red_zone_pre(pre: Dict[str, object]) -> bool:
    if str(pre.get("territory")) != "opponents":
        return False
    try:
        yl = int(pre.get("yardline", 99))
    except (TypeError, ValueError):
        return False
    return 1 <= yl <= RED_ZONE_MAX_OPP_YARDLINE


def _is_backed_up_pre(pre: Dict[str, object]) -> bool:
    if str(pre.get("territory")) != "own":
        return False
    try:
        yl = int(pre.get("yardline", 99))
    except (TypeError, ValueError):
        return False
    return 1 <= yl <= BACKED_UP_MAX_OWN_YARDLINE


def row_matches_situation(row: UnifiedReviewRow, situation: SituationKey) -> bool:
    if situation == "all":
        return True
    pre = row.pre_snap
    d, dist = _down_dist(pre)
    if situation == "1st_down":
        return d == 1
    if situation == "2nd_long":
        return d == 2 and dist is not None and dist >= SECOND_LONG_MIN_DISTANCE
    if situation == "3rd_down":
        return d == 3
    if situation == "4th_down":
        return d == 4
    if situation == "red_zone":
        return _is_red_zone_pre(pre)
    if situation == "backed_up":
        return _is_backed_up_pre(pre)
    if situation == "two_minute":
        q = pre.get("quarter")
        sec = pre.get("seconds_remaining")
        try:
            qi = int(q) if q is not None else 0
            si = int(sec) if sec is not None else None
        except (TypeError, ValueError):
            return False
        if qi != 4 or si is None:
            return False
        return si <= TWO_MINUTE_MAX_SECONDS
    return False


def _actual_play(game: Game, row: UnifiedReviewRow) -> Optional[ActualPlayResult]:
    if row.drive_id < 0 or row.drive_id >= len(game.drives):
        return None
    plays = game.drives[row.drive_id].plays or []
    idx = row.play_index_on_drive - 1
    if 0 <= idx < len(plays):
        return plays[idx]
    return None


def offensive_success(
    game: Game,
    row: UnifiedReviewRow,
) -> Optional[bool]:
    """New set of downs or TD. ``None`` when outcome cannot be determined."""
    act = _actual_play(game, row)
    if act is not None:
        if bool(act.touchdown):
            return True
        if bool(act.first_down):
            return True
        return False
    rt = str(row.actual_structured.get("result_type") or "").lower()
    if "touchdown" in rt:
        return True
    if "first" in rt and "down" in rt:
        return True
    if rt in ("incomplete", "interception", "sack") or "intercept" in rt:
        return False
    if rt == "":
        return None
    return False


def yards_for_row(game: Game, row: UnifiedReviewRow) -> Optional[int]:
    act = _actual_play(game, row)
    if act is not None:
        return int(act.yards_gained)
    y = row.actual_structured.get("yards_gained")
    if y is None:
        return None
    try:
        return int(y)
    except (TypeError, ValueError):
        return None


def _run_pass(row: UnifiedReviewRow) -> Optional[str]:
    v = row.actual_structured.get("run_pass")
    if v in ("Run", "Pass"):
        return str(v)
    return None


def _result_label(row: UnifiedReviewRow, game: Game) -> str:
    act = _actual_play(game, row)
    if act is not None and (act.result_type or "").strip():
        return str(act.result_type).strip().lower()
    rt = row.actual_structured.get("result_type")
    if rt:
        return str(rt).strip().lower()
    return "unknown"


def aggregate_situation(
    game: Game,
    indexed_rows: Sequence[Tuple[int, UnifiedReviewRow]],
    situation: SituationKey,
) -> SituationAggregate:
    """Aggregate plays for one situation chip; indices refer to the caller's snapshot list."""
    label = SITUATION_LABELS[situation]
    picked: List[Tuple[int, UnifiedReviewRow]] = []
    for gi, row in indexed_rows:
        if row_matches_situation(row, situation):
            picked.append((gi, row))

    if not picked:
        return SituationAggregate(
            situation_key=situation,
            situation_label=label,
            play_count=0,
            success_count=0,
            success_rate=None,
            avg_yards=None,
            run_count=0,
            pass_count=0,
            most_common_result=None,
            play_indices=(),
        )

    succ = 0
    yards_vals: List[int] = []
    runs = 0
    passes = 0
    results: List[str] = []
    indices: List[int] = []

    for gi, row in picked:
        indices.append(gi)
        s = offensive_success(game, row)
        if s is True:
            succ += 1
        y = yards_for_row(game, row)
        if y is not None:
            yards_vals.append(y)
        rp = _run_pass(row)
        if rp == "Run":
            runs += 1
        elif rp == "Pass":
            passes += 1
        results.append(_result_label(row, game))

    n = len(picked)
    rate: Optional[float] = (succ / n) if n else None

    avg: Optional[float]
    if yards_vals:
        avg = sum(yards_vals) / len(yards_vals)
    else:
        avg = None

    common: Optional[str] = None
    if results:
        c = Counter(results)
        common = c.most_common(1)[0][0]

    return SituationAggregate(
        situation_key=situation,
        situation_label=label,
        play_count=n,
        success_count=succ,
        success_rate=rate,
        avg_yards=avg,
        run_count=runs,
        pass_count=passes,
        most_common_result=common,
        play_indices=tuple(indices),
    )


def build_indexed_our_offense(
    game: Game,
    rows: Sequence[UnifiedReviewRow],
    *,
    our_coached_espn_id: str,
) -> List[Tuple[int, UnifiedReviewRow]]:
    """``(index, row)`` with stable 0..n-1 indices for pattern traceability."""
    ours = filter_our_offense_rows(game, rows, our_coached_espn_id=our_coached_espn_id)
    return list(enumerate(ours))

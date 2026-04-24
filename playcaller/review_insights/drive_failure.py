"""Short, diagnostic failure reasons for underperforming drives."""

from __future__ import annotations

import re
from typing import List, Sequence, Tuple

from playcaller.domain import PASS_FAMILIES, RUN_FAMILIES
from playcaller.game import DRIVE_END_FIELD_GOAL_MISS, Drive
from playcaller.play_event_segment import PlayEventSegment, segment_from_actual
from playcaller.reconciliation.drive_reconciler import ReconciledDrive
from playcaller.review.unified_review import UnifiedReviewRow
from playcaller.review_insights.scoring_weights import (
    DRIVE_FAILURE_MAX_BULLETS,
    MODEL_CONFIDENCE_HIGH,
    NEGATIVE_PLAY_YARDS_THRESHOLD,
)


def _scr_plays(drive: Drive) -> List:
    return [p for p in (drive.plays or []) if segment_from_actual(p) == PlayEventSegment.OFFENSE]


def _ordinal(n: int) -> str:
    if n in (11, 12, 13):
        return f"{n}th"
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def _target_label(play) -> str:
    for attr in ("feed_receiver_label", "feed_target_role", "ball_carrier_or_target"):
        v = getattr(play, attr, "") or ""
        v = str(v).strip()
        if v:
            return v
    return "target"


def _down_dist_phrase(play) -> str:
    try:
        d = int(play.feed_presnap_down) if play.feed_presnap_down is not None else 0
    except (TypeError, ValueError):
        d = 0
    try:
        dist = int(play.feed_presnap_distance) if play.feed_presnap_distance is not None else 0
    except (TypeError, ValueError):
        dist = 0
    if d <= 0:
        return "scrimmage"
    return f"{_ordinal(d)} & {dist}"


def _model_top_call_phrase(row: UnifiedReviewRow) -> str:
    fam = row.model_structured.get("family") or ""
    fam_s = str(fam).replace("_", " ")
    conf = row.confidence
    if conf is not None:
        return f"{fam_s} ({int(round(100 * float(conf)))}% conf)"
    return fam_s or "model top call"


def explain_drive_failure(
    drive: Drive,
    drive_review_rows: Sequence[UnifiedReviewRow],
    reconciled: ReconciledDrive,
) -> List[str]:
    """
    Return up to :data:`DRIVE_FAILURE_MAX_BULLETS` short bullets; empty when nothing concrete.

    Deterministic ordering by internal priority then lexicographic tie-break.
    """
    candidates: List[Tuple[int, str]] = []
    scr = _scr_plays(drive)
    prio = 0

    for i, p in enumerate(scr):
        try:
            d0 = int(p.feed_presnap_down) if p.feed_presnap_down is not None else 0
        except (TypeError, ValueError):
            d0 = 0
        yds = int(p.yards_gained or 0)
        if d0 in (1, 2) and (p.sack or yds <= NEGATIVE_PLAY_YARDS_THRESHOLD):
            nxt = scr[i + 1] if i + 1 < len(scr) else None
            nd = None
            if nxt is not None and nxt.feed_presnap_down is not None:
                try:
                    nd = int(nxt.feed_presnap_down)
                except (TypeError, ValueError):
                    nd = None
            if d0 == 1 and nd == 2:
                candidates.append((30 + prio, "2nd-and-long after negative play on 1st down"))
            elif d0 == 2:
                candidates.append((29 + prio, f"Negative play on {_ordinal(2)} down"))
            prio += 1

    for p in scr:
        if not p.penalty:
            continue
        try:
            yd = int(p.penalty_yards)
        except (TypeError, ValueError):
            yd = 0
        if yd <= 0:
            continue
        desc = (p.description or "").lower()
        if "hold" in desc or "false start" in desc:
            candidates.append((25, f"Penalty pushed offense back ~{yd} yds ({_down_dist_phrase(p)})"))

    for p in scr:
        if p.turnover or (p.pass_result or "").lower() == "intercepted":
            candidates.append((40, f"Turnover on {_down_dist_phrase(p)}"))
            break

    for p in scr:
        if (p.pass_result or "").lower() != "incomplete":
            continue
        try:
            d0 = int(p.feed_presnap_down) if p.feed_presnap_down is not None else 0
        except (TypeError, ValueError):
            d0 = 0
        if d0 != 3:
            continue
        tgt = _target_label(p)
        fam = (p.family or "").strip()
        if fam in PASS_FAMILIES:
            candidates.append((23, f"Missed throw on 3rd down — look: {tgt}"))
        else:
            candidates.append((22, f"Incomplete pass on 3rd down ({_down_dist_phrase(p)})"))

    for p in scr:
        try:
            d0 = int(p.feed_presnap_down) if p.feed_presnap_down is not None else 0
        except (TypeError, ValueError):
            d0 = 0
        try:
            need = int(p.feed_presnap_distance) if p.feed_presnap_distance is not None else 0
        except (TypeError, ValueError):
            need = 0
        if d0 == 4 and need > 0 and int(p.yards_gained or 0) < need:
            if (p.family or "") in RUN_FAMILIES or (p.play_type or "").lower() == "run":
                candidates.append((18, f"Short-yardage run stuffed on {_down_dist_phrase(p)}"))

    for row in sorted(drive_review_rows, key=lambda r: r.play_index_on_drive):
        if row.event_segment != PlayEventSegment.OFFENSE:
            continue
        if row.replay_error:
            continue
        conf = row.confidence
        if conf is None or float(conf) < MODEL_CONFIDENCE_HIGH:
            continue
        c = row.comparison
        if c.run_pass_match is not False and c.summary_bucket_match is not False:
            continue
        phrase = _model_top_call_phrase(row)
        candidates.append((15, f"High-confidence model lean: {phrase}"))

    run_streak = 0
    run_yards = 0
    for p in scr:
        if (p.family or "") in RUN_FAMILIES or (p.play_type or "").lower() == "run":
            run_streak += 1
            run_yards += int(p.yards_gained or 0)
        else:
            if run_streak >= 3 and run_yards <= 6:
                candidates.append((10, f"Three straight runs for only {run_yards} yds"))
            run_streak = 0
            run_yards = 0
    if run_streak >= 3 and run_yards <= 6:
        candidates.append((10, f"Three straight runs for only {run_yards} yds"))

    if reconciled.outcome_kind == DRIVE_END_FIELD_GOAL_MISS:
        candidates.append((5, "Efficient drive stalled on a missed field goal try"))

    seen: set[str] = set()
    out: List[str] = []
    for pri, msg in sorted(candidates, key=lambda t: (-t[0], t[1])):
        key = re.sub(r"\s+", " ", msg.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(msg)
        if len(out) >= DRIVE_FAILURE_MAX_BULLETS:
            break
    return out

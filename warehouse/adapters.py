from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any, Dict, List, Optional

from playcaller.play_event_segment import PlayEventSegment
from playcaller.review.unified_review import (
    ReviewMode,
    UnifiedComparison,
    UnifiedReviewRow,
)

from warehouse.models import DerivedPlayFeatures, Game, Play
from warehouse.taxonomy import PlayType


def _warehouse_run_pass(play_type: PlayType) -> Optional[str]:
    if play_type == PlayType.RUN:
        return "Run"
    if play_type in (PlayType.PASS, PlayType.SACK, PlayType.SCRAMBLE):
        return "Pass"
    return None


def _warehouse_event_segment(play_type: PlayType) -> PlayEventSegment:
    if play_type in (
        PlayType.RUN,
        PlayType.PASS,
        PlayType.SACK,
        PlayType.SCRAMBLE,
        PlayType.SPIKE,
        PlayType.KNEEL,
    ):
        return PlayEventSegment.OFFENSE
    if play_type == PlayType.PUNT:
        return PlayEventSegment.PUNT
    if play_type == PlayType.KICKOFF:
        return PlayEventSegment.KICKOFF
    if play_type == PlayType.FIELD_GOAL:
        return PlayEventSegment.FIELD_GOAL
    if play_type == PlayType.EXTRA_POINT:
        return PlayEventSegment.PAT
    if play_type == PlayType.TWO_POINT:
        return PlayEventSegment.OTHER_SPECIAL
    if play_type in (PlayType.PENALTY_NO_PLAY, PlayType.TIMEOUT):
        return PlayEventSegment.ADMIN
    if play_type == PlayType.UNKNOWN:
        return PlayEventSegment.OFFENSE
    return PlayEventSegment.OFFENSE


def _annotate_offensive_snap_indices(rows: List[UnifiedReviewRow]) -> List[UnifiedReviewRow]:
    counts: Dict[int, int] = {}
    out: List[UnifiedReviewRow] = []
    for r in rows:
        if r.event_segment == PlayEventSegment.OFFENSE:
            counts[r.drive_id] = counts.get(r.drive_id, 0) + 1
            out.append(replace(r, offensive_snap_index=counts[r.drive_id]))
        else:
            out.append(replace(r, offensive_snap_index=None))
    return out


def to_review_rows(
    plays: list[Play],
    features: list[DerivedPlayFeatures],
    game: Game,
) -> list[UnifiedReviewRow]:
    """
    Convert normalized warehouse data into the exact row type consumed by the Review Session UI.

    Model / recommendation fields are left empty; comparisons are unset (no model to compare).
    """
    by_pid = {f.play_id: f for f in features}
    if len(by_pid) != len(features):
        msg = "features must have unique play_id values"
        raise ValueError(msg)

    ordered = sorted(plays, key=lambda p: (by_pid[p.id].drive_number, p.play_sequence))

    idx_in_drive: defaultdict[int, int] = defaultdict(int)
    rows: List[UnifiedReviewRow] = []

    for play in ordered:
        feat = by_pid.get(play.id)
        if feat is None:
            msg = f"missing DerivedPlayFeatures for play id {play.id!r}"
            raise ValueError(msg)

        idx_in_drive[feat.drive_number] += 1
        play_index = idx_in_drive[feat.drive_number]

        pre_snap: Dict[str, Any] = {
            "down": play.down,
            "distance": play.distance,
            "territory": None,
            "yardline": play.yardline_100,
            "quarter": play.quarter,
            "seconds_remaining": play.clock_seconds,
            "score_diff": feat.score_diff,
        }

        seg = _warehouse_event_segment(play.play_type)
        cmp_u = UnifiedComparison(
            run_pass_match=None,
            summary_bucket_match=None,
            family_match=None,
        )

        actual_rp = _warehouse_run_pass(play.play_type)
        yards = play.yards_gained
        actual_struct: Dict[str, Any] = {
            "summary_bucket": "",
            "actual_bucket": "",
            "family": "",
            "run_pass": actual_rp,
            "yards_gained": int(yards) if yards is not None else None,
            "play_type": play.play_type.value,
            "result_type": play.play_result.value,
        }

        raw = (play.raw_description or "").strip()
        actual_headline = raw if raw else "—"
        actual_detail = ""

        model_struct: Dict[str, Any] = {
            "summary_bucket": "",
            "family": "",
            "play_name": "",
            "run_pass": None,
        }

        # Warehouse drive_number is 1-based; Review UI uses 0-based drive indices.
        drive_id = int(feat.drive_number) - 1

        rows.append(
            UnifiedReviewRow(
                review_mode=ReviewMode.WAREHOUSE_HISTORICAL,
                audit_index=None,
                drive_id=drive_id,
                play_index_on_drive=play_index,
                team_side=None,
                pre_snap=pre_snap,
                actual_headline=actual_headline,
                actual_detail=actual_detail,
                actual_structured=actual_struct,
                model_headline="—",
                model_subline="",
                model_structured=model_struct,
                comparison=cmp_u,
                confidence=None,
                is_replay=True,
                is_historical=False,
                mismatch_tags=(),
                replay_error=None,
                chain_error=None,
                drive_result_kind=None,
                event_segment=seg,
            )
        )

    return _annotate_offensive_snap_indices(rows)

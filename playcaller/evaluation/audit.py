from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from typing import Any, Dict, List, Mapping, Optional

from ..domain import ActualPlayResult, GameContext, PASS_FAMILIES, RUN_FAMILIES
from ..features import ModelInput

# Keep equal to ``playcaller.review.snap_review.SNAP_REVIEW_RECORD_VERSION`` (documented export schema).
_AUDIT_ROW_SCHEMA_VERSION = 1


def _top_family_scores(scores: Mapping[str, float], *, n: int = 5) -> List[Dict[str, Any]]:
    if not scores:
        return []
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"family": k, "score": round(float(v), 4)} for k, v in ranked[:n]]


def _compact_model_input(mi: Optional[ModelInput]) -> Dict[str, Any]:
    if mi is None:
        return {}
    gcf = mi.meta.get("game_context_features") if isinstance(mi.meta, dict) else None
    if not isinstance(gcf, dict):
        gcf = None
    # Trim features to high-signal keys for storage size
    feat = mi.features or {}
    keys = (
        "gcf_archived_team_drives",
        "gcf_overall_run_share",
        "gcf_overall_pass_share",
        "gcf_recent_success_rate",
        "gcf_recent_explosive_rate",
        "gcf_turnover_play_rate",
        "gcf_stalled_drive_share",
        "game_flow_weighted_run_share",
        "game_flow_weighted_pass_share",
        "game_flow_prior_plays",
        "game_flow_seq_len",
    )
    slim_features = {k: feat[k] for k in keys if k in feat}
    return {
        "features": slim_features,
        "game_context_features": gcf,
    }


def next_review_ordinal(game_audit_list: List[Dict[str, Any]]) -> int:
    """Next monotonic ``review_ordinal`` for a game (1-based sequence)."""
    best = 0
    for r in game_audit_list:
        try:
            o = int(r.get("review_ordinal", 0))
        except (TypeError, ValueError):
            o = 0
        if o > best:
            best = o
    return best + 1


def supersede_open_audits_for_snap(
    game_audit_list: List[Dict[str, Any]],
    *,
    drive_epoch: int,
    plays_at_recommend: int,
) -> None:
    """
    Before appending a new open row for the same live snap, mark prior open rows obsolete.

    Matches on ``(drive_epoch, plays_at_recommend)`` so re-**Generate** without logging
    does not leave multiple competing open recommendations for one snap.
    """
    de = int(drive_epoch)
    pat = int(plays_at_recommend)
    for rec in game_audit_list:
        if rec.get("status") != "open":
            continue
        try:
            rde = int(rec.get("drive_epoch", -1))
            rpat = int(rec.get("plays_at_recommend", -1))
        except (TypeError, ValueError):
            continue
        if rde == de and rpat == pat:
            rec["status"] = "superseded"
            rec["superseded_reason"] = "superseded_by_later_recommendation_same_snap"


def audit_record_from_recommendation(
    *,
    result: Dict[str, Any],
    plays_at_recommend: int,
    drive_epoch: int,
    game_id: str,
    session_context: Optional[Mapping[str, Any]] = None,
    review_ordinal: int = 0,
    team_possession: Optional[str] = None,
    scoreboard_at_generate: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build one open audit row from a ``recommend()`` return dict (post-enrichment).

    Stored as plain dict for JSON round-trip on ``Game.recommendation_audit``.
    """
    ctx: GameContext = result["ctx"]
    scores = result.get("scores") or {}
    play = result.get("play") or {}
    mi: Optional[ModelInput] = result.get("model_input")
    fd = result.get("fourth_down") or {}
    model = result.get("model") or {}

    sgid = ""
    if session_context and isinstance(session_context, dict):
        sgid = str(session_context.get("session_game_id") or "").strip()

    row_id = uuid.uuid4().hex
    sb: Dict[str, Any] = dict(scoreboard_at_generate) if scoreboard_at_generate else {}
    play_name = str(play.get("name", "") or "")
    play_family = str(result.get("play_family", ""))
    bucket_s = str(result.get("bucket", "")).strip()
    tags: List[str] = [bucket_s] if bucket_s else []

    rec: Dict[str, Any] = {
        "review_record_version": int(_AUDIT_ROW_SCHEMA_VERSION),
        "review_ordinal": int(review_ordinal),
        "session_game_id": sgid,
        "row_id": row_id,
        "snap_id": row_id[:12],
        "ts": time.time(),
        "game_id": str(game_id),
        "drive_epoch": int(drive_epoch),
        "plays_at_recommend": int(plays_at_recommend),
        "status": "open",
        "completed": False,
        "actual_result": None,
        "pre_snap": {k: v for k, v in asdict(ctx).items()},
        "situation": {
            "down": int(ctx.down),
            "distance": int(ctx.distance),
            "yardline": int(ctx.yardline),
            "territory": str(ctx.territory),
            "quarter": int(ctx.quarter),
            "clock_seconds_remaining": int(ctx.seconds_remaining),
            "score_diff": int(ctx.score_diff),
            "offense_points": int(sb.get("offense_points", 0)),
            "defense_points": int(sb.get("defense_points", 0)),
        },
        "model_recommendation": {
            "play_call": play_name,
            "family": play_family,
            "concept_label": play_name,
            "tags": tags,
            "confidence": model.get("confidence"),
            "model_name": model.get("name"),
            "model_version": model.get("version"),
        },
        "bucket": bucket_s,
        "top_families": _top_family_scores(scores, n=6),
        "selected_family": play_family,
        "selected_play_name": play_name,
        "model": {
            "name": model.get("name"),
            "version": model.get("version"),
            "confidence": model.get("confidence"),
        },
        "fourth_down_recommendation": fd.get("recommendation"),
        "model_input_compact": _compact_model_input(mi),
    }
    if team_possession:
        rec["team_possession"] = str(team_possession)
    if scoreboard_at_generate:
        rec["scoreboard_at_generate"] = dict(scoreboard_at_generate)
    if session_context:
        rec["session_context"] = dict(session_context)
    mo = result.get("model_output")
    if mo is not None and hasattr(mo, "extras") and isinstance(mo.extras, dict):
        bs = mo.extras.get("base_scores")
        if isinstance(bs, dict) and bs:
            rec["base_scores_top"] = _top_family_scores(bs, n=4)
        sbh = mo.extras.get("scores_before_history")
        if isinstance(sbh, dict) and sbh:
            rec["scores_before_history_top"] = _top_family_scores(sbh, n=4)
    hi = result.get("historical_influence")
    if isinstance(hi, dict):
        rec["historical_influence"] = {
            "applied": hi.get("applied"),
            "reason": hi.get("reason"),
            "overall_matches": hi.get("overall_matches"),
            "similarity_tier": hi.get("similarity_tier"),
            "similarity_tier_strength": hi.get("similarity_tier_strength"),
            "overall_unique_games": hi.get("overall_unique_games"),
            "overall_scale": hi.get("overall_scale"),
            "run_lane": {
                "n": (hi.get("run_lane") or {}).get("n"),
                "adjustment": (hi.get("run_lane") or {}).get("adjustment"),
            },
            "pass_lane": {
                "n": (hi.get("pass_lane") or {}).get("n"),
                "adjustment": (hi.get("pass_lane") or {}).get("adjustment"),
            },
        }
    hm = result.get("historical_metadata")
    if isinstance(hm, dict) and hm.get("corpus_supplied"):
        rec["historical_metadata"] = {
            "status": hm.get("status"),
            "headline": hm.get("headline"),
            "overall_matches": hm.get("overall_matches"),
            "similarity_tier": hm.get("similarity_tier"),
            "similarity_widened": hm.get("similarity_widened"),
            "run_lane": hm.get("run_lane"),
            "pass_lane": hm.get("pass_lane"),
        }
    wa = result.get("warehouse_advisory")
    if isinstance(wa, dict):
        ol = wa.get("outcome_league_season")
        og = wa.get("outcome_game")
        tend = wa.get("offense_team_tendency")
        sp = wa.get("similar_plays")
        rec["warehouse_advisory"] = {
            "enabled": bool(wa.get("enabled")),
            "situation_summary": wa.get("situation_summary"),
            "scope_binding": wa.get("scope_binding"),
            "outcome_league_season_n": int(ol.get("total_plays", 0)) if isinstance(ol, dict) else None,
            "outcome_game_n": int(og.get("total_plays", 0)) if isinstance(og, dict) else None,
            "team_tendency_n": int(tend.get("total_plays", 0)) if isinstance(tend, dict) else None,
            "similar_plays_returned": len(sp.get("plays", [])) if isinstance(sp, dict) else None,
            "similar_plays_has_more": sp.get("has_more") if isinstance(sp, dict) else None,
            "notes_headline": (wa.get("notes") or [])[:3],
            "errors_headline": (wa.get("errors") or [])[:2],
        }
    return rec


def append_open_audit(game_audit_list: List[Dict[str, Any]], record: Dict[str, Any]) -> None:
    game_audit_list.append(record)


def actual_to_audit_dict(actual: ActualPlayResult) -> Dict[str, Any]:
    d = asdict(actual)
    return d


def actual_result_summary(actual: ActualPlayResult) -> Dict[str, Any]:
    """Compact logged-outcome dict for ``actual_result`` (audit-only; not used by scoring)."""
    return {
        "play_type": actual.play_type,
        "family": actual.family,
        "concept_name": actual.concept_name,
        "yards_gained": int(actual.yards_gained),
        "result_type": actual.result_type or "",
        "touchdown": bool(actual.touchdown),
        "turnover": bool(actual.turnover),
        "turnover_kind": actual.turnover_kind or "",
        "first_down": bool(actual.first_down),
        "sack": bool(actual.sack),
        "penalty": bool(actual.penalty),
        "penalty_yards": int(actual.penalty_yards),
    }


def _close_snap_review_row(rec: Dict[str, Any], actual: ActualPlayResult) -> None:
    rec["linked_actual"] = actual_to_audit_dict(actual)
    rec["actual_result"] = actual_result_summary(actual)
    rec["status"] = "closed"
    rec["completed"] = True


def void_last_closed_audit(game_audit_list: List[Dict[str, Any]]) -> None:
    """Mark the most recent closed audit as undone (user reversed the logged play)."""
    for rec in reversed(game_audit_list):
        if rec.get("status") == "closed":
            rec["status"] = "void_undone"
            rec.pop("linked_actual", None)
            rec.pop("actual_result", None)
            rec["completed"] = False
            return


def trim_stale_open_audits(game_audit_list: List[Dict[str, Any]], plays_on_drive: int) -> None:
    """Drop trailing open audits that assumed more plays than currently on the drive (e.g. after undo)."""
    n = int(plays_on_drive)
    while game_audit_list and game_audit_list[-1].get("status") == "open":
        pat = int(game_audit_list[-1].get("plays_at_recommend", -1))
        if pat > n:
            game_audit_list.pop()
        else:
            break


def link_open_audit_to_actual(
    game_audit_list: List[Dict[str, Any]],
    *,
    plays_after_log: int,
    actual: ActualPlayResult,
) -> Optional[Dict[str, Any]]:
    """
    Close the snap review row for this logged play.

    1. Prefer the most recent **open** row with ``plays_at_recommend == plays_after_log - 1``.
    2. Else the most recent **open** row with no ``actual_result`` yet (fallback for edge cases).

    Sets ``linked_actual``, ``actual_result``, ``completed``, ``status: closed``.

    Use :func:`~playcaller.evaluation.snap_review_lifecycle.close_snap_review_row_with_logged_actual`
    from UI / feed code so pairing rules stay centralized.

    Returns the closed row dict, or ``None`` if nothing matched.
    """
    target_prev = int(plays_after_log) - 1
    for rec in reversed(game_audit_list):
        if rec.get("status") != "open":
            continue
        if int(rec.get("plays_at_recommend", -999)) != target_prev:
            continue
        _close_snap_review_row(rec, actual)
        return rec
    for rec in reversed(game_audit_list):
        if rec.get("status") != "open":
            continue
        if rec.get("actual_result") is not None:
            continue
        _close_snap_review_row(rec, actual)
        return rec
    return None


def aggressiveness_label(family: str) -> str:
    """Coarse bucket for run vs pass tendency vs special."""
    if family in RUN_FAMILIES:
        return "run_family"
    if family in PASS_FAMILIES:
        return "pass_family"
    if family == "two_point":
        return "two_point"
    return "other"


def situation_bucket(ctx: Mapping[str, Any]) -> str:
    """Human-readable situation tag for grouping in metrics."""
    down = int(ctx.get("down", 1))
    dist = int(ctx.get("distance", 10))
    terr = str(ctx.get("territory", "own"))
    yl = int(ctx.get("yardline", 25))
    if terr == "opponents" and yl <= 20:
        zone = "red_zone"
    elif terr == "opponents" and yl <= 35:
        zone = "frontier"
    elif terr == "own" and yl <= 15:
        zone = "backed_up"
    else:
        zone = "field"
    short = dist <= 2 and down < 4
    long = dist >= 7
    if down == 4:
        return f"4th_{zone}"
    if short:
        return f"short_yardage_{zone}"
    if long:
        return f"long_distance_{zone}"
    return f"standard_{zone}"

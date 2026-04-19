"""Build structured model replay summaries and actual vs replay comparison fields."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from playcaller.domain import PASS_FAMILIES, RUN_FAMILIES, ActualPlayResult, GameContext

from .analysis_types import ModelReplayStructuredResult, PreSnapContextRecord
from .replay_taxonomy import replay_summary_bucket_from_recommend


def actual_run_pass_bucket(actual: ActualPlayResult) -> Optional[str]:
    """Coarse Run / Pass bucket from logged truth (family and play_type aware)."""
    fam = str(actual.family or "")
    if fam in RUN_FAMILIES:
        return "Run"
    if fam in PASS_FAMILIES:
        return "Pass"
    pt = str(actual.play_type or "").lower()
    if pt == "run":
        return "Run"
    if pt in ("pass", "qb_scramble", "qb_run"):
        return "Pass"
    rt = str(actual.result_type or "").lower()
    if rt in ("field_goal", "field_goal_miss", "punt"):
        return None
    return None


def model_replay_structured_from_recommend(result: Mapping[str, Any]) -> Optional[ModelReplayStructuredResult]:
    """Extract a stable subset from ``FootballPlayPredictor.recommend`` output."""
    fam = str(result.get("play_family") or "")
    play = result.get("play") or {}
    name = str(play.get("name") or "") if isinstance(play, dict) else ""
    bucket = str(result.get("bucket") or "")
    summary_bucket = replay_summary_bucket_from_recommend(result)
    run_pass: Optional[str] = None
    if fam in RUN_FAMILIES:
        run_pass = "Run"
    elif fam in PASS_FAMILIES:
        run_pass = "Pass"

    conf: Optional[float] = None
    model_block = result.get("model")
    if isinstance(model_block, dict):
        raw = model_block.get("confidence")
        if raw is not None:
            try:
                conf = float(raw)
            except (TypeError, ValueError):
                conf = None
    m_name = ""
    m_ver = ""
    if isinstance(model_block, dict):
        m_name = str(model_block.get("name") or "")
        m_ver = str(model_block.get("version") or "")

    if not fam and not name:
        if not summary_bucket or summary_bucket == "recommended call":
            return None
    return ModelReplayStructuredResult(
        play_family=fam,
        play_call_name=name,
        bucket=bucket,
        run_pass=run_pass,
        confidence=conf,
        summary_bucket=summary_bucket,
        model_name=m_name,
        model_version=m_ver,
    )


def model_replay_one_line(structured: Optional[ModelReplayStructuredResult]) -> str:
    """Short operator-facing summary (not for machine comparison)."""
    if structured is None:
        return ""
    parts: list[str] = []
    if structured.summary_bucket:
        parts.append(structured.summary_bucket)
    if structured.run_pass:
        parts.append(structured.run_pass)
    if structured.play_family:
        parts.append(structured.play_family.replace("_", " "))
    if structured.play_call_name:
        parts.append(f"“{structured.play_call_name}”")
    if structured.confidence is not None:
        parts.append(f"conf {structured.confidence:.0%}")
    return " · ".join(parts) if parts else ""


def family_match_actual_vs_replay(actual: ActualPlayResult, result: Mapping[str, Any]) -> Optional[bool]:
    """Whether logged family matches replay family; ``None`` if either side is unknown."""
    af = str(actual.family or "").strip()
    rf = str(result.get("play_family") or "").strip()
    if not af or not rf:
        return None
    return af == rf


def pre_snap_record_from_context(
    ctx: GameContext,
    *,
    plays_before: int,
    reconstruction_anchor: str,
    reconstruction_notes: str = "",
) -> PreSnapContextRecord:
    return PreSnapContextRecord(
        territory=str(ctx.territory),
        yardline=int(ctx.yardline),
        down=int(ctx.down),
        distance=int(ctx.distance),
        quarter=int(ctx.quarter),
        seconds_remaining=int(ctx.seconds_remaining),
        score_diff=int(ctx.score_diff),
        own_timeouts=int(ctx.own_timeouts),
        opp_timeouts=int(ctx.opp_timeouts),
        plays_this_drive_before_snap=int(plays_before),
        reconstruction_anchor=reconstruction_anchor,
        reconstruction_notes=reconstruction_notes or "",
        def_personnel=str(ctx.def_personnel),
        coverage_shell=str(ctx.coverage_shell),
        weather=str(ctx.weather),
    )

"""
Extract ESPN ``drives.previous[]`` metadata for drive integrity / debug audits.

Populates :class:`~playcaller.game.DriveFeedAuditSnapshot` at import time (no raw JSON
stored on ``Game`` beyond this snapshot).
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from playcaller.game import DriveFeedAuditSnapshot

_TdExtraPoint = Optional[Literal["pat", "two_point", "pat_missed"]]


def _intish(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _infer_espn_td_extra_point(raw: Dict[str, Any]) -> _TdExtraPoint:
    """
    After a TD, ESPN often appends PAT / 2PT lines on the scoring play or a following play.

    Returns:
      ``pat`` — standard extra point good (or assumed good when PAT wording absent).
      ``two_point`` — successful two-point conversion.
      ``pat_missed`` — missed/blocked PAT or failed 2PT (drive worth 6 on the board).
      ``None`` — TD drive but no PAT/2PT phrase found (treated as 7 in reconciler).
    """
    res = str(raw.get("result") or "").strip().upper()
    if res != "TD":
        return None
    parts: list[str] = []
    for pl in raw.get("plays") or []:
        if not isinstance(pl, dict):
            continue
        ty = pl.get("type")
        tyt = str(ty.get("text") if isinstance(ty, dict) else "").strip()
        txt = str(pl.get("text") or "").strip()
        parts.append(f"{tyt} {txt}")
    blob = " ".join(parts).lower()

    # Two-point attempt (phrase or type text)
    if "two-point" in blob or "two point conversion" in blob:
        if any(
            x in blob
            for x in (
                "no good",
                "failed",
                "intercept",
                "incomplete",
                "sack",
                "fumble",
                "missed",
            )
        ):
            return "pat_missed"
        return "two_point"

    if "extra point" in blob:
        if any(x in blob for x in ("no good", "blocked", "missed", "wide", "failed")):
            return "pat_missed"
        if "good" in blob or "is good" in blob:
            return "pat"

    return None


def parse_drive_feed_audit_from_espn_drive_dict(raw: Dict[str, Any]) -> Optional[DriveFeedAuditSnapshot]:
    """Best-effort parse of one ESPN completed-drive object; ``None`` if ``raw`` is empty."""
    if not isinstance(raw, dict) or not raw:
        return None

    start = raw.get("start") if isinstance(raw.get("start"), dict) else {}
    period = start.get("period") if isinstance(start.get("period"), dict) else {}
    clock = start.get("clock") if isinstance(start.get("clock"), dict) else {}

    start_period = _intish(period.get("number"))
    start_clock_display = str(clock.get("displayValue") or "").strip()
    start_yard_line = _intish(start.get("yardLine"))
    start_field_text = str(start.get("text") or "").strip()

    espn_result_code = str(raw.get("result") or "").strip()
    espn_display_result = str(raw.get("displayResult") or raw.get("shortDisplayResult") or "").strip()

    is_score_raw = raw.get("isScore")
    espn_is_score: Optional[bool]
    if isinstance(is_score_raw, bool):
        espn_is_score = is_score_raw
    else:
        espn_is_score = None

    feed_offensive_plays = _intish(raw.get("offensivePlays"))
    feed_yards = _intish(raw.get("yards"))

    te = raw.get("timeElapsed") if isinstance(raw.get("timeElapsed"), dict) else {}
    time_elapsed_display = str(te.get("displayValue") or "").strip()

    end = raw.get("end") if isinstance(raw.get("end"), dict) else {}
    end_period_obj = end.get("period") if isinstance(end.get("period"), dict) else {}
    end_clock = end.get("clock") if isinstance(end.get("clock"), dict) else {}
    end_period = _intish(end_period_obj.get("number"))
    end_clock_display = str(end_clock.get("displayValue") or "").strip()
    end_field_text = str(end.get("text") or "").strip()

    plays = raw.get("plays") or []
    first_play_period: Optional[int] = None
    first_play_clock_display = ""
    if isinstance(plays, list) and plays and isinstance(plays[0], dict):
        p0 = plays[0]
        per0 = p0.get("period") if isinstance(p0.get("period"), dict) else {}
        first_play_period = _intish(per0.get("number"))
        cl0 = p0.get("clock") if isinstance(p0.get("clock"), dict) else {}
        first_play_clock_display = str(cl0.get("displayValue") or "").strip()

    espn_td_extra_point = _infer_espn_td_extra_point(raw)

    return DriveFeedAuditSnapshot(
        espn_result_code=espn_result_code,
        espn_display_result=espn_display_result,
        espn_is_score=espn_is_score,
        start_period=start_period,
        start_clock_display=start_clock_display,
        start_yard_line=start_yard_line,
        start_field_text=start_field_text,
        feed_offensive_plays=feed_offensive_plays,
        feed_yards=feed_yards,
        time_elapsed_display=time_elapsed_display,
        first_play_period=first_play_period,
        first_play_clock_display=first_play_clock_display,
        end_period=end_period,
        end_clock_display=end_clock_display,
        end_field_text=end_field_text,
        espn_td_extra_point=espn_td_extra_point,
    )

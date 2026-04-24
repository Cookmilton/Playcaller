"""Formatted actual vs model comparison strings (deterministic, no fabrication)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from playcaller.play_event_segment import PlayEventSegment
from playcaller.review.unified_review import UnifiedReviewRow
from playcaller.ui.review_helpers import family_display_name, format_clock_line, format_scrimmage_line


def normalized_top_families(model_struct: Mapping[str, Any]) -> List[Tuple[str, float]]:
    """``top_families`` list from audit or replay (family + model score)."""
    raw = model_struct.get("top_families")
    if not isinstance(raw, list):
        return []
    out: List[Tuple[str, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        fam = str(item.get("family") or "").strip()
        if not fam:
            continue
        try:
            sc = float(item.get("score", 0.0))
        except (TypeError, ValueError):
            sc = 0.0
        out.append((fam, sc))
    return out


def format_film_room_timestamp(pre: Mapping[str, Any]) -> str:
    """Compact clock phrase for mistake headers (prefer feed display when present)."""
    cd = pre.get("clock_display")
    if cd:
        return str(cd).strip()
    return format_clock_line(pre).replace(" · ", " ").replace(" left", "").strip()


def format_actual_comparison_line(row: UnifiedReviewRow) -> str:
    """Single-line actual: headline + optional operator detail."""
    h = (row.actual_headline or "").strip()
    d = (row.actual_detail or "").strip()
    if h and d:
        return f"{h} — {d}"
    return h or d or "—"


def format_model_recommendation_line(
    *,
    summary_bucket: str,
    family: str,
    play_name: str,
    success_estimate: Optional[float],
) -> str:
    """One model candidate line (family label + optional success estimate from scores map)."""
    fam_l = family_display_name(family) if family else ""
    bucket = (summary_bucket or "").strip()
    play_n = (play_name or "").strip()
    parts: List[str] = []
    if bucket and bucket != fam_l:
        parts.append(bucket)
    elif fam_l and fam_l != "—":
        parts.append(fam_l)
    if play_n:
        parts.append(f"“{play_n}”")
    elif fam_l and fam_l != "—" and not parts:
        parts.append(fam_l)
    base = " — ".join(parts) if parts else "—"
    if success_estimate is None:
        return base
    return f"{base} — {int(round(100 * float(success_estimate)))}% success est."


def actual_family_match_rank(row: UnifiedReviewRow) -> Optional[int]:
    """
    1-based rank of the logged family inside the model's top family list, if any.

    ``None`` when the actual family is unknown or the model did not publish ``top_families``.
    """
    af = str(row.actual_structured.get("family") or "").strip()
    if not af:
        return None
    tops = normalized_top_families(row.model_structured)
    if not tops:
        return None
    for i, (fam, _) in enumerate(tops[:3], start=1):
        if fam == af:
            return i
    return None


def match_indicator_phrase(rank: Optional[int], *, has_ranked_list: bool) -> str:
    if rank == 1:
        return "Match: top recommendation"
    if rank == 2:
        return "Match: 2nd-ranked model call"
    if rank == 3:
        return "Match: 3rd-ranked model call"
    if not has_ranked_list:
        return "Match: no ranked family list in session data"
    return "Match: not in model top 3 (by family)"


def build_model_ranked_family_lines(row: UnifiedReviewRow) -> Tuple[List[str], Optional[int], str]:
    """
    All ranked model family lines (same formatting as top-three), match rank, indicator phrase.

    When ``top_families`` is missing, falls back to the single stored headline line.
    """
    tops = normalized_top_families(row.model_structured)
    rank = actual_family_match_rank(row) if tops else None
    phrase = match_indicator_phrase(rank, has_ranked_list=bool(tops))
    ms = row.model_structured
    lines: List[str] = []
    if len(tops) >= 1:
        sel_fam = str(ms.get("family") or "")
        sel_name = str(ms.get("play_name") or "")
        sel_bucket = str(ms.get("summary_bucket") or "")
        for fam, score in tops:
            is_top_pick = fam == sel_fam
            lines.append(
                format_model_recommendation_line(
                    summary_bucket=sel_bucket if is_top_pick else "",
                    family=fam,
                    play_name=sel_name if is_top_pick else "",
                    success_estimate=score,
                )
            )
        return lines, rank, phrase

    line = format_model_recommendation_line(
        summary_bucket=str(ms.get("summary_bucket") or ""),
        family=str(ms.get("family") or ""),
        play_name=str(ms.get("play_name") or ""),
        success_estimate=None,
    )
    if line != "—" and row.confidence is not None:
        line = f"{line} — {row.confidence:.0%} model confidence"
    return ([line] if line != "—" else []), rank, phrase


def build_model_top_three_lines(row: UnifiedReviewRow) -> Tuple[List[str], Optional[int], str]:
    """Up to three ranked model lines (slice of :func:`build_model_ranked_family_lines`)."""
    lines, rank, phrase = build_model_ranked_family_lines(row)
    return lines[:3], rank, phrase


def comparison_block_markdown_lines(row: UnifiedReviewRow) -> List[str]:
    """Bullet-ready lines for UI (actual, model stack, match)."""
    if row.event_segment != PlayEventSegment.OFFENSE:
        return [
            f"**Actual:** {format_actual_comparison_line(row)}",
            "_No offensive model comparison for this special-teams snap._",
        ]
    actual = format_actual_comparison_line(row)
    model_lines, _, phrase = build_model_top_three_lines(row)
    out = [f"**Actual:** {actual}"]
    if not model_lines:
        out.append("**Model:** _No model recommendation captured for this snap._")
    else:
        out.append("**Model:**")
        for i, ln in enumerate(model_lines, start=1):
            if i == 1:
                out.append(f"  {i}. **{ln}**")
            else:
                out.append(f"  {i}. {ln}")
    out.append(f"**{phrase}**")
    return out

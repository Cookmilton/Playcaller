"""Deterministic call-quality labels for film-room rows (auditable rubric)."""

from __future__ import annotations

from typing import AbstractSet, Optional

from playcaller.game import Game
from playcaller.play_event_segment import PlayEventSegment
from playcaller.review.unified_review import UnifiedReviewRow
from playcaller.review_insights.comparison_format import actual_family_match_rank, normalized_top_families
from playcaller.review_insights.models import CallQualityLabel
from playcaller.review_insights.situational import offensive_success
from playcaller.review_insights.thresholds import MODEL_CONF_HIGH

# Rubric exposed for audits / tests (symbol, category, condition summary)
CALL_QUALITY_RUBRIC: tuple[tuple[str, str, str], ...] = (
    ("❌", "poor", "Listed in Top Mistakes for this session."),
    ("❌", "poor", "Actual family not in model top 3 while top recommendation confidence ≥ 70%."),
    ("✅", "good", "Actual matched model top 2 and the play was a successful outcome."),
    ("✅", "good", "Short-yardage third-down conversion succeeded (high-leverage success)."),
    ("⚠️", "questionable", "Actual in model top 3 but outcome was negative or success unclear."),
    ("⚠️", "questionable", "Actual matched model but confidence was below 70% or outcome mixed."),
    ("✅", "good", "Actual matched model top 1 with neutral/unknown outcome."),
    ("—", "n/a", "Special teams or other snaps without offensive model comparison."),
)


def label_call_quality(
    game: Game,
    row: UnifiedReviewRow,
    *,
    top_mistake_play_ids: AbstractSet[str],
) -> CallQualityLabel:
    """
    Map a unified review row to a single coaching signal.

    Deterministic: same row contents and mistake set → same label.
    """
    play_id = f"{row.drive_id}:{row.play_index_on_drive}"
    if row.event_segment != PlayEventSegment.OFFENSE:
        return CallQualityLabel(
            symbol="—",
            category="n/a",
            reason="Special teams / non-offense snap — not labeled.",
        )

    if play_id in top_mistake_play_ids:
        return CallQualityLabel(
            symbol="❌",
            category="poor",
            reason="Surfaced in Top Mistakes — high-severity divergence or damage.",
        )

    tops = normalized_top_families(row.model_structured)
    rank = actual_family_match_rank(row) if tops else None
    conf = float(row.confidence) if row.confidence is not None else None
    success = offensive_success(game, row)

    try:
        dist = int(row.pre_snap.get("distance", 99))
    except (TypeError, ValueError):
        dist = 99
    try:
        down = int(row.pre_snap.get("down", 1))
    except (TypeError, ValueError):
        down = 1

    if down == 3 and dist <= 3 and success is True:
        return CallQualityLabel(
            symbol="✅",
            category="good",
            reason="Short-yardage third-down conversion — high-leverage success.",
        )

    if rank is not None and rank <= 2 and success is True:
        return CallQualityLabel(
            symbol="✅",
            category="good",
            reason="Actual matched a top-2 model family and the outcome advanced the sticks or scored.",
        )

    if rank is None and tops and conf is not None and conf >= MODEL_CONF_HIGH:
        af = str(row.actual_structured.get("family") or "").strip()
        if af:
            return CallQualityLabel(
                symbol="❌",
                category="poor",
                reason="Logged family not in the model's top 3 while the model's top pick was high confidence.",
            )

    if rank is not None and rank <= 3 and success is False:
        return CallQualityLabel(
            symbol="⚠️",
            category="questionable",
            reason="Call was in the model's top 3 but the result was negative for the offense.",
        )

    if rank is not None and rank <= 3 and success is None:
        return CallQualityLabel(
            symbol="⚠️",
            category="questionable",
            reason="Call aligned with the model's top 3 but the outcome is incomplete/unknown in the data.",
        )

    if rank == 3 and conf is not None and conf < MODEL_CONF_HIGH:
        return CallQualityLabel(
            symbol="⚠️",
            category="questionable",
            reason="Third-ranked model option matched — lower confidence tier.",
        )

    if rank == 1 and success is None:
        return CallQualityLabel(
            symbol="✅",
            category="good",
            reason="Matched the model's top recommendation (outcome not scored).",
        )

    if rank == 1 and success is False:
        return CallQualityLabel(
            symbol="⚠️",
            category="questionable",
            reason="Matched the top model call but the play lost field position or failed to convert.",
        )

    return CallQualityLabel(
        symbol="⚠️",
        category="questionable",
        reason="No stronger rule applied — review context manually.",
    )

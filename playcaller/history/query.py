"""
Similar-situation retrieval over normalized historical plays (explicit tiers, no scoring changes).

Call ``query_similar_plays`` with a ``SituationSignature`` from ``situation_signature_from_context(ctx)``
or build a corpus via ``load_history_directory`` and pass ``corpus.plays``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

from playcaller.domain import GameContext

from .buckets import (
    DISTANCE_BUCKET_NEIGHBORS,
    FIELD_ZONE_NEIGHBORS,
    SituationSignature,
    distance_buckets_relaxed,
    field_zones_relaxed,
    situation_signature_from_context,
    situation_signature_from_normalized_row,
    yardline_within_tolerance,
)
from .lanes import actual_family_to_history_lane
from .outcome_aggregates import HistoricalOutcomeSummary, aggregate_matched_play_outcomes
from .records import HistoryCorpus, NormalizedHistoricalPlay


@dataclass
class SimilarSituationAggregates:
    """Descriptive stats over matched rows (for dashboards / future priors)."""

    match_count: int
    unique_source_games: int
    success_rate: Optional[float]
    plays_with_success_flag: int
    explosive_rate: float
    turnover_rate: float
    touchdown_rate: float
    avg_yards_gained: float
    by_recommended_family: Dict[str, int] = field(default_factory=dict)
    by_actual_family: Dict[str, int] = field(default_factory=dict)
    by_recommended_run_pass: Dict[str, int] = field(default_factory=dict)
    by_actual_run_pass: Dict[str, int] = field(default_factory=dict)


@dataclass
class SimilarSituationResult:
    """Matched slice + how we got there (debuggable)."""

    query: SituationSignature
    matches: List[NormalizedHistoricalPlay]
    tier: str
    trace: Dict[str, Any]
    aggregates: SimilarSituationAggregates
    outcome_summary: Optional[HistoricalOutcomeSummary] = None


def _row_signature(row: NormalizedHistoricalPlay) -> Optional[SituationSignature]:
    return situation_signature_from_normalized_row(
        down=row.down,
        distance=row.distance,
        territory=row.territory,
        yardline=row.yardline,
        score_diff=row.score_diff,
    )


def _build_aggregates(matches: List[NormalizedHistoricalPlay]) -> SimilarSituationAggregates:
    n = len(matches)
    if n == 0:
        return SimilarSituationAggregates(
            match_count=0,
            unique_source_games=0,
            success_rate=None,
            plays_with_success_flag=0,
            explosive_rate=0.0,
            turnover_rate=0.0,
            touchdown_rate=0.0,
            avg_yards_gained=0.0,
        )

    games = {m.source_path + "::" + m.game_id for m in matches}
    succ_flags = [m.play_success for m in matches if m.play_success is not None]
    success_rate = (
        round(sum(1 for x in succ_flags if x) / len(succ_flags), 4) if succ_flags else None
    )
    explosive_rate = round(sum(1 for m in matches if m.explosive_play) / n, 4)
    turnover_rate = round(sum(1 for m in matches if m.actual.turnover) / n, 4)
    td_rate = round(sum(1 for m in matches if m.actual.touchdown) / n, 4)
    yards = [int(m.actual.yards_gained) for m in matches]
    avg_y = round(sum(yards) / n, 3)

    rec_fam: Counter[str] = Counter()
    act_fam: Counter[str] = Counter()
    rec_rp: Counter[str] = Counter()
    act_rp: Counter[str] = Counter()
    for m in matches:
        if m.recommended_family:
            rec_fam[str(m.recommended_family)] += 1
            rec_rp[actual_family_to_history_lane(m.recommended_family)] += 1
        af = str(m.actual.family or "") or "unknown"
        act_fam[af] += 1
        act_rp[actual_family_to_history_lane(m.actual.family or None)] += 1

    return SimilarSituationAggregates(
        match_count=n,
        unique_source_games=len(games),
        success_rate=success_rate,
        plays_with_success_flag=len(succ_flags),
        explosive_rate=explosive_rate,
        turnover_rate=turnover_rate,
        touchdown_rate=td_rate,
        avg_yards_gained=avg_y,
        by_recommended_family=dict(rec_fam),
        by_actual_family=dict(act_fam),
        by_recommended_run_pass=dict(rec_rp),
        by_actual_run_pass=dict(act_rp),
    )


def _row_matches_tier(
    q: SituationSignature,
    row_sig: SituationSignature,
    *,
    relax_distance: bool,
    relax_field: bool,
    yardline_tol: int,
    score_diff_max: Optional[int],
) -> bool:
    if row_sig.down != q.down:
        return False

    if score_diff_max is not None:
        if q.score_diff is not None and row_sig.score_diff is not None:
            if abs(int(q.score_diff) - int(row_sig.score_diff)) > int(score_diff_max):
                return False

    d_allowed = (
        distance_buckets_relaxed(q.distance_bucket) if relax_distance else (q.distance_bucket,)
    )
    z_allowed = field_zones_relaxed(q.field_zone) if relax_field else (q.field_zone,)
    if row_sig.distance_bucket not in d_allowed:
        return False
    if row_sig.field_zone not in z_allowed:
        return False

    if not yardline_within_tolerance(q.yardline_100, row_sig.yardline_100, yards=yardline_tol):
        return False

    return True


# Ordered fallback: first tier that reaches min_matches, else last tier with whatever matched.
_TIER_STEPS: Tuple[Tuple[str, bool, bool, int], ...] = (
    ("strict", False, False, 0),
    ("relax_distance", True, False, 0),
    ("relax_field", False, True, 0),
    ("relax_both", True, True, 0),
    ("relax_both_yard5", True, True, 5),
)


def query_similar_plays(
    plays: Sequence[NormalizedHistoricalPlay],
    query: SituationSignature,
    *,
    min_matches: int = 5,
    score_diff_max: Optional[int] = None,
) -> SimilarSituationResult:
    """
    Return historical plays whose bucketed situation matches ``query``.

    Tries **strict** match first (down + distance bucket + field zone + exact yardline band),
    then explicit widenings documented in ``result.trace["tiers_tried"]``.

    Rows without enough situation columns (no audit / incomplete exports) are skipped — see
    ``trace["rows_skipped_no_signature"]``.

    **Does not** call the recommendation engine or mutate live state.
    """
    indexed: List[Tuple[NormalizedHistoricalPlay, SituationSignature]] = []
    skipped = 0
    for row in plays:
        sig = _row_signature(row)
        if sig is None:
            skipped += 1
            continue
        indexed.append((row, sig))

    tiers_tried: List[Dict[str, Any]] = []
    best_matches: List[NormalizedHistoricalPlay] = []
    best_tier = _TIER_STEPS[-1][0]

    for tier_name, rd, rf, ytol in _TIER_STEPS:
        matched = [
            row
            for row, rs in indexed
            if _row_matches_tier(
                query,
                rs,
                relax_distance=rd,
                relax_field=rf,
                yardline_tol=ytol,
                score_diff_max=score_diff_max,
            )
        ]
        tiers_tried.append(
            {
                "tier": tier_name,
                "relax_distance": rd,
                "relax_field": rf,
                "yardline_tolerance": ytol,
                "match_count": len(matched),
            }
        )
        if len(matched) >= min_matches:
            best_matches = matched
            best_tier = tier_name
            break
        if len(matched) > len(best_matches):
            best_matches = matched
            best_tier = tier_name

    trace = {
        "yardline_filter": "Applied only when tier yardline_tolerance > 0 (otherwise buckets define field).",
        "query_signature": query.describe(),
        "query_buckets": {
            "down": query.down,
            "distance_bucket": query.distance_bucket,
            "field_zone": query.field_zone,
            "yardline_100": query.yardline_100,
            "score_diff": query.score_diff,
            "score_diff_filter_max": score_diff_max,
        },
        "rows_considered": len(indexed),
        "rows_skipped_no_signature": skipped,
        "min_matches_requested": min_matches,
        "tier_selected": best_tier,
        "tiers_tried": tiers_tried,
        "neighbor_rules": {
            "distance": {k: list(v) for k, v in DISTANCE_BUCKET_NEIGHBORS.items()},
            "field": {k: list(v) for k, v in FIELD_ZONE_NEIGHBORS.items()},
        },
    }

    ag = _build_aggregates(best_matches)
    notes: List[str] = []
    if ag.match_count < min_matches:
        notes.append(
            f"Sample size {ag.match_count} is below requested minimum {min_matches}; "
            f"broadened tier **{best_tier}** was the best available."
        )
    if ag.match_count > 0 and ag.plays_with_success_flag < ag.match_count:
        notes.append(
            "Some rows lack `play_success` (needs down/distance at log); success_rate uses the subset with flags only."
        )
    if ag.unique_source_games < ag.match_count:
        notes.append(
            "Multiple plays may come from the same saved game — use `unique_source_games` to gauge independence."
        )
    trace["interpretation_notes"] = notes
    return SimilarSituationResult(
        query=query,
        matches=best_matches,
        tier=best_tier,
        trace=trace,
        aggregates=ag,
        outcome_summary=None,
    )


def attach_outcome_summary(
    result: SimilarSituationResult,
    *,
    min_family_report_n: int = 3,
) -> SimilarSituationResult:
    """
    Attach ``HistoricalOutcomeSummary`` to a query result (keeps retrieval and metrics separate).

    Call when you want family-level outcomes; omit to avoid extra work.
    """
    summary = aggregate_matched_play_outcomes(
        result.matches, min_family_report_n=min_family_report_n
    )
    return replace(result, outcome_summary=summary)


def query_similar_plays_from_context(
    plays: Sequence[NormalizedHistoricalPlay],
    ctx: GameContext,
    **kwargs: Any,
) -> SimilarSituationResult:
    """Convenience: ``SituationSignature`` from ``ctx`` then ``query_similar_plays``."""
    sig = situation_signature_from_context(ctx)
    return query_similar_plays(plays, sig, **kwargs)


def query_similar_plays_from_corpus(
    corpus: HistoryCorpus,
    query: SituationSignature,
    **kwargs: Any,
) -> SimilarSituationResult:
    """Convenience over ``HistoryCorpus.plays``."""
    return query_similar_plays(corpus.plays, query, **kwargs)


def query_similar_plays_from_corpus_context(
    corpus: HistoryCorpus,
    ctx: GameContext,
    **kwargs: Any,
) -> SimilarSituationResult:
    return query_similar_plays_from_context(corpus.plays, ctx, **kwargs)


def result_to_debug_dict(result: SimilarSituationResult) -> Dict[str, Any]:
    """JSON-friendly summary for logging or Streamlit expander."""
    from .outcome_aggregates import outcome_summary_to_dict

    out: Dict[str, Any] = {
        "tier": result.tier,
        "match_count": len(result.matches),
        "aggregates": asdict(result.aggregates),
        "trace": result.trace,
    }
    if result.outcome_summary is not None:
        out["outcome_summary"] = outcome_summary_to_dict(result.outcome_summary)
    return out

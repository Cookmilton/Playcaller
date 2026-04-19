"""
Conservative, explainable score nudges from similar historical situations.

Applied **after** base heuristic + calibration: ``final = base + small_adjustment``.

Does not replace the recommender; safe to disable by omitting corpus or setting ``enabled=False``.

**Widening:** ``query_similar_plays`` may relax distance/field/yardline tiers. Non-strict tiers use
``SIMILARITY_TIER_STRENGTH`` so widened matches move scores less than strict matches for the same raw rates.

**Clustered games:** Lane slices use ``OutcomeTotals.n_unique_games``; when many rows repeat the same
``game_id``, ``_unique_games_lane_scale`` shrinks the lane adjustment (correlated samples).

**Thin success data:** ``lane_success_reliability_scale`` shrinks the lane when ``success_rate`` is based on
few evaluable rows (exports missing ``play_success`` / pre-snap context).

**Situation dampener:** ``situation_dampener_for_history`` slightly reduces weight on 4th down and two-minute
contexts where historical mixes are often less exchangeable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from playcaller.domain import PASS_FAMILIES, RUN_FAMILIES, GameContext

from .outcome_aggregates import OutcomeTotals
from .query import attach_outcome_summary, query_similar_plays_from_context
from .records import NormalizedHistoricalPlay

# Multiplier on lane adjustments when similarity retrieval used a widened tier (see ``query._TIER_STEPS``).
SIMILARITY_TIER_STRENGTH: Dict[str, float] = {
    "strict": 1.0,
    "relax_distance": 0.72,
    "relax_field": 0.72,
    "relax_both": 0.52,
    "relax_both_yard5": 0.45,
}


def similarity_tier_strength(tier: str) -> float:
    """Strength factor for ``tier`` from ``SimilarSituationResult.tier``; unknown tiers stay conservative."""
    return float(SIMILARITY_TIER_STRENGTH.get(str(tier), 0.65))


def _unique_games_lane_scale(n: int, n_unique_games: int) -> float:
    """
    Down-weight a lane when matched rows concentrate in few games (non-independent repetition).

    ``n_unique_games / n == 1`` → 1.0; one game duplicated ``n`` times → ~0.28 floor.
    """
    if n <= 0:
        return 0.0
    r = max(0.0, min(1.0, float(n_unique_games) / float(n)))
    return max(0.28, min(1.0, 0.28 + 0.72 * r))


def lane_slice_for_historical_metadata(lane_dbg: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """
    UI / audit slice derived from a single ``run_lane`` / ``pass_lane`` debug dict.

    Kept in this module so headline math uses the same adjustment and rates as scoring.
    """
    n = int(lane_dbg.get("n") or 0)
    if n <= 0:
        return None
    adj = float(lane_dbg.get("adjustment") or 0.0)
    sr = lane_dbg.get("success_rate")
    tr = float(lane_dbg.get("turnover_rate") or 0.0)
    if adj > 0.002:
        role = "boost"
    elif adj < -0.002:
        role = "caution"
    else:
        role = "neutral"
    return {
        "n": n,
        "success_rate": float(sr) if sr is not None else None,
        "turnover_rate": round(tr, 4),
        "adjustment": round(adj, 4),
        "role": role,
    }


@dataclass(frozen=True)
class HistoricalInfluenceConfig:
    """Tunable bounds; ``plays`` is an optional default corpus on the predictor."""

    enabled: bool = False
    plays: Optional[Sequence[NormalizedHistoricalPlay]] = None

    # Retrieval (same knobs as validation UI)
    query_min_matches: int = 5
    score_diff_max: Optional[int] = None
    min_family_report_n: int = 3

    # Application gates (conservative)
    min_overall_matches: int = 8
    min_lane_matches: int = 5
    # Ramp overall strength from n=5 up to min_overall_matches
    soft_gate_low_n: int = 5

    max_abs_adjustment: float = 0.06
    success_scale: float = 0.10
    turnover_scale: float = 0.12
    raw_signal_cap: float = 0.12
    # Lane sample weight → 1.0 when lane_n >= lane_weight_ref_n
    lane_weight_ref_n: float = 28.0


def _lane_weight(n: int, min_lane: int, ref_n: float) -> float:
    if n < min_lane:
        return 0.0
    denom = max(1e-6, float(ref_n) - float(min_lane))
    return max(0.0, min(1.0, (float(n) - float(min_lane)) / denom))


def _overall_scale(overall_n: int, low: int, target: int) -> float:
    if overall_n < low:
        return 0.0
    if overall_n >= target:
        return 1.0
    return max(0.0, min(1.0, (float(overall_n) - float(low)) / float(target - low)))


def lane_success_reliability_scale(tot: OutcomeTotals, *, reference_n: int = 5) -> float:
    """
    Shrink a lane nudge when ``success_rate`` rests on few evaluable plays (missing ``play_success`` / down-distance).

    Turnover term still uses full ``n``; this scales the **combined** raw signal after ``_lane_adjustment_raw``.
    """
    if tot.success_rate is None:
        return 1.0
    ev = int(tot.n_success_evaluable)
    if ev <= 0:
        return 0.35
    ref = max(3, int(reference_n))
    if ev >= ref:
        return 1.0
    return max(0.35, float(ev) / float(ref))


def situation_dampener_for_history(ctx: GameContext, similarity_tier: str) -> float:
    """
    Extra conservatism for high-leverage or tempo-skewed situations (multiplies lane adjustment).

    Fourth down and hurry-up histories often mix fake punts, desperation throws, and clock spikes —
    not always comparable to a normal ``GameContext`` snap even when buckets match.
    """
    tier = str(similarity_tier or "")
    strict = tier == "strict"
    d = 1.0
    try:
        if int(ctx.down) == 4:
            d *= 0.88 if not strict else 0.94
    except (TypeError, ValueError):
        pass
    if str(getattr(ctx, "game_mode", "normal") or "normal") == "two_minute":
        d *= 0.90
    return max(0.72, min(1.0, d))


def _lane_adjustment_raw(tot: OutcomeTotals, config: HistoricalInfluenceConfig) -> Tuple[float, Dict[str, Any]]:
    sr = tot.success_rate
    succ_part = (float(sr) - 0.5) * float(config.success_scale) if sr is not None else 0.0
    tov_part = -float(tot.turnover_rate) * float(config.turnover_scale)
    raw = succ_part + tov_part
    raw = max(-float(config.raw_signal_cap), min(float(config.raw_signal_cap), raw))
    return raw, {
        "success_rate": sr,
        "turnover_rate": round(float(tot.turnover_rate), 4),
        "conversion_rate": round(float(tot.conversion_rate), 4),
        "mean_yards": round(float(tot.mean_yards), 3),
        "success_component": round(succ_part, 5),
        "turnover_component": round(tov_part, 5),
        "raw_signal": round(raw, 5),
    }


def apply_historical_family_adjustments(
    scores: Mapping[str, float],
    ctx: GameContext,
    plays: Sequence[NormalizedHistoricalPlay],
    config: HistoricalInfluenceConfig,
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """
    Return (adjusted_scores, debug_dict). If history is not applied, scores are unchanged
    (copied) and debug explains why.
    """
    out = dict(scores)
    base_debug: Dict[str, Any] = {
        "applied": False,
        "config": {
            "min_overall_matches": config.min_overall_matches,
            "min_lane_matches": config.min_lane_matches,
            "max_abs_adjustment": config.max_abs_adjustment,
            "query_min_matches": config.query_min_matches,
        },
    }

    if not plays:
        base_debug["reason"] = "empty_plays"
        return out, base_debug

    base_debug["baseline_scores_for_history"] = {k: round(float(v), 4) for k, v in scores.items()}

    qres = query_similar_plays_from_context(
        plays,
        ctx,
        min_matches=int(config.query_min_matches),
        score_diff_max=config.score_diff_max,
    )
    enriched = attach_outcome_summary(qres, min_family_report_n=int(config.min_family_report_n))
    summary = enriched.outcome_summary
    overall_n = int(summary.overall.n) if summary is not None else 0

    _qb = enriched.trace.get("query_buckets") or {}
    base_debug["query_buckets"] = {
        k: _qb.get(k) for k in ("down", "distance_bucket", "field_zone", "yardline_100", "score_diff")
    }
    base_debug["similarity_tier"] = enriched.tier
    base_debug["overall_matches"] = overall_n
    base_debug["trace_min_matches_requested"] = enriched.trace.get("min_matches_requested")

    if summary is None or overall_n <= 0:
        base_debug["reason"] = "no_outcome_summary_or_zero_matches"
        return out, base_debug

    oscale = _overall_scale(overall_n, config.soft_gate_low_n, config.min_overall_matches)
    if oscale <= 0.0:
        base_debug["reason"] = "overall_below_soft_gate"
        base_debug["soft_gate_low_n"] = config.soft_gate_low_n
        return out, base_debug

    tier_s = similarity_tier_strength(str(enriched.tier))
    base_debug["similarity_tier_strength"] = round(tier_s, 4)
    base_debug["overall_unique_games"] = int(summary.overall.n_unique_games)
    sit_scale = situation_dampener_for_history(ctx, str(enriched.tier))
    base_debug["situation_dampener"] = round(sit_scale, 4)

    run_tot = summary.by_actual_lane.get("run_family")
    pass_tot = summary.by_actual_lane.get("pass_family")
    sr_ref_n = max(5, int(config.min_lane_matches))

    def _finalize_lane(
        tot: Optional[OutcomeTotals], lane_label: str
    ) -> Tuple[float, Dict[str, Any]]:
        dbg: Dict[str, Any] = {"lane": lane_label, "n": 0, "adjustment": 0.0, "gated": True}
        if tot is None:
            dbg["reason"] = "no_rows"
            return 0.0, dbg
        dbg["n"] = int(tot.n)
        if tot.n < config.min_lane_matches:
            dbg["reason"] = "below_min_lane_matches"
            return 0.0, dbg
        raw, m = _lane_adjustment_raw(tot, config)
        lw = _lane_weight(int(tot.n), config.min_lane_matches, config.lane_weight_ref_n)
        ug = _unique_games_lane_scale(int(tot.n), int(tot.n_unique_games))
        sr_scale = lane_success_reliability_scale(tot, reference_n=sr_ref_n)
        adj_pre = raw * lw * oscale * tier_s * ug * sr_scale * sit_scale
        cap = float(config.max_abs_adjustment)
        adj = max(-cap, min(cap, adj_pre))
        dbg.update(m)
        dbg["lane_weight"] = round(lw, 4)
        dbg["overall_scale"] = round(oscale, 4)
        dbg["tier_strength"] = round(tier_s, 4)
        dbg["unique_games_in_lane"] = int(tot.n_unique_games)
        dbg["unique_games_scale"] = round(ug, 4)
        dbg["success_evaluable_scale"] = round(sr_scale, 4)
        dbg["situation_dampener"] = round(sit_scale, 4)
        dbg["adjustment_pre_cap"] = round(adj_pre, 5)
        dbg["adjustment"] = round(adj, 5)
        dbg["gated"] = False
        return float(adj), dbg

    run_adj, run_dbg = _finalize_lane(run_tot, "run_family")
    pass_adj, pass_dbg = _finalize_lane(pass_tot, "pass_family")

    if max(abs(run_adj), abs(pass_adj)) < 1e-9:
        base_debug.update(
            {
                "applied": False,
                "reason": "zero_lane_adjustments",
                "run_lane": run_dbg,
                "pass_lane": pass_dbg,
            }
        )
        return dict(scores), base_debug

    per_family: Dict[str, Dict[str, float]] = {}
    for fam in out:
        if fam in RUN_FAMILIES:
            delta = run_adj
        elif fam in PASS_FAMILIES:
            delta = pass_adj
        else:
            delta = 0.0
        before = float(out[fam])
        after = round(before + delta, 4)
        out[fam] = after
        per_family[fam] = {"before": round(before, 4), "after": after, "delta": round(delta, 5)}

    base_debug.update(
        {
            "applied": True,
            "overall_scale": round(oscale, 4),
            "run_lane": run_dbg,
            "pass_lane": pass_dbg,
            "per_family": per_family,
            "influence_inputs": {
                "max_abs_adjustment_cap": float(config.max_abs_adjustment),
                "similarity_tier": enriched.tier,
                "similarity_tier_strength": round(tier_s, 4),
                "situation_dampener": round(sit_scale, 4),
                "overall_n": overall_n,
                "overall_unique_games": int(summary.overall.n_unique_games),
                "overall_scale": round(oscale, 4),
            },
        }
    )
    return out, base_debug


def resolve_historical_plays_for_call(
    config: Optional[HistoricalInfluenceConfig],
    historical_plays_kw: Optional[Sequence[NormalizedHistoricalPlay]],
) -> Optional[Sequence[NormalizedHistoricalPlay]]:
    """Plays passed to ``recommend()`` win over config.plays."""
    if historical_plays_kw is not None:
        return historical_plays_kw if len(historical_plays_kw) > 0 else None
    if config is None:
        return None
    if config.plays is not None and len(config.plays) > 0 and config.enabled:
        return config.plays
    return None

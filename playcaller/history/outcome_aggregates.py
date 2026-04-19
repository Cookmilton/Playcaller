"""
Outcome metrics for a **matched** set of ``NormalizedHistoricalPlay`` rows.

Separate from similarity **retrieval** (``query.py``): pass ``result.matches`` or any play list.

Uses the same turnover / explosive definitions as ``playcaller.evaluation.metrics`` and the same
success heuristic as ``playcaller.history.normalize.derive_play_success`` (to-go / TD / flag).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .lanes import actual_family_to_history_lane
from playcaller.evaluation.metrics import (
    EXPLOSIVE_GAIN_YARD_THRESHOLD,
    actual_fields_is_explosive,
    actual_fields_is_turnover,
)

from .normalize import derive_play_success
from .records import NormalizedHistoricalPlay

VERY_SMALL_N = 5
CAUTION_N = 20
SMALL_FAMILY_N = 3


def _actual_map(row: NormalizedHistoricalPlay) -> Dict[str, Any]:
    return asdict(row.actual)


def _resolved_success(row: NormalizedHistoricalPlay) -> Optional[bool]:
    if row.play_success is not None:
        return bool(row.play_success)
    return derive_play_success(row.actual, down=row.down, distance=row.distance)


def _caveats_for_slice(n: int, *, label: str = "slice") -> Tuple[str, ...]:
    if n == 0:
        return (f"{label}: empty — no plays.",)
    out: List[str] = []
    if n < VERY_SMALL_N:
        out.append(
            f"{label}: n={n} is very small; rates swing wildly with one play. "
            f"Do not treat percentages as precise."
        )
    elif n < CAUTION_N:
        out.append(
            f"{label}: n={n} is modest; use rates as directional hints, not definitive."
        )
    return tuple(out)


@dataclass
class OutcomeTotals:
    """Aggregates over one homogeneous play subset."""

    n: int
    n_unique_games: int
    success_rate: Optional[float]
    n_success_evaluable: int
    n_success_positive: int
    conversion_rate: float
    n_conversions: int
    touchdown_rate: float
    explosive_rate: float
    turnover_rate: float
    mean_yards: float
    median_yards: float
    caveats: Tuple[str, ...] = ()


def _aggregate_totals(
    rows: Sequence[NormalizedHistoricalPlay],
    *,
    slice_label: str = "Overall",
) -> OutcomeTotals:
    n = len(rows)
    if n == 0:
        return OutcomeTotals(
            n=0,
            n_unique_games=0,
            success_rate=None,
            n_success_evaluable=0,
            n_success_positive=0,
            conversion_rate=0.0,
            n_conversions=0,
            touchdown_rate=0.0,
            explosive_rate=0.0,
            turnover_rate=0.0,
            mean_yards=0.0,
            median_yards=0.0,
            caveats=_caveats_for_slice(0, label=slice_label),
        )

    games = {r.source_path + "::" + r.game_id for r in rows}
    yards = [int(r.actual.yards_gained) for r in rows]

    resolved = [_resolved_success(r) for r in rows]
    evaluable = [x for x in resolved if x is not None]
    n_ev = len(evaluable)
    n_pos = sum(1 for x in evaluable if x)
    success_rate = round(n_pos / n_ev, 4) if n_ev else None

    n_conv = sum(1 for r in rows if bool(r.actual.first_down) or bool(r.actual.touchdown))
    conversion_rate = round(n_conv / n, 4)

    n_td = sum(1 for r in rows if r.actual.touchdown)
    touchdown_rate = round(n_td / n, 4)

    n_ex = sum(1 for r in rows if actual_fields_is_explosive(_actual_map(r)))
    explosive_rate = round(n_ex / n, 4)

    n_tov = sum(1 for r in rows if actual_fields_is_turnover(_actual_map(r)))
    turnover_rate = round(n_tov / n, 4)

    mean_y = round(sum(yards) / n, 3)
    med_y = float(round(median(yards), 3))

    caveats = list(_caveats_for_slice(n, label=slice_label))
    if n_ev < n:
        caveats.append(
            f"{slice_label}: success_rate uses {n_ev}/{n} plays with evaluable success "
            "(needs pre-snap down/distance on the row or stored play_success)."
        )

    return OutcomeTotals(
        n=n,
        n_unique_games=len(games),
        success_rate=success_rate,
        n_success_evaluable=n_ev,
        n_success_positive=n_pos,
        conversion_rate=conversion_rate,
        n_conversions=n_conv,
        touchdown_rate=touchdown_rate,
        explosive_rate=explosive_rate,
        turnover_rate=turnover_rate,
        mean_yards=mean_y,
        median_yards=med_y,
        caveats=tuple(caveats),
    )


@dataclass
class HistoricalOutcomeSummary:
    """
    Full outcome breakdown for a matched historical set.

    ``by_actual_lane`` groups by **logged** play family lane (run vs pass families).
    ``by_actual_family`` keeps per-family slices where sample allows.
    """

    overall: OutcomeTotals
    by_actual_lane: Dict[str, OutcomeTotals] = field(default_factory=dict)
    by_actual_family: Dict[str, OutcomeTotals] = field(default_factory=dict)
    metric_definitions: Dict[str, str] = field(default_factory=dict)
    global_caveats: Tuple[str, ...] = ()


METRIC_DEFINITIONS: Dict[str, str] = {
    "success_rate": (
        "Share of plays with positive **success** per `derive_play_success` "
        "(TD, logged first down, or gain ≥ to-go when down/distance known) / stored `play_success`."
    ),
    "conversion_rate": "Share of plays with **first down** or **touchdown** on the logged result.",
    "touchdown_rate": "Share of plays with `actual.touchdown`.",
    "explosive_rate": (
        f"Share of plays with gain ≥ {EXPLOSIVE_GAIN_YARD_THRESHOLD} yards "
        "(`evaluation.metrics.actual_fields_is_explosive`, same as audit analytics)."
    ),
    "turnover_rate": (
        "Share of plays flagged as turnover (`evaluation.metrics.actual_fields_is_turnover`)."
    ),
    "mean_yards": "Mean `yards_gained` on logged plays.",
    "median_yards": "Median `yards_gained` on logged plays.",
}


def aggregate_matched_play_outcomes(
    matches: Sequence[NormalizedHistoricalPlay],
    *,
    min_family_report_n: int = SMALL_FAMILY_N,
) -> HistoricalOutcomeSummary:
    """
    Compute interpretable outcomes over **already matched** historical plays.

    Does not perform similarity search — pass ``query_similar_plays(...).matches`` or any slice.
    """
    rows = list(matches)
    overall = _aggregate_totals(rows, slice_label="Overall")

    by_lane: Dict[str, List[NormalizedHistoricalPlay]] = {
        "run_family": [],
        "pass_family": [],
        "other": [],
        "unknown": [],
    }
    by_fam: Dict[str, List[NormalizedHistoricalPlay]] = {}
    for r in rows:
        lane = actual_family_to_history_lane(r.actual.family or None)
        by_lane[lane].append(r)
        fam = str(r.actual.family or "") or "unknown"
        by_fam.setdefault(fam, []).append(r)

    lane_totals = {
        k: _aggregate_totals(by_lane[k], slice_label=f"Lane {k}")
        for k in ("run_family", "pass_family", "other", "unknown")
    }
    fam_totals: Dict[str, OutcomeTotals] = {}
    fam_caveats: List[str] = []
    for fam, lst in sorted(by_fam.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(lst) < min_family_report_n:
            fam_caveats.append(
                f"Per-family stats omitted for '{fam}' (n={len(lst)} < {min_family_report_n})."
            )
            continue
        fam_totals[fam] = _aggregate_totals(lst, slice_label=f"Family {fam}")

    global_caveats: List[str] = []
    if overall.n > 0 and overall.n_unique_games < overall.n:
        global_caveats.append(
            "Several plays may come from the same saved game — independence is not assumed."
        )
    global_caveats.extend(fam_caveats)

    return HistoricalOutcomeSummary(
        overall=overall,
        by_actual_lane=lane_totals,
        by_actual_family=fam_totals,
        metric_definitions=dict(METRIC_DEFINITIONS),
        global_caveats=tuple(global_caveats),
    )


def outcome_summary_to_dict(summary: HistoricalOutcomeSummary) -> Dict[str, Any]:
    """Structured dict for Streamlit / logs (nested dataclasses → plain data)."""

    def _tot(d: OutcomeTotals) -> Dict[str, Any]:
        return asdict(d)

    return {
        "overall": _tot(summary.overall),
        "by_actual_lane": {k: _tot(v) for k, v in summary.by_actual_lane.items()},
        "by_actual_family": {k: _tot(v) for k, v in summary.by_actual_family.items()},
        "metric_definitions": summary.metric_definitions,
        "global_caveats": list(summary.global_caveats),
    }

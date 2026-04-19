"""
Normalized **review rows** for Post-game / Review Session — stored model vs replay vs actual.

* **Stored** timelines (``snap_review_log`` / ``recommendation_audit``): model output is historical (Generate-time).
* **Replay** rows: model output is **retroactive** only — never written to exports as truth.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from playcaller.actual_result import (
    format_actual_play_operator_detail,
    format_actual_play_operator_headline,
)
from playcaller.domain import PASS_FAMILIES, RUN_FAMILIES, ActualPlayResult
from playcaller.game import Game
from playcaller.live_data.drive_display import (
    PREVIOUS_DRIVES_FILTER_BOTH,
    classify_drive_team_side,
    filter_previous_drive_indices,
)
from playcaller.replay.analysis_types import ActualVsReplayComparisonRow, PreSnapContextRecord
from playcaller.replay.comparison import actual_run_pass_bucket, model_replay_one_line
from playcaller.replay.previous_drive_replay import cached_comparison_rows_for_archived_drive
from playcaller.replay.replay_taxonomy import (
    actual_play_summary_bucket,
    coarse_bucket_alignment,
    model_summary_bucket_from_audit_row,
)
from playcaller.review.derived import linked_actual_to_play
from playcaller.review.snap_review import SNAP_REVIEW_LOG_EXPORT_KEY, review_timeline_rows
from playcaller.ui.review_helpers import family_display_name


class ReviewMode(str, Enum):
    """How Review Session sources model-vs-actual comparisons."""

    TRUE_STORED = "true_stored"  # Primary JSON key ``snap_review_log`` (gold standard)
    LEGACY_STORED = "legacy_stored"  # Rows from ``recommendation_audit`` only in file
    REPLAY_ONLY = "replay_only"  # No stored decisions — retroactive replay vs logged plays
    NOT_REVIEWABLE = "not_reviewable"


@dataclass(frozen=True)
class UnifiedComparison:
    run_pass_match: Optional[bool]
    summary_bucket_match: Optional[bool]
    family_match: Optional[bool]

    @property
    def direction_match(self) -> Optional[bool]:
        """Alias: run/pass alignment ("correct direction")."""
        return self.run_pass_match


@dataclass(frozen=True)
class UnifiedReviewRow:
    """Single rendering contract for film-room UI (all modes)."""

    review_mode: ReviewMode
    audit_index: Optional[int]
    drive_id: int
    play_index_on_drive: int
    team_side: Optional[str]  # "our" | "opp" | None (unknown)
    pre_snap: Dict[str, Any]
    actual_headline: str
    actual_detail: str
    actual_structured: Dict[str, Any]
    model_headline: str
    model_subline: str
    model_structured: Dict[str, Any]
    comparison: UnifiedComparison
    confidence: Optional[float]
    is_replay: bool
    is_historical: bool
    mismatch_tags: Tuple[str, ...] = ()
    replay_error: Optional[str] = None
    chain_error: Optional[str] = None
    drive_result_kind: Optional[str] = None

    def breakdown_dict(self) -> Dict[str, Any]:
        """Structured breakdown for UI (not a full raw row dump)."""
        pre = self.pre_snap
        return {
            "review_mode": self.review_mode.value,
            "drive_id": self.drive_id,
            "play_index_on_drive": self.play_index_on_drive,
            "down": pre.get("down"),
            "distance": pre.get("distance"),
            "territory": pre.get("territory"),
            "yardline": pre.get("yardline"),
            "quarter": pre.get("quarter"),
            "actual_summary_bucket": self.actual_structured.get("summary_bucket") or self.actual_structured.get(
                "actual_bucket"
            ),
            "model_summary_bucket": self.model_structured.get("summary_bucket"),
            "actual_run_pass": self.actual_structured.get("run_pass"),
            "model_run_pass": self.model_structured.get("run_pass"),
            "family_actual": self.actual_structured.get("family"),
            "family_model": self.model_structured.get("family"),
            "run_pass_match": self.comparison.run_pass_match,
            "summary_bucket_match": self.comparison.summary_bucket_match,
            "family_match": self.comparison.family_match,
            "is_replay": self.is_replay,
            "is_historical": self.is_historical,
            "replay_error": self.replay_error,
            "chain_error": self.chain_error,
            "confidence": self.confidence,
        }


def count_logged_plays(game: Game) -> int:
    return sum(len(getattr(d, "plays", None) or []) for d in (game.drives or []))


def resolve_review_mode(
    game: Game,
    *,
    upload_payload: Optional[Mapping[str, Any]],
    timeline: Sequence[Mapping[str, Any]],
) -> ReviewMode:
    """
    Priority: non-empty timeline → stored (true vs legacy from upload keys); else replay if plays; else not reviewable.
    """
    if timeline:
        if upload_payload is None:
            return ReviewMode.TRUE_STORED
        snap = upload_payload.get(SNAP_REVIEW_LOG_EXPORT_KEY)
        if isinstance(snap, list) and len(snap) > 0:
            return ReviewMode.TRUE_STORED
        return ReviewMode.LEGACY_STORED
    if count_logged_plays(game) > 0:
        return ReviewMode.REPLAY_ONLY
    return ReviewMode.NOT_REVIEWABLE


def export_review_capability_bullets(
    game: Game,
    *,
    mode: ReviewMode,
) -> Tuple[str, ...]:
    """User-facing export / session capability lines (no fabrication)."""
    n_snap = len(review_timeline_rows(game.recommendation_audit or []))
    n_plays = count_logged_plays(game)
    if mode in (ReviewMode.TRUE_STORED, ReviewMode.LEGACY_STORED):
        return (
            f"This session includes **full snap review timeline** ({n_snap} row(s)) — stored model-at-Generate decisions.",
            f"**Replay review** remains available as a separate read-only lens ({n_plays} logged play(s)).",
        )
    if mode == ReviewMode.REPLAY_ONLY:
        return (
            "**This file supports replay review** — comparisons use the **current model** vs recorded plays (not historical Generate output).",
            "Re-run **Generate** during a session to produce a **`snap_review_log`** timeline for stored decisions.",
        )
    return ("No logged plays — nothing to review.",)


def _model_run_pass_from_family(family: Any) -> Optional[str]:
    fam = str(family or "").strip()
    if fam in RUN_FAMILIES:
        return "Run"
    if fam in PASS_FAMILIES:
        return "Pass"
    return None


def _confidence_from_audit(row: Mapping[str, Any]) -> Optional[float]:
    mb = row.get("model")
    if isinstance(mb, dict):
        raw = mb.get("confidence")
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
    mr = row.get("model_recommendation")
    if isinstance(mr, dict):
        raw = mr.get("confidence")
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
    return None


def _pre_snap_dict(row: Mapping[str, Any]) -> Dict[str, Any]:
    pre = row.get("pre_snap")
    return dict(pre) if isinstance(pre, dict) else {}


def _pre_from_replay_record(rec: PreSnapContextRecord) -> Dict[str, Any]:
    return {
        "down": rec.down,
        "distance": rec.distance,
        "territory": rec.territory,
        "yardline": rec.yardline,
        "quarter": rec.quarter,
        "seconds_remaining": rec.seconds_remaining,
        "score_diff": rec.score_diff,
        "coverage_shell": rec.coverage_shell,
        "weather": rec.weather,
    }


def _comparison_for_stored(
    *,
    row: Mapping[str, Any],
    act: Optional[ActualPlayResult],
    act_dict: Optional[Mapping[str, Any]],
) -> Tuple[UnifiedComparison, Dict[str, Any], Dict[str, Any]]:
    model_bucket = model_summary_bucket_from_audit_row(row)
    model_rp = _model_run_pass_from_family(row.get("selected_family"))
    model_struct = {
        "summary_bucket": model_bucket,
        "family": str(row.get("selected_family") or ""),
        "play_name": str(row.get("selected_play_name") or ""),
        "situation_bucket": str(row.get("bucket") or ""),
        "run_pass": model_rp,
        "fourth_down": str(row.get("fourth_down_recommendation") or ""),
    }
    if act is None:
        cmp = UnifiedComparison(run_pass_match=None, summary_bucket_match=None, family_match=None)
        actual_struct = {
            "summary_bucket": "",
            "family": "",
            "run_pass": None,
            "yards_gained": None,
        }
        return cmp, actual_struct, model_struct

    actual_bucket = actual_play_summary_bucket(act)
    actual_rp = actual_run_pass_bucket(act)
    afam = str(act.family or "")
    sfam = str(row.get("selected_family") or "")
    fam_m: Optional[bool] = None
    if afam and sfam:
        fam_m = afam == sfam
    rpm: Optional[bool] = None
    if actual_rp is not None and model_rp is not None:
        rpm = actual_rp == model_rp
    sbm = coarse_bucket_alignment(
        actual_bucket,
        model_bucket,
        actual_run_pass=actual_rp,
        replay_run_pass=model_rp,
    )
    actual_struct = {
        "summary_bucket": actual_bucket,
        "actual_bucket": actual_bucket,
        "family": afam,
        "run_pass": actual_rp,
        "yards_gained": int(act.yards_gained),
        "play_type": str(act.play_type or ""),
    }
    cmp = UnifiedComparison(
        run_pass_match=rpm,
        summary_bucket_match=sbm,
        family_match=fam_m,
    )
    return cmp, actual_struct, model_struct


def _mismatch_heuristics(
    *,
    pre: Mapping[str, Any],
    comparison: UnifiedComparison,
    model_rp: Optional[str],
    actual_rp: Optional[str],
) -> Tuple[str, ...]:
    tags: List[str] = []
    try:
        dist = int(pre.get("distance", 99))
        down = int(pre.get("down", 1))
    except (TypeError, ValueError):
        dist, down = 99, 1
    short = dist <= 3 and down in (3, 4)
    if comparison.run_pass_match is False:
        if model_rp == "Pass" and actual_rp == "Run":
            if short:
                tags.append("Short yardage: model pass vs actual run")
            elif down <= 2:
                tags.append("Too aggressive — early-down pass vs run")
            else:
                tags.append("Model pass vs actual run")
        elif model_rp == "Run" and actual_rp == "Pass":
            tags.append("Model run vs actual pass")
            if down >= 3:
                tags.append("Too conservative — model run on late down")
    if comparison.summary_bucket_match is False and model_rp == actual_rp and model_rp in ("Run", "Pass"):
        tags.append("Same direction, different bucket (depth/scheme)")
    if comparison.family_match is False and comparison.run_pass_match is True:
        tags.append("Same run/pass, different scheme")
    return tuple(tags[:4])


def build_unified_rows_from_audit(
    game: Game,
    audit: Sequence[Mapping[str, Any]],
    mode: ReviewMode,
    *,
    our_coached_espn_id: str = "",
) -> List[UnifiedReviewRow]:
    """Stored timeline: Generate-time model vs linked actual."""
    rows: List[UnifiedReviewRow] = []
    for i, row in enumerate(audit):
        if not isinstance(row, dict):
            continue
        pre = _pre_snap_dict(row)
        de = int(row.get("drive_epoch", 0) or 0)
        pat = int(row.get("plays_at_recommend", 0) or 0)
        play_i = pat + 1
        act_dict = row.get("linked_actual")
        act: Optional[ActualPlayResult] = None
        if isinstance(act_dict, dict):
            try:
                act = linked_actual_to_play(act_dict)
            except (TypeError, ValueError):
                act = None
        cmp_u, actual_struct, model_struct = _comparison_for_stored(row=row, act=act, act_dict=act_dict)
        conf = _confidence_from_audit(row)

        if act is not None:
            a_head = format_actual_play_operator_headline(act)
            a_det = format_actual_play_operator_detail(act)
        else:
            a_head = "— No logged play yet"
            a_det = ""

        model_head = model_struct.get("summary_bucket") or family_display_name(model_struct.get("family"))
        fam_disp = family_display_name(model_struct.get("family"))
        play_n = str(model_struct.get("play_name") or "").strip()
        sub_parts = [x for x in (fam_disp, f"“{play_n}”" if play_n else "",) if x]
        if conf is not None:
            sub_parts.append(f"{conf:.0%} conf")
        model_sub = " · ".join(sub_parts) if sub_parts else model_head

        dr_kind = None
        if 0 <= de < len(game.drives):
            res = game.drives[de].result
            if res is not None:
                dr_kind = str(res.kind or "")

        side: Optional[str] = None
        if 0 <= de < len(game.drives):
            side = classify_drive_team_side(game.drives[de], our_coached_espn_id=our_coached_espn_id)

        tags = _mismatch_heuristics(
            pre=pre,
            comparison=cmp_u,
            model_rp=model_struct.get("run_pass"),
            actual_rp=actual_struct.get("run_pass"),
        )

        rows.append(
            UnifiedReviewRow(
                review_mode=mode,
                audit_index=i,
                drive_id=de,
                play_index_on_drive=play_i,
                team_side=side,
                pre_snap=pre,
                actual_headline=a_head,
                actual_detail=a_det,
                actual_structured=actual_struct,
                model_headline=str(model_head or "—"),
                model_subline=model_sub,
                model_structured=model_struct,
                comparison=cmp_u,
                confidence=conf,
                is_replay=False,
                is_historical=True,
                mismatch_tags=tags,
                replay_error=None,
                chain_error=None,
                drive_result_kind=dr_kind,
            )
        )
    return rows


def build_unified_rows_from_replay(
    game: Game,
    session_state: MutableMapping[str, Any],
    *,
    predictor: Any,
    ambient_ctx: Any,
    our_coached_espn_id: str = "",
) -> List[UnifiedReviewRow]:
    """
    Retroactive replay: one row per logged play on each archived drive (current engine).
    """
    if predictor is None:
        return []

    indices = filter_previous_drive_indices(
        game,
        mode=PREVIOUS_DRIVES_FILTER_BOTH,
        our_coached_espn_id=our_coached_espn_id,
    )
    rows: List[UnifiedReviewRow] = []
    for chron_i in indices:
        dr = game.drives[chron_i]
        plays = getattr(dr, "plays", None) or []
        if not plays:
            continue
        comp_rows = cached_comparison_rows_for_archived_drive(
            session_state,
            drive=dr,
            drive_index=int(chron_i),
            game=game,
            ambient_ctx=ambient_ctx,
            predictor=predictor,
            plays=plays,
        )
        side = classify_drive_team_side(dr, our_coached_espn_id=our_coached_espn_id)
        dr_kind = None
        if dr.result is not None:
            dr_kind = str(dr.result.kind or "")

        for r in comp_rows:
            rows.append(_unified_from_comparison_row(r, drive_id=chron_i, team_side=side, drive_result_kind=dr_kind))
    return rows


def _unified_from_comparison_row(
    r: ActualVsReplayComparisonRow,
    *,
    drive_id: int,
    team_side: Optional[str],
    drive_result_kind: Optional[str],
) -> UnifiedReviewRow:
    pre = _pre_from_replay_record(r.pre_snap_context)
    act: Optional[ActualPlayResult] = None
    if isinstance(r.actual_structured_result, dict):
        try:
            names = {f.name for f in fields(ActualPlayResult)}
            act = ActualPlayResult(
                **{k: v for k, v in r.actual_structured_result.items() if k in names}
            )
        except (TypeError, ValueError):
            act = None
    if act is not None:
        a_head = format_actual_play_operator_headline(act)
        a_det = format_actual_play_operator_detail(act)
    else:
        a_head = r.actual_play_summary_primary or "—"
        a_det = r.actual_play_summary_detail or ""

    m = r.model_replay_structured
    if m is not None:
        model_head = m.summary_bucket or m.run_pass or m.play_family or "—"
        sub_parts: List[str] = []
        if m.play_family:
            sub_parts.append(m.play_family.replace("_", " "))
        if m.play_call_name:
            sub_parts.append(f"“{m.play_call_name}”")
        if m.confidence is not None:
            sub_parts.append(f"{m.confidence:.0%} conf")
        model_sub = " · ".join(sub_parts) if sub_parts else model_replay_one_line(m)
        model_struct = {
            "summary_bucket": m.summary_bucket,
            "family": m.play_family,
            "play_name": m.play_call_name,
            "situation_bucket": m.bucket,
            "run_pass": m.run_pass,
            "model_name": m.model_name,
            "model_version": m.model_version,
        }
        conf = m.confidence
    else:
        model_head = r.model_replay_summary or "—"
        model_sub = r.replay_error or ""
        model_struct = {"summary_bucket": "", "family": "", "play_name": "", "run_pass": None}
        conf = None

    actual_struct = {
        "summary_bucket": r.actual_summary_bucket,
        "actual_bucket": r.actual_summary_bucket,
        "family": str(r.actual_structured_result.get("family", "") or ""),
        "run_pass": r.actual_run_pass,
        "yards_gained": r.actual_structured_result.get("yards_gained"),
    }
    cmp_u = UnifiedComparison(
        run_pass_match=r.run_pass_match,
        summary_bucket_match=r.coarse_bucket_match,
        family_match=r.family_match,
    )
    tags = _mismatch_heuristics(
        pre=pre,
        comparison=cmp_u,
        model_rp=r.model_run_pass,
        actual_rp=r.actual_run_pass,
    )
    return UnifiedReviewRow(
        review_mode=ReviewMode.REPLAY_ONLY,
        audit_index=None,
        drive_id=drive_id,
        play_index_on_drive=int(r.play_index),
        team_side=team_side,
        pre_snap=pre,
        actual_headline=a_head,
        actual_detail=a_det,
        actual_structured=actual_struct,
        model_headline=str(model_head),
        model_subline=model_sub,
        model_structured=model_struct,
        comparison=cmp_u,
        confidence=conf,
        is_replay=True,
        is_historical=False,
        mismatch_tags=tags,
        replay_error=r.replay_error,
        chain_error=r.chain_error,
        drive_result_kind=drive_result_kind,
    )


@dataclass
class ReviewRowFilter:
    drive_result_kinds: Tuple[str, ...] = ()  # e.g. touchdown, punt
    play_run_pass: Optional[str] = None  # "Run" | "Pass"
    match_only: bool = False
    mismatch_only: bool = False
    team_side: str = PREVIOUS_DRIVES_FILTER_BOTH  # our | opponent | both
    our_coached_espn_id: str = ""

    def active(self) -> bool:
        return bool(
            self.drive_result_kinds
            or self.play_run_pass
            or self.match_only
            or self.mismatch_only
            or (self.team_side != PREVIOUS_DRIVES_FILTER_BOTH)
        )


def _row_has_mismatch(row: UnifiedReviewRow) -> bool:
    c = row.comparison
    for v in (c.run_pass_match, c.summary_bucket_match, c.family_match):
        if v is False:
            return True
    return False


def _row_all_true_matches(row: UnifiedReviewRow) -> bool:
    c = row.comparison
    vals = [v for v in (c.run_pass_match, c.summary_bucket_match, c.family_match) if v is not None]
    return bool(vals) and all(v is True for v in vals)


def filter_unified_rows(rows: Sequence[UnifiedReviewRow], flt: ReviewRowFilter) -> List[UnifiedReviewRow]:
    out: List[UnifiedReviewRow] = []
    for r in rows:
        if flt.drive_result_kinds and (r.drive_result_kind or "") not in flt.drive_result_kinds:
            continue
        if flt.play_run_pass:
            arp = r.actual_structured.get("run_pass")
            if arp != flt.play_run_pass:
                continue
        if flt.team_side != PREVIOUS_DRIVES_FILTER_BOTH:
            if r.team_side is None:
                if flt.team_side != PREVIOUS_DRIVES_FILTER_BOTH:
                    continue
            elif flt.team_side == "our" and r.team_side != "our":
                continue
            elif flt.team_side == "opponent" and r.team_side != "opp":
                continue
        if flt.match_only and not _row_all_true_matches(r):
            continue
        if flt.mismatch_only and not _row_has_mismatch(r):
            continue
        out.append(r)
    return out


@dataclass
class ReviewSummaryMetrics:
    total_rows: int
    rows_with_actual: int
    drives_with_rows: int
    run_pass_match_rate: Optional[float]
    bucket_match_rate: Optional[float]
    family_match_rate: Optional[float]
    direction_match_rate: Optional[float]
    high_confidence_agreement_rate: Optional[float]


def compute_review_summary_metrics(rows: Sequence[UnifiedReviewRow]) -> ReviewSummaryMetrics:
    def _rate(getter: Any) -> Optional[float]:
        num = 0
        den = 0
        for r in rows:
            v = getter(r)
            if v is None:
                continue
            den += 1
            if v:
                num += 1
        if den == 0:
            return None
        return num / den

    with_actual = sum(1 for r in rows if r.actual_headline and "No logged play" not in r.actual_headline)
    drives_n = len({r.drive_id for r in rows})

    def _high_conf_agree() -> Optional[float]:
        num = den = 0
        for r in rows:
            if r.confidence is None or float(r.confidence) < 0.60:
                continue
            rp = r.comparison.run_pass_match
            bk = r.comparison.summary_bucket_match
            if rp is None or bk is None:
                continue
            den += 1
            if rp and bk:
                num += 1
        if den == 0:
            return None
        return num / den

    return ReviewSummaryMetrics(
        total_rows=len(rows),
        rows_with_actual=with_actual,
        drives_with_rows=drives_n,
        run_pass_match_rate=_rate(lambda r: r.comparison.run_pass_match),
        bucket_match_rate=_rate(lambda r: r.comparison.summary_bucket_match),
        family_match_rate=_rate(lambda r: r.comparison.family_match),
        direction_match_rate=_rate(lambda r: r.comparison.direction_match),
        high_confidence_agreement_rate=_high_conf_agree(),
    )


def match_strength(row: UnifiedReviewRow) -> str:
    """``strong`` | ``partial`` | ``mismatch`` | ``neutral`` for UI coloring."""
    c = row.comparison
    vals = [v for v in (c.run_pass_match, c.summary_bucket_match, c.family_match) if v is not None]
    if not vals:
        return "neutral"
    if all(v is True for v in vals):
        return "strong"
    if c.run_pass_match is False or c.family_match is False:
        return "mismatch"
    if any(v is False for v in vals):
        return "partial"
    return "partial"


def group_unified_rows_by_drive(rows: Sequence[UnifiedReviewRow]) -> Dict[int, List[UnifiedReviewRow]]:
    out: Dict[int, List[UnifiedReviewRow]] = {}
    for r in rows:
        out.setdefault(r.drive_id, []).append(r)
    for k in list(out.keys()):
        out[k] = sorted(out[k], key=lambda x: x.play_index_on_drive)
    return dict(sorted(out.items()))


def compute_quick_insights(rows: Sequence[UnifiedReviewRow]) -> List[str]:
    """Lightweight coaching bullets (no heavy analytics)."""
    insights: List[str] = []
    mod_p = act_p = 0
    mod_tot = act_tot = 0
    by_dist: Dict[str, List[bool]] = {}

    for r in rows:
        mr = r.model_structured.get("run_pass")
        ar = r.actual_structured.get("run_pass")
        if mr in ("Run", "Pass"):
            mod_tot += 1
            if mr == "Pass":
                mod_p += 1
        if ar in ("Run", "Pass"):
            act_tot += 1
            if ar == "Pass":
                act_p += 1
        pre = r.pre_snap
        try:
            d = int(pre.get("down", 0))
            dist = int(pre.get("distance", 0))
        except (TypeError, ValueError):
            d, dist = 0, 0
        label = f"{d} & {dist}" if d else "other"
        bm = r.comparison.summary_bucket_match
        if bm is not None:
            by_dist.setdefault(label, []).append(bool(bm))

    if mod_tot and act_tot:
        insights.append(
            f"Model **pass rate {100 * mod_p / mod_tot:.0f}%** vs actual **{100 * act_p / act_tot:.0f}%** (run/pass tagged plays only)."
        )

    early_mod_p = early_mod_t = early_act_p = early_act_t = 0
    for r in rows:
        pre = r.pre_snap
        try:
            d = int(pre.get("down", 0))
        except (TypeError, ValueError):
            d = 0
        if d not in (1, 2):
            continue
        mr = r.model_structured.get("run_pass")
        ar = r.actual_structured.get("run_pass")
        if mr in ("Run", "Pass"):
            early_mod_t += 1
            if mr == "Pass":
                early_mod_p += 1
        if ar in ("Run", "Pass"):
            early_act_t += 1
            if ar == "Pass":
                early_act_p += 1
    if early_mod_t >= 3 and early_act_t >= 3:
        mp = early_mod_p / early_mod_t
        ap = early_act_p / early_act_t
        if mp - ap >= 0.12:
            insights.append("**Early downs (1st–2nd):** model **over-passed** vs actual tagged run/pass.")
        elif ap - mp >= 0.12:
            insights.append("**Early downs:** actual was **more pass-heavy** than the model.")

    best = worst = None
    best_r = -1.0
    worst_r = 2.0
    for label, bits in by_dist.items():
        if len(bits) < 2:
            continue
        rate = sum(bits) / len(bits)
        if rate > best_r:
            best_r, best = rate, label
        if rate < worst_r:
            worst_r, worst = rate, label

    if best is not None and best_r >= 0:
        insights.append(
            f"**Best bucket match:** {best} (~{100 * best_r:.0f}% on {len(by_dist.get(best, []))} snap(s))."
        )
    if worst is not None and worst != best and worst_r <= 1:
        insights.append(f"**Tough spot:** {worst} (~{100 * worst_r:.0f}% bucket match).")

    return insights[:6]

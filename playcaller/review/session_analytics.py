"""
Football-oriented aggregates for Review Session (pattern + model diagnostics).

Pure functions — safe for unit tests; no Streamlit imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from playcaller.history.normalize import derive_field_zone
from playcaller.play_event_segment import PlayEventSegment
from playcaller.review.unified_review import UnifiedReviewRow, high_confidence_full_agreement_counts


def _rp(row: UnifiedReviewRow, side: str) -> Optional[str]:
    d = row.model_structured if side == "model" else row.actual_structured
    v = d.get("run_pass")
    if v in ("Run", "Pass"):
        return str(v)
    return None


def _down_dist(pre: Mapping[str, Any]) -> Tuple[int, int]:
    try:
        d = int(pre.get("down", 0) or 0)
    except (TypeError, ValueError):
        d = 0
    try:
        dist = int(pre.get("distance", 0) or 0)
    except (TypeError, ValueError):
        dist = 0
    return d, dist


def _is_red_zone_pre(pre: Mapping[str, Any]) -> bool:
    if str(pre.get("territory")) != "opponents":
        return False
    try:
        yl = int(pre.get("yardline", 99))
    except (TypeError, ValueError):
        return False
    z = derive_field_zone(territory="opponents", yardline=yl)
    return z == "red_zone" or yl <= 20


def _distance_bucket(dist: int) -> str:
    if dist <= 3:
        return "Short (1–3)"
    if dist <= 6:
        return "Medium (4–6)"
    return "Long (7+)"


@dataclass
class RunPassRates:
    n: int
    pass_n: int

    @property
    def pass_rate(self) -> Optional[float]:
        if self.n <= 0:
            return None
        return self.pass_n / self.n


@dataclass
class PatternAnalysisReport:
    """Tendency breakdowns from unified review rows (pre_snap + tagged run/pass)."""

    by_down: Dict[int, Tuple[RunPassRates, RunPassRates]]  # down -> (model, actual)
    by_dist_bucket: Dict[str, Tuple[RunPassRates, RunPassRates]]
    red_zone: Tuple[RunPassRates, RunPassRates]
    early_down: Tuple[RunPassRates, RunPassRates]  # 1–2
    late_down: Tuple[RunPassRates, RunPassRates]  # 3–4
    sample_warnings: Tuple[str, ...] = ()


def build_pattern_analysis(rows: Sequence[UnifiedReviewRow]) -> PatternAnalysisReport:
    st_excl = sum(1 for r in rows if r.event_segment != PlayEventSegment.OFFENSE)
    rows = tuple(r for r in rows if r.event_segment == PlayEventSegment.OFFENSE)

    by_down: Dict[int, Tuple[List[int], List[int]]] = {i: ([], []) for i in range(1, 5)}
    dist_bins: Dict[str, Tuple[List[int], List[int]]] = {}
    rz_m: List[int] = []
    rz_a: List[int] = []
    early_m: List[int] = []
    early_a: List[int] = []
    late_m: List[int] = []
    late_a: List[int] = []

    warnings: List[str] = []
    if st_excl:
        warnings.append(
            f"Excluded **{st_excl}** special-teams / non-offense event(s) from run-pass tendency slices."
        )
    n_tagged = 0
    for r in rows:
        m = _rp(r, "model")
        a = _rp(r, "actual")
        if m in ("Run", "Pass") or a in ("Run", "Pass"):
            n_tagged += 1
        pre = r.pre_snap
        d, dist = _down_dist(pre)
        if 1 <= d <= 4:
            mp, ap = by_down[d]
            if m in ("Run", "Pass"):
                mp.append(1 if m == "Pass" else 0)
            if a in ("Run", "Pass"):
                ap.append(1 if a == "Pass" else 0)
        dist_for_bucket = dist if dist > 0 else 1
        bk = _distance_bucket(dist_for_bucket)
        db_m, db_a = dist_bins.setdefault(bk, ([], []))
        if m in ("Run", "Pass"):
            db_m.append(1 if m == "Pass" else 0)
        if a in ("Run", "Pass"):
            db_a.append(1 if a == "Pass" else 0)

        if _is_red_zone_pre(pre):
            if m in ("Run", "Pass"):
                rz_m.append(1 if m == "Pass" else 0)
            if a in ("Run", "Pass"):
                rz_a.append(1 if a == "Pass" else 0)

        if d in (1, 2):
            if m in ("Run", "Pass"):
                early_m.append(1 if m == "Pass" else 0)
            if a in ("Run", "Pass"):
                early_a.append(1 if a == "Pass" else 0)
        elif d in (3, 4):
            if m in ("Run", "Pass"):
                late_m.append(1 if m == "Pass" else 0)
            if a in ("Run", "Pass"):
                late_a.append(1 if a == "Pass" else 0)

    if n_tagged < 5:
        warnings.append(
            f"Thin sample: only **{n_tagged}** snap(s) with at least one run/pass tag (model or actual) — treat rates as directional."
        )

    def _rr(bits: List[int]) -> RunPassRates:
        n = len(bits)
        return RunPassRates(n=n, pass_n=sum(bits))

    def _pair(mbits: List[int], abits: List[int]) -> Tuple[RunPassRates, RunPassRates]:
        return _rr(mbits), _rr(abits)

    down_out: Dict[int, Tuple[RunPassRates, RunPassRates]] = {}
    for d in range(1, 5):
        down_out[d] = _pair(by_down[d][0], by_down[d][1])

    dist_out: Dict[str, Tuple[RunPassRates, RunPassRates]] = {}
    for bk in ("Short (1–3)", "Medium (4–6)", "Long (7+)"):
        if bk in dist_bins:
            dist_out[bk] = _pair(dist_bins[bk][0], dist_bins[bk][1])

    return PatternAnalysisReport(
        by_down=down_out,
        by_dist_bucket=dist_out,
        red_zone=_pair(rz_m, rz_a),
        early_down=_pair(early_m, early_a),
        late_down=_pair(late_m, late_a),
        sample_warnings=tuple(warnings),
    )


def _fmt_rate(rr: RunPassRates) -> str:
    if rr.n <= 0:
        return "— (n=0)"
    pr = rr.pass_rate
    assert pr is not None
    return f"{100 * pr:.0f}% pass (n={rr.n})"


def pattern_analysis_markdown_lines(report: PatternAnalysisReport) -> List[str]:
    """Readable markdown chunks for Streamlit (section headers + bullets)."""
    lines: List[str] = []
    lines.append("_Offensive scrimmage snaps only — kickoffs, punts, FG/PAT, and other non-offense events are excluded._")
    for w in report.sample_warnings:
        lines.append(f"- {w}")
    lines.append("##### Run / pass mix by down")
    lines.append("_Tagged run/pass on model & actual only._")
    for d in range(1, 5):
        mr, ar = report.by_down[d]
        lines.append(
            f"- **{d}{'st' if d == 1 else 'nd' if d == 2 else 'rd' if d == 3 else 'th'}:** "
            f"model {_fmt_rate(mr)} · actual {_fmt_rate(ar)}"
        )
    lines.append("##### Distance bucket (pre-snap distance)")
    for label in ("Short (1–3)", "Medium (4–6)", "Long (7+)"):
        if label not in report.by_dist_bucket:
            continue
        mr, ar = report.by_dist_bucket[label]
        lines.append(f"- **{label}:** model {_fmt_rate(mr)} · actual {_fmt_rate(ar)}")
    rz_m, rz_a = report.red_zone
    lines.append("##### Situational slices")
    lines.append(
        f"- **Red zone:** model {_fmt_rate(rz_m)} · actual {_fmt_rate(rz_a)} "
        f"_(opp territory, ≤20 yd line / red-zone)_"
    )
    em, ea = report.early_down
    lm, la = report.late_down
    lines.append(f"- **Early downs (1st–2nd):** model {_fmt_rate(em)} · actual {_fmt_rate(ea)}")
    lines.append(f"- **Late downs (3rd–4th):** model {_fmt_rate(lm)} · actual {_fmt_rate(la)}")
    return lines


@dataclass
class ModelDiagnosticsReport:
    n_with_confidence: int
    mean_confidence: Optional[float]
    high_conf_mismatch: int
    high_conf_total: int
    by_drive_agreement: Dict[int, Tuple[int, int]]  # drive_id -> (agree, compared) on run_pass+bucket both scorable
    replay_rows: int
    stored_rows: int
    notes: Tuple[str, ...] = field(default_factory=tuple)


def build_model_diagnostics(rows: Sequence[UnifiedReviewRow]) -> ModelDiagnosticsReport:
    confs: List[float] = []
    high_agree, high_tot = high_confidence_full_agreement_counts(rows)
    high_mis = high_tot - high_agree
    by_drive: Dict[int, List[Tuple[Optional[bool], Optional[bool]]]] = {}
    replay_n = stored_n = 0
    for r in rows:
        if r.is_replay:
            replay_n += 1
        if r.is_historical:
            stored_n += 1
        if r.event_segment != PlayEventSegment.OFFENSE:
            continue
        if r.confidence is not None:
            try:
                confs.append(float(r.confidence))
            except (TypeError, ValueError):
                pass
        rp = r.comparison.run_pass_match
        bk = r.comparison.summary_bucket_match
        dkey = int(r.drive_id)
        by_drive.setdefault(dkey, []).append((rp, bk))

    mean_c: Optional[float] = None
    if confs:
        mean_c = sum(confs) / len(confs)

    drive_agree: Dict[int, Tuple[int, int]] = {}
    for did, pairs in by_drive.items():
        agree = 0
        tot = 0
        for rp, bk in pairs:
            if rp is None or bk is None:
                continue
            tot += 1
            if rp and bk:
                agree += 1
        if tot:
            drive_agree[did] = (agree, tot)

    notes: List[str] = []
    if replay_n and stored_n:
        notes.append("Mix of replay and stored rows is unusual for one view — confirm Review mode banner.")
    if not confs:
        notes.append("No confidence values on rows — diagnostics are agreement-only.")
    notes.append("Drive agreement stats use **offensive scrimmage snaps only** (special teams excluded).")

    return ModelDiagnosticsReport(
        n_with_confidence=len(confs),
        mean_confidence=mean_c,
        high_conf_mismatch=high_mis,
        high_conf_total=high_tot,
        by_drive_agreement=drive_agree,
        replay_rows=replay_n,
        stored_rows=stored_n,
        notes=tuple(notes),
    )


def model_diagnostics_markdown_lines(rep: ModelDiagnosticsReport) -> List[str]:
    lines: List[str] = []
    lines.append("##### Confidence & alignment")
    for n in rep.notes:
        lines.append(f"- {n}")
    if rep.mean_confidence is not None:
        lines.append(
            f"- **Mean confidence** (where present): **{100 * rep.mean_confidence:.0f}%** "
            f"over **{rep.n_with_confidence}** row(s)."
        )
    if rep.high_conf_total:
        pct = 100 * (1 - rep.high_conf_mismatch / rep.high_conf_total)
        lines.append(
            f"- **High-confidence full agreement** (≥60% conf, run/pass & bucket both scored): "
            f"**{rep.high_conf_total - rep.high_conf_mismatch}/{rep.high_conf_total}** "
            f"({pct:.0f}% — misses may mean context shift, label noise, or replay drift)."
        )
    if rep.by_drive_agreement:
        lines.append("##### By drive (full agreement when both scores exist)")
        for did in sorted(rep.by_drive_agreement.keys()):
            a, t = rep.by_drive_agreement[did]
            lines.append(f"- Drive **{did}:** **{a}/{t}** snaps aligned on run/pass + bucket")
    return lines

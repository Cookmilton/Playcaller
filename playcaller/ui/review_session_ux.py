"""
Warehouse-historical Review Session UX: pure helpers (no Streamlit in top section)
and Streamlit renderers in the lower section.

Gated on :class:`~playcaller.review.unified_review.ReviewMode.WAREHOUSE_HISTORICAL` only.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import List, Set, Tuple

import streamlit as st

from playcaller.drive_audit_report import DriveAuditReport, score_reconciliation_summary_lines
from playcaller.domain import ActualPlayResult
from playcaller.game import (
    DRIVE_END_TURNOVER_FUMBLE,
    DRIVE_END_TURNOVER_INT,
    DRIVE_END_TURNOVER_ON_DOWNS,
    Drive,
    Game,
)
from playcaller.implied_scoring import (
    implied_totals_and_breakdown_from_warehouse_plays,
    warehouse_possession_one_team_only_warning,
    warehouse_session_points_for_play,
)
from playcaller.reconciliation.drive_reconciler import ReconciledDrive, reconcile_drive
from playcaller.review.unified_review import ReviewMode
from playcaller.review_insights.timeline import (
    GameFlowBundle,
    build_game_flow,
    game_flow_section_html,
)
from playcaller.ui.previous_drives_render import render_drive_score_ribbon
from warehouse.review_loader import (
    WAREHOUSE_AUDIT_META_OUTLIER_FLAGS,
    WAREHOUSE_AUDIT_META_QUALITY_ISSUES,
    WAREHOUSE_AUDIT_META_REQUIRED_FIELD_GAP_PCT,
    WAREHOUSE_AUDIT_META_VALIDATION_ISSUES,
)

# =============================================================================
# Pure: mode
# =============================================================================


def is_warehouse_historical(mode: ReviewMode) -> bool:
    return mode is ReviewMode.WAREHOUSE_HISTORICAL


# =============================================================================
# Pure: §10.1 – §10.6
# =============================================================================


def reliability_label(
    *,
    validation_issues: int,
    quality_issues: int,
    outlier_flags: int,
    required_field_gap_pct: float,
    score_gap: int | None,
    drive_coverage_ok: bool,
) -> str:
    if (
        not drive_coverage_ok
        or (score_gap is not None and score_gap >= 5)
        or required_field_gap_pct >= 5.0
        or (validation_issues + quality_issues + outlier_flags) >= 5
    ):
        return "Low confidence"
    if (
        (score_gap is not None and 2 <= score_gap <= 4)
        or (1.0 <= required_field_gap_pct < 5.0)
        or (1 <= (validation_issues + quality_issues + outlier_flags) <= 4)
    ):
        return "Caution"
    return "Healthy"


def score_confidence(
    *,
    actual_home: int | None,
    actual_away: int | None,
    implied_home: int,
    implied_away: int,
) -> tuple[str, int | None, str]:
    if actual_home is None or actual_away is None:
        return ("Unknown", None, "Final score not available; cannot reconcile.")
    gap_home = abs(implied_home - int(actual_home))
    gap_away = abs(implied_away - int(actual_away))
    max_gap = max(gap_home, gap_away)
    if max_gap <= 1:
        return (
            "High",
            max_gap,
            f"Reconstructed score matches scoreboard within {max_gap} point(s) per team.",
        )
    if 2 <= max_gap <= 4:
        return (
            "Medium",
            max_gap,
            f"Reconstructed score is off by up to {max_gap} points on at least one team. Some scoring plays may be misclassified.",
        )
    return (
        "Low",
        max_gap,
        f"Reconstructed score is off by {max_gap} points on at least one team. Treat scoring breakdowns with caution.",
    )


def team_label_mode(*, mode: str, coached_team_set: bool) -> str:
    if mode == "warehouse_historical" and not coached_team_set:
        return "home_away"
    return "us_them"


def _play_q(p: ActualPlayResult) -> int:
    v = p.feed_period_number
    return int(v) if v is not None and int(v) > 0 else 0


def _max_q_dr(dr: Drive) -> int:
    return max((_play_q(p) for p in dr.plays), default=0)


def _min_q_first(dr: Drive) -> int:
    if not dr.plays:
        return 0
    return _play_q(dr.plays[0])


def _last_before_halftime_set(game: Game) -> set[int]:
    dvs, n, out = game.drives, len(game.drives), set()
    for i in range(1, n):
        if _min_q_first(dvs[i]) >= 3 and _max_q_dr(dvs[i - 1]) <= 2:
            out.add(i - 1)
    if not out and n:
        for i in range(n - 1, -1, -1):
            if 1 <= _max_q_dr(dvs[i]) <= 2:
                out.add(i)
                break
    return out


def _last_regulation_index(game: Game) -> int | None:
    for i, dr in enumerate(game.drives):
        if not dr.plays:
            continue
        if _min_q_first(dr) >= 5:
            return (i - 1) if i > 0 else None
    return None


def _is_scoring(rec: ReconciledDrive) -> bool:
    return int(rec.possession_points) > 0


def _is_to(rec: ReconciledDrive) -> bool:
    return rec.outcome_kind in (
        DRIVE_END_TURNOVER_INT,
        DRIVE_END_TURNOVER_FUMBLE,
        DRIVE_END_TURNOVER_ON_DOWNS,
    )


def _is_exp(dr: Drive) -> bool:
    return any(int(getattr(p, "yards_gained", 0) or 0) >= 20 for p in dr.plays)


def _tag_rank(
    i: int,
    rec: ReconciledDrive,
    dr: Drive,
    outlier_game: bool,
    p95: int,
) -> int:
    if _is_scoring(rec):
        return 0
    if _is_to(rec):
        return 1
    if _is_exp(dr):
        return 2
    if outlier_game and (
        _is_scoring(rec) or _is_to(rec) or _is_exp(dr) or len(dr.plays) >= p95
    ):
        return 3
    return 4


def select_key_drives(
    game: Game,
    *,
    outlier_game_flag: bool = False,
    p95_play_count: int | None = None,
) -> List[int]:
    n = len(game.drives)
    if n == 0:
        return []
    p95 = p95_play_count if p95_play_count is not None else 12
    recs = [reconcile_drive(d, espn=d.feed_audit) for d in game.drives]
    half = _last_before_halftime_set(game)
    reg = _last_regulation_index(game)
    must: set[int] = {n - 1} | set(half)
    if reg is not None and reg != n - 1:
        must.add(reg)
    key: set[int] = set(must)
    for i, dr in enumerate(game.drives):
        r = recs[i]
        if _is_scoring(r) or _is_to(r) or _is_exp(dr):
            key.add(i)
        if outlier_game_flag and (
            _is_scoring(r) or _is_to(r) or _is_exp(dr) or len(dr.plays) >= p95
        ):
            key.add(i)
    if not key:
        return list(range(n))
    if len(key) <= 15:
        return sorted(key)
    if len(must) >= 15:
        return sorted(must)[:15]
    res: set[int] = set(must)
    others = [i for i in key if i not in must]
    others.sort(
        key=lambda i: (_tag_rank(i, recs[i], game.drives[i], outlier_game_flag, p95), i)
    )
    for i in others:
        if len(res) >= 15:
            break
        res.add(i)
    if len(res) < 15:
        for i in sorted(key):
            if i not in res and len(res) < 15:
                res.add(i)
    return sorted(res)[:15]


@dataclass(frozen=True)
class _Ins:
    text: str
    pr: int


def _margins_after_drives(game: Game) -> List[int]:
    meta = game.session_metadata or {}
    h = str(meta.get("warehouse_home_team") or "").strip()
    a = str(meta.get("warehouse_away_team") or "").strip()
    hp = ap = 0
    out: list[int] = []
    prev: ActualPlayResult | None = None
    if h and a:
        for dr in game.drives:
            for p in dr.plays:
                oh, oa, _, _, _ = warehouse_session_points_for_play(
                    p, prev, game, home_team=h, away_team=a
                )
                hp += oh
                ap += oa
                prev = p
            out.append(hp - ap)
    else:
        for dr in game.drives:
            r = reconcile_drive(dr, espn=dr.feed_audit)
            pts = int(r.possession_points)
            ab = str(getattr(dr, "feed_team_abbr", "") or "")
            if pts:
                if ab == h or (not a and dr.possessing_team == "offense"):
                    hp += pts
                else:
                    ap += pts
            out.append(hp - ap)
    return out if out else [0]


def _largest_swing(game: Game) -> _Ins | None:
    m = _margins_after_drives(game)
    if len(m) < 2:
        return None
    best_d, best_i = 0, 0
    for i in range(1, len(m)):
        d = abs(m[i] - m[i - 1])
        if d > best_d:
            best_d, best_i = d, i
    if best_d == 0:
        return None
    dr = game.drives[best_i]
    pts = int(reconcile_drive(dr, espn=dr.feed_audit).possession_points)
    if pts <= 0:
        return None
    ab = str(getattr(dr, "feed_team_abbr", "") or "Team")
    np = max(1, len(dr.plays))
    return _Ins(
        f"{ab} netted the biggest swing in margin (+{best_d} points) on a {np}-play drive ({pts} pts).",
        2,
    )


def _drought(game: Game) -> _Ins | None:
    if not game.drives:
        return None
    recs = [reconcile_drive(d, espn=d.feed_audit) for d in game.drives]
    run = best = 0
    for r in recs:
        if _is_scoring(r):
            run = 0
        else:
            run += 1
            best = max(best, run)
    if best < 4:
        return None
    return _Ins(f"Neither team scored across {best} consecutive drives.", 3)


def _explosive(game: Game) -> _Ins | None:
    by, ptyp, ab = 0, "play", "Team"
    for dr in game.drives:
        a = str(getattr(dr, "feed_team_abbr", "") or "Team")
        for p in dr.plays:
            y = int(getattr(p, "yards_gained", 0) or 0)
            if y > by:
                by, ptyp, ab = y, str(getattr(p, "play_type", "") or "play"), a
    if by < 20:
        return None
    return _Ins(f"{ab}'s longest play: {by}-yard {ptyp}.", 4)


def _turnovers(game: Game) -> _Ins | None:
    meta = game.session_metadata or {}
    h, w = str(meta.get("warehouse_home_team") or ""), str(meta.get("warehouse_away_team") or "")
    t = th = ta = 0
    for dr in game.drives:
        r = reconcile_drive(dr, espn=dr.feed_audit)
        if not _is_to(r):
            continue
        t += 1
        ab = str(getattr(dr, "feed_team_abbr", "") or "")
        if h and ab == h:
            th += 1
        elif w and ab == w:
            ta += 1
    if t < 1:
        return None
    return _Ins(f"{t} turnover(s) ({th} on home, {ta} on away).", 5)


def rank_insights(
    game: Game,
    *,
    reliability: str,
    score_label: str,
    max_score_gap: int | None = None,
    validation_issue_ct: int = 0,
    quality_issue_ct: int = 0,
    outlier_issue_ct: int = 0,
) -> List[str]:
    out: list[_Ins] = []
    show_audit_line = (
        reliability != "Healthy" or score_label != "High" or outlier_issue_ct > 0
    )
    if show_audit_line:
        g = max_score_gap if max_score_gap is not None else 0
        vq = f"{validation_issue_ct} validation / {quality_issue_ct} quality"
        if outlier_issue_ct > 0:
            vq += f" · **{outlier_issue_ct} critical validation**"
        out.append(
            _Ins(
                f"Data read: **{reliability}** · {vq}; "
                f"score check **{score_label}** (max gap {g}).",
                1,
            )
        )
    o2, o3, o4, o5 = _largest_swing(game), _drought(game), _explosive(game), _turnovers(game)
    for o in (o2, o3, o4, o5):
        if o is not None:
            out.append(o)
    out.sort(key=lambda x: x.pr)
    seen: set[str] = set()
    fin: list[str] = []
    for o in out:
        if o.text in seen:
            continue
        seen.add(o.text)
        fin.append(o.text)
        if len(fin) >= 3:
            break
    return fin


# --- §10.6 compact labels (display only) ---

_KNOWN_END: dict[str, str] = {
    "punt": "Punt",
    "touchdown": "Touchdown",
    "field_goal": "Field goal",
    "field_goal_miss": "Field goal",
    "turnover_interception": "Turnover (interception)",
    "turnover_fumble": "Turnover (fumble)",
    "turnover_on_downs": "Turnover on downs",
    "unknown": "Drive ended",
}


def compact_drive_label(drive: Drive) -> str:
    k = (drive.result.kind if drive.result else "") or ""
    low = k.lower()
    if low in _KNOWN_END and low != "unknown":
        return _KNOWN_END[low]
    h = (drive.result.headline if drive.result else "") or ""
    if h.strip() and h.lower() in ("drive ended", "unknown", "—"):
        return "Drive ended"
    if k and low not in _KNOWN_END and k not in _KNOWN_END:
        return "Drive ended"
    if h.strip() and h.lower() not in ("drive ended", "unknown", "—", ""):
        return h
    if k and k in _KNOWN_END:
        return _KNOWN_END[k]
    return "Drive ended"


def compact_play_label(
    play: ActualPlayResult,
    *,
    structured_play_type: str = "",
) -> str:
    pt = (structured_play_type or play.play_type or "").strip()
    if pt and pt.lower() not in ("unknown", ""):
        return pt.replace("_", " ").title()
    d = (play.description or "").strip()
    if d:
        return d[:80]
    return "Unknown"


def play_display_line_for_warehouse(
    game: Game,
    drive_id: int,
    play_index: int,
    default_headline: str,
) -> str:
    if not (0 <= drive_id < len(game.drives)):
        return default_headline
    dr = game.drives[drive_id]
    pidx = int(play_index) - 1
    if 0 <= pidx < len(dr.plays):
        p = dr.plays[pidx]
        if (default_headline or "").strip().lower() in ("unknown", "—", ""):
            return compact_play_label(p, structured_play_type=p.play_type)
    return default_headline


# =============================================================================
# Reliability + score context from a loaded Game (no I/O)
# =============================================================================


def score_gap_for_game(game: Game) -> int | None:
    meta = game.session_metadata or {}
    if not bool(meta.get("warehouse_processed")):
        return None
    ih, ia, _ = implied_totals_and_breakdown_from_warehouse_plays(game)
    ah, aa = int(game.offense_points), int(game.defense_points)
    return max(abs(ih - ah), abs(ia - aa))


def _meta_int(meta: dict[str, object], key: str) -> int | None:
    raw = meta.get(key)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _meta_float(meta: dict[str, object], key: str) -> float | None:
    raw = meta.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def compute_reliability_context(
    game: Game,
    *,
    validation_issues: int | None = None,
    quality_issues: int | None = None,
    outlier_flags: int | None = None,
    required_field_gap_pct: float | None = None,
) -> tuple[str, bool, int | None]:
    """Returns (reliability_label, drive_coverage_ok, score_gap).

    For ``warehouse_processed`` games loaded via :func:`warehouse.review_loader.build_playcaller_game_from_warehouse`,
    validation / quality / outlier counts and required-field gap are read from ``session_metadata`` unless
    overridden by explicit keyword arguments.
    """
    warn = warehouse_possession_one_team_only_warning(game)
    cov = warn is None
    meta = game.session_metadata or {}
    wh = bool(meta.get("warehouse_processed"))

    def _ival(param: int | None, key: str, default: int = 0) -> int:
        if param is not None:
            return int(param)
        if wh:
            m = _meta_int(meta, key)
            if m is not None:
                return m
        return default

    def _fval(param: float | None, key: str, default: float = 0.0) -> float:
        if param is not None:
            return float(param)
        if wh:
            m = _meta_float(meta, key)
            if m is not None:
                return m
        return default

    v_issues = _ival(validation_issues, WAREHOUSE_AUDIT_META_VALIDATION_ISSUES)
    q_issues = _ival(quality_issues, WAREHOUSE_AUDIT_META_QUALITY_ISSUES)
    o_flags = _ival(outlier_flags, WAREHOUSE_AUDIT_META_OUTLIER_FLAGS)
    gap_pct = _fval(required_field_gap_pct, WAREHOUSE_AUDIT_META_REQUIRED_FIELD_GAP_PCT)

    if wh:
        ih, ia, _ = implied_totals_and_breakdown_from_warehouse_plays(game)
    else:
        ih = ia = 0
    gap: int | None
    if wh:
        gap = max(abs(ih - int(game.offense_points)), abs(ia - int(game.defense_points)))
    else:
        gap = None
    lab = reliability_label(
        validation_issues=v_issues,
        quality_issues=q_issues,
        outlier_flags=o_flags,
        required_field_gap_pct=gap_pct,
        score_gap=gap,
        drive_coverage_ok=cov,
    )
    return lab, cov, gap


# =============================================================================
# Game flow: subset bundle (warehouse compact view)
# =============================================================================


def game_flow_bundle_for_drive_subset(bundle: GameFlowBundle, one_based: Set[int]) -> GameFlowBundle:
    rows = tuple(r for r in bundle.rows if r.drive_number in one_based)
    return GameFlowBundle(
        rows=rows,
        scoring_runs=(),
        droughts=(),
        turning_points=(),
        momentum_suppressed=True,
    )


# =============================================================================
# Streamlit (import streamlit only below pure helpers; kept in same file per spec)
# =============================================================================


def _warehouse_home_away_legend(game: Game) -> tuple[str, str]:
    m = game.session_metadata or {}
    h = str(m.get("warehouse_home_team") or "Home")
    a = str(m.get("warehouse_away_team") or "Away")
    return f"Home ({h})", f"Away ({a})"


def render_summary_header(game: Game, report: DriveAuditReport, *, mode: ReviewMode) -> None:
    if not is_warehouse_historical(mode):
        return
    m = game.session_metadata or {}
    h, a = str(m.get("warehouse_home_team") or "?"), str(m.get("warehouse_away_team") or "?")
    nplays = sum(len(d.plays) for d in game.drives)
    ndr = len(game.drives)
    rel, _, _ = compute_reliability_context(game)
    st.markdown("#### Game summary (warehouse)")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Matchup", f"{a} @ {h}"[:64])
    c2.metric("Final (session board)", f"{int(game.offense_points)} – {int(game.defense_points)}")
    c3.metric("Drives", ndr)
    c4.metric("Plays (logged)", nplays)
    c5.metric("Data reliability", rel)
    st.caption(
        "Source: **processed JSON** (warehouse) — reconstructed scoring is compared to the session board in the panel below."
    )


def render_score_confidence_panel(
    game: Game,
    report: DriveAuditReport,
    *,
    mode: ReviewMode,
) -> None:
    if not is_warehouse_historical(mode):
        return
    ih, ia, _ = implied_totals_and_breakdown_from_warehouse_plays(game)
    ah, aa = int(game.offense_points), int(game.defense_points)
    label, max_gap, expl = score_confidence(
        actual_home=ah,
        actual_away=aa,
        implied_home=ih,
        implied_away=ia,
    )
    if label == "High":
        st.success(f"**Score confidence: {label}** — {expl}")
    elif label in ("Medium", "Unknown"):
        st.warning(f"**Score confidence: {label}** — {expl}")
    else:
        st.error(f"**Score confidence: {label}** — {expl}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Session board (home / away)", f"{ah} – {aa}")
    c2.metric("Reconstructed (plays)", f"{ih} – {ia}")
    if max_gap is not None:
        c3.metric("Largest per-team gap", f"{max_gap} pt")
    else:
        c3.metric("Largest per-team gap", "—")
    st.caption("_Model note (warehouse):_ play-level TD=6 + PAT/2PT/FG; see details below.")
    with st.expander("Show reconciliation details", expanded=False):
        for line in score_reconciliation_summary_lines(game, report):
            st.markdown(f"- {line}")


def render_warehouse_score_ribbon(report: DriveAuditReport, game: Game, *, mode: ReviewMode) -> None:
    if not is_warehouse_historical(mode):
        return
    render_drive_score_ribbon(
        report,
        trace_names=_warehouse_home_away_legend(game),
        unavailable_message="**Score progression unavailable** — check feed / cumulative scores.",
    )


def render_top_insights(game: Game, *, mode: ReviewMode) -> None:
    if not is_warehouse_historical(mode):
        return
    rel, _, _ = compute_reliability_context(game)
    ih, ia, _ = implied_totals_and_breakdown_from_warehouse_plays(game)
    ah, aa = int(game.offense_points), int(game.defense_points)
    sl, max_gap, _ = score_confidence(
        actual_home=ah, actual_away=aa, implied_home=ih, implied_away=ia
    )
    m = game.session_metadata or {}
    v_ct = int(m.get(WAREHOUSE_AUDIT_META_VALIDATION_ISSUES) or 0)
    q_ct = int(m.get(WAREHOUSE_AUDIT_META_QUALITY_ISSUES) or 0)
    o_ct = int(m.get(WAREHOUSE_AUDIT_META_OUTLIER_FLAGS) or 0)
    lines = rank_insights(
        game,
        reliability=rel,
        score_label=sl,
        max_score_gap=max_gap,
        validation_issue_ct=v_ct,
        quality_issue_ct=q_ct,
        outlier_issue_ct=o_ct,
    )
    if not lines:
        return
    st.markdown("#### Game story")
    for line in lines:
        st.markdown(f"- {html.escape(line)}")


def render_compact_game_flow(
    game: Game,
    *,
    mode: ReviewMode,
    our_coached_espn_id: str,
) -> None:
    if not is_warehouse_historical(mode):
        return
    if not game.drives:
        return
    bundle = build_game_flow(game, our_coached_espn_id=our_coached_espn_id)
    key0 = select_key_drives(game)
    key1 = {i + 1 for i in key0}
    sub = game_flow_bundle_for_drive_subset(bundle, key1)
    total, shown = len(game.drives), len(key0)
    hidden = max(0, total - shown)
    st.markdown("### Game flow (key drives)")
    st.caption("Highlights: scoring, turnovers, explosive plays, and end-of-half / regulation markers.")
    st.markdown(game_flow_section_html(game, sub, our_coached_espn_id=our_coached_espn_id), unsafe_allow_html=True)
    with st.expander(f"Show all drives ({total} total, {hidden} hidden as routine)", expanded=False):
        st.caption("Full drive list (same as before this view).")
        st.markdown(game_flow_section_html(game, bundle, our_coached_espn_id=our_coached_espn_id), unsafe_allow_html=True)
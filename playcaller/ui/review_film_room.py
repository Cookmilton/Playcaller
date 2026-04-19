"""Film-room style Review Session layout (dual-mode unified rows)."""

from __future__ import annotations

import html
from typing import Optional, Sequence, Tuple

import streamlit as st

from playcaller.game import Game
from playcaller.live_data.drive_display import (
    PREVIOUS_DRIVES_FILTER_BOTH,
    PREVIOUS_DRIVES_FILTER_OPPONENT,
    PREVIOUS_DRIVES_FILTER_OUR,
    chronological_team_drive_indices,
    prior_drive_heading,
)
from playcaller.review.unified_review import (
    ReviewMode,
    ReviewRowFilter,
    ReviewSummaryMetrics,
    UnifiedComparison,
    UnifiedReviewRow,
    compute_quick_insights,
    compute_review_summary_metrics,
    filter_unified_rows,
    group_unified_rows_by_drive,
    match_strength,
)
from playcaller.review.derived import format_field_position_sentence, format_situation_line
from playcaller.streamlit_state.session import coached_team_espn_id_for_previous_drives
from playcaller.ui.product_copy import (
    REVIEW_MESSAGE_REPLAY,
    REVIEW_MESSAGE_STORED,
    REVIEW_MODE_LABEL_LEGACY,
    REVIEW_MODE_LABEL_TRUE,
    REVIEW_SECTION_FILM_ROOM,
)


def _pct(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return f"{int(round(100 * float(x)))}%"


def _border_color(strength: str) -> str:
    return {
        "strong": "#22c55e",
        "partial": "#eab308",
        "mismatch": "#ef4444",
        "neutral": "#475569",
    }.get(strength, "#475569")


def _comparison_line(c: UnifiedComparison, *, show_labels: bool) -> str:
    def _one(name: str, v: Optional[bool]) -> str:
        if v is True:
            word = "match"
        elif v is False:
            word = "miss"
        else:
            word = "n/a"
        return f"{name}: {word}" if show_labels else word

    parts = [
        _one("Run/pass", c.run_pass_match),
        _one("Bucket", c.summary_bucket_match),
        _one("Family", c.family_match),
    ]
    return " · ".join(parts)


def _comparison_strip_html(c: UnifiedComparison) -> str:
    """Green / red / gray strip for film-room cards (fixed English labels — safe HTML)."""

    def cell(label: str, v: Optional[bool]) -> str:
        if v is True:
            g = '<span style="color:#4ade80;font-weight:600">✓</span>'
        elif v is False:
            g = '<span style="color:#f87171;font-weight:600">✗</span>'
        else:
            g = '<span style="color:#64748b">—</span>'
        return f"{label}: {g}"

    return " · ".join(
        [
            cell("Run/pass", c.run_pass_match),
            cell("Bucket", c.summary_bucket_match),
            cell("Family", c.family_match),
        ]
    )


def _breakdown_markdown(row: UnifiedReviewRow) -> str:
    d = row.breakdown_dict()
    lines = []
    for k, v in d.items():
        if v is None or v == "":
            continue
        if isinstance(v, (dict, list)):
            continue
        lines.append(f"- **{k.replace('_', ' ')}:** `{html.escape(str(v))}`")
    return "\n".join(lines) if lines else "_No breakdown fields._"


def render_review_sidebar_controls() -> Tuple[ReviewRowFilter, bool, bool]:
    """Sidebar filters; widget keys are stable for the Review page."""
    st.sidebar.markdown("##### Film room filters")
    _drive_labels = {
        "touchdown": "TD",
        "punt": "Punt",
        "turnover_interception": "INT",
        "turnover_fumble": "Fumble",
        "turnover_on_downs": "Turnover on downs",
        "field_goal": "FG",
        "field_goal_miss": "FG miss",
        "unknown": "Unknown / other",
    }
    drive_outcomes = st.sidebar.multiselect(
        "Drive result",
        options=list(_drive_labels.keys()),
        format_func=lambda k: _drive_labels.get(str(k), str(k)),
        default=[],
        key="review_film_drive_result_filter",
        help="**Empty selection = all drive results** (no filter). Choose one or more kinds to narrow the film room.",
    )
    kinds = tuple(str(x) for x in drive_outcomes)
    _rp_opts: Tuple[Optional[str], ...] = (None, "Run", "Pass")
    play_rp = st.sidebar.selectbox(
        "Actual play type",
        options=list(range(len(_rp_opts))),
        format_func=lambda i: "All" if _rp_opts[int(i)] is None else str(_rp_opts[int(i)]),
        key="review_film_play_rp_filter",
    )
    play_rp = _rp_opts[int(play_rp)]
    team = st.sidebar.radio(
        "Possession filter",
        options=[PREVIOUS_DRIVES_FILTER_BOTH, PREVIOUS_DRIVES_FILTER_OUR, PREVIOUS_DRIVES_FILTER_OPPONENT],
        format_func=lambda m: {"our": "Our team", "opponent": "Opponent", "both": "Both"}.get(str(m), str(m)),
        key="review_film_team_scope",
    )
    mismatch_only = st.sidebar.toggle("Show mismatches only", value=False, key="review_film_mismatch_only")
    match_only = st.sidebar.toggle("Show full matches only", value=False, key="review_film_match_only")
    st.sidebar.caption("Match toggles apply to rows with comparable metrics.")
    show_conf = st.sidebar.toggle("Emphasize confidence on model card", value=True, key="review_film_show_conf")
    show_breakdown = st.sidebar.toggle(
        "Expand breakdown sections by default", value=False, key="review_film_breakdown_expanded"
    )
    our_id = coached_team_espn_id_for_previous_drives(st.session_state)
    flt = ReviewRowFilter(
        drive_result_kinds=kinds,
        play_run_pass=play_rp,
        match_only=match_only and not mismatch_only,
        mismatch_only=mismatch_only and not match_only,
        team_side=str(team),
        our_coached_espn_id=our_id,
    )
    return flt, show_conf, show_breakdown


def render_mode_banner(mode: ReviewMode) -> None:
    if mode == ReviewMode.TRUE_STORED:
        st.success(f"**{REVIEW_MODE_LABEL_TRUE}** — {REVIEW_MESSAGE_STORED}")
    elif mode == ReviewMode.LEGACY_STORED:
        st.info(f"**{REVIEW_MODE_LABEL_LEGACY}** — {REVIEW_MESSAGE_STORED}")
    elif mode == ReviewMode.REPLAY_ONLY:
        st.info(REVIEW_MESSAGE_REPLAY)


def render_coaching_summary_panel(metrics: ReviewSummaryMetrics, *, mode: ReviewMode) -> None:
    mode_lbl = {
        ReviewMode.TRUE_STORED: "Stored review (gold)",
        ReviewMode.LEGACY_STORED: "Legacy stored review",
        ReviewMode.REPLAY_ONLY: "Replay review",
    }.get(mode, str(mode.value))
    st.markdown("### Coaching report")
    st.caption(f"**Active mode:** {mode_lbl} — stored vs replay are **never mixed** in one row.")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Plays in view", metrics.total_rows)
    c2.metric("Drives", metrics.drives_with_rows)
    c3.metric("Run/pass match", _pct(metrics.run_pass_match_rate))
    c4.metric("Bucket match", _pct(metrics.bucket_match_rate))
    c5.metric("Direction", _pct(metrics.direction_match_rate))
    c6.metric("High-conf agree", _pct(metrics.high_confidence_agreement_rate))
    fam = metrics.family_match_rate
    if fam is not None:
        st.caption(f"Family match (where comparable): **{_pct(fam)}** · High-conf = snaps with **≥60%** model confidence where run/pass & bucket both scored.")


def render_quick_insights_block(rows: Sequence[UnifiedReviewRow]) -> None:
    insights = compute_quick_insights(rows)
    if not insights:
        return
    st.markdown("#### Quick insights")
    for line in insights:
        st.markdown(f"- {line}")


def _drive_header(game: Game, drive_id: int, group: Sequence[UnifiedReviewRow]) -> str:
    if drive_id < 0 or drive_id >= len(game.drives):
        return f"Drive {drive_id}"
    dr = game.drives[drive_id]
    seq = chronological_team_drive_indices(game)
    team_n = seq[drive_id] if drive_id < len(seq) else drive_id + 1
    base = prior_drive_heading(dr, team_n)
    res = dr.result
    suffix = ""
    if res:
        suffix = f" · {res.headline}"
    plays = getattr(dr, "plays", None) or []
    nplays = len(plays)
    net_yards = sum(int(getattr(p, "yards_gained", 0) or 0) for p in plays)
    elapsed = int(getattr(dr, "time_elapsed_seconds", 0) or 0)
    if not elapsed and nplays:
        elapsed = 38 * nplays
    m, s = divmod(max(0, elapsed), 60)
    time_s = f"~{m}:{s:02d} game clock" if elapsed else ""
    yards_s = f"{net_yards:+d} yds" if nplays else "0 yds"
    bits = [f"{base}{suffix}", f"{nplays} plays", yards_s]
    if time_s:
        bits.append(time_s)
    return " · ".join(bits)


def _render_play_card(
    row: UnifiedReviewRow,
    *,
    game: Game,
    show_conf: bool,
    breakdown_expanded: bool,
) -> None:
    strength = match_strength(row)
    border = _border_color(strength)
    pre = row.pre_snap
    situ = format_situation_line(pre)
    field = format_field_position_sentence(pre)

    tags_html = ""
    if row.mismatch_tags:
        tags_html = (
            "<div style='font-size:11px;color:#fbbf24;margin-top:6px'>"
            + " · ".join(html.escape(t) for t in row.mismatch_tags)
            + "</div>"
        )

    conf_badge = ""
    if show_conf and row.confidence is not None:
        conf_badge = f"<span style='color:#94a3b8'> · {row.confidence:.0%} conf</span>"

    hist_badge = ""
    if row.is_historical:
        hist_badge = "<span style='font-size:10px;color:#4ade80'>STORED MODEL</span>"
    elif row.is_replay:
        hist_badge = "<span style='font-size:10px;color:#38bdf8'>REPLAY MODEL</span>"
    else:
        hist_badge = ""

    st.markdown(
        f"<div style='border-left:4px solid {border};border-radius:6px;padding:10px 12px;margin:8px 0;"
        f"background:rgba(15,23,42,0.45)'>{hist_badge}</div>",
        unsafe_allow_html=True,
    )

    st.caption(f"{situ} · {field}")
    left, right = st.columns(2)
    with left:
        st.markdown("**Actual**")
        st.markdown(
            f"<div style='font-size:15px;font-weight:600;color:#f8fafc'>{html.escape(row.actual_headline)}</div>"
            f"<div style='font-size:12px;color:#94a3b8;margin-top:4px'>{html.escape(row.actual_detail or '')}</div>",
            unsafe_allow_html=True,
        )
        actual_bucket = row.actual_structured.get("summary_bucket") or row.actual_structured.get("actual_bucket")
        if actual_bucket:
            st.caption(f"Bucket: **{actual_bucket}**")
    with right:
        st.markdown("**Model**" + (f" {conf_badge}" if conf_badge else ""), unsafe_allow_html=True)
        st.markdown(
            f"<div style='font-size:15px;font-weight:600;color:#38bdf8'>{html.escape(row.model_headline)}</div>"
            f"<div style='font-size:12px;color:#cbd5e1;margin-top:4px'>{html.escape(row.model_subline)}</div>",
            unsafe_allow_html=True,
        )
        if row.replay_error:
            st.caption(f"Replay: _{html.escape(row.replay_error)}_")
        if row.chain_error:
            st.caption(f"Chain: _{html.escape(row.chain_error)}_")

    cmp_html = _comparison_strip_html(row.comparison)
    st.markdown(
        f"<div style='font-size:13px;margin-top:8px;padding:8px 10px;border-radius:8px;"
        f"background:rgba(255,255,255,0.04)'><strong>Comparison</strong> · {cmp_html}</div>"
        f"{tags_html}",
        unsafe_allow_html=True,
    )

    with st.expander("Breakdown", expanded=breakdown_expanded):
        st.markdown(_breakdown_markdown(row))
        st.caption("Normalized fields only — not a full export record.")


def render_film_room(
    game: Game,
    rows: Sequence[UnifiedReviewRow],
    *,
    mode: ReviewMode,
    flt: ReviewRowFilter,
    show_conf: bool,
    breakdown_expanded: bool,
) -> None:
    filtered = filter_unified_rows(list(rows), flt)
    metrics = compute_review_summary_metrics(filtered)

    render_mode_banner(mode)
    render_coaching_summary_panel(metrics, mode=mode)
    render_quick_insights_block(filtered)

    st.divider()
    st.markdown(f"### {REVIEW_SECTION_FILM_ROOM}")
    st.caption(f"**{len(filtered)}** play card(s) after filters (from **{len(rows)}** total).")

    if not filtered:
        if not rows:
            if mode == ReviewMode.REPLAY_ONLY:
                st.info(
                    "**No replay rows** — if you expected cards here, try **Possession filter → Both**, "
                    "or confirm drives have logged plays and replay did not skip them (see any replay/chain messages on cards)."
                )
            else:
                st.info("No review rows to display.")
        else:
            st.info("No plays match filters — widen filters in the sidebar (empty **Drive result** = all outcomes).")
        return

    by_drive = group_unified_rows_by_drive(filtered)
    for drive_id, group in by_drive.items():
        title = _drive_header(game, drive_id, group)
        with st.expander(title, expanded=False):
            for row in group:
                st.markdown(
                    f"##### Play {row.play_index_on_drive}"
                    + (f" · snap {row.audit_index + 1}" if row.audit_index is not None else "")
                )
                _render_play_card(row, game=game, show_conf=show_conf, breakdown_expanded=breakdown_expanded)
                st.divider()

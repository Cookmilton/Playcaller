"""Film-room style Review Session layout (dual-mode unified rows)."""

from __future__ import annotations

import html
from typing import AbstractSet, Optional, Sequence, Tuple

import streamlit as st

from playcaller.game import Game
from playcaller.play_event_segment import PlayEventSegment
from playcaller.live_data.drive_display import (
    PREVIOUS_DRIVES_FILTER_BOTH,
    PREVIOUS_DRIVES_FILTER_OPPONENT,
    PREVIOUS_DRIVES_FILTER_OUR,
    chronological_team_drive_indices,
    classify_drive_team_side,
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
from playcaller.drive_audit_report import compute_drive_audit
from playcaller.review.derived import derive_key_moments
from playcaller.reconciliation.drive_reconciler import reconcile_drive
from playcaller.review.session_analytics import (
    build_model_diagnostics,
    build_pattern_analysis,
    model_diagnostics_markdown_lines,
    pattern_analysis_markdown_lines,
)
from playcaller.review_insights import (
    aggregate_situation,
    build_game_flow,
    build_indexed_our_offense,
    compute_drive_grade,
    detect_patterns,
    filter_our_offense_rows,
    game_flow_section_html,
    generate_game_story,
    label_call_quality,
    rank_top_mistakes,
    related_drive_indices_for_pattern,
    SITUATION_LABELS,
    SITUATION_ORDER,
)
from playcaller.review_insights.comparison_format import (
    build_model_ranked_family_lines,
    format_actual_comparison_line,
)
from playcaller.review_insights.models import DriveGrade, PlayMistake
from playcaller.streamlit_state.session import coached_team_espn_id_for_previous_drives
from playcaller.ui.format_play_context import format_play_context
from playcaller.ui.previous_drives_render import render_drive_score_ribbon, render_score_reconciliation_strip
FILM_ROOM_FOCUS_DRIVE = "review_film_room_focus_drive_idx"
FILM_ROOM_FOCUS_PLAY = "review_film_room_focus_play_tuple"  # (drive_id, play_index_on_drive)

from playcaller.ui.product_copy import (
    REVIEW_MESSAGE_REPLAY,
    REVIEW_MESSAGE_STORED,
    REVIEW_MESSAGE_WAREHOUSE,
    REVIEW_MODE_LABEL_LEGACY,
    REVIEW_MODE_LABEL_TRUE,
    REVIEW_MODE_LABEL_WAREHOUSE,
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
    _seg_opts = [s.value for s in PlayEventSegment]
    _seg_lbl = {
        "offense": "Offense (scrimmage)",
        "kickoff": "Kickoff",
        "punt": "Punt",
        "field_goal": "Field goal / try",
        "pat": "Extra point",
        "other_special": "Other special teams",
        "admin": "Admin / no-play",
    }
    seg_pick = st.sidebar.multiselect(
        "Event types",
        options=_seg_opts,
        default=_seg_opts,
        format_func=lambda x: _seg_lbl.get(str(x), str(x)),
        key="review_film_event_segments",
        help="**All selected = no filter.** Narrow to offense only to focus on true scrimmage snaps.",
    )
    seg_filt: Tuple[str, ...] = () if len(seg_pick) == len(_seg_opts) else tuple(str(x) for x in seg_pick)
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
        event_segments=seg_filt,
    )
    return flt, show_conf, show_breakdown


def render_mode_banner(mode: ReviewMode) -> None:
    if mode == ReviewMode.TRUE_STORED:
        st.success(f"**{REVIEW_MODE_LABEL_TRUE}** — {REVIEW_MESSAGE_STORED}")
    elif mode == ReviewMode.LEGACY_STORED:
        st.info(f"**{REVIEW_MODE_LABEL_LEGACY}** — {REVIEW_MESSAGE_STORED}")
    elif mode == ReviewMode.REPLAY_ONLY:
        st.info(REVIEW_MESSAGE_REPLAY)
    elif mode == ReviewMode.WAREHOUSE_HISTORICAL:
        st.info(REVIEW_MESSAGE_WAREHOUSE)


def render_coaching_summary_panel(metrics: ReviewSummaryMetrics, *, mode: ReviewMode) -> None:
    mode_lbl = {
        ReviewMode.TRUE_STORED: "Stored review (gold)",
        ReviewMode.LEGACY_STORED: "Legacy stored review",
        ReviewMode.REPLAY_ONLY: "Replay review",
        ReviewMode.WAREHOUSE_HISTORICAL: REVIEW_MODE_LABEL_WAREHOUSE,
    }.get(mode, str(mode.value))
    st.markdown("#### Coaching report")
    st.caption(f"**Active mode:** {mode_lbl} — stored vs replay are **never mixed** in one row.")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Plays in view", metrics.total_rows)
    c2.metric("Drives", metrics.drives_with_rows)
    c3.metric("Run/pass match", _pct(metrics.run_pass_match_rate))
    c4.metric("Bucket match", _pct(metrics.bucket_match_rate))
    c5.metric("Direction", _pct(metrics.direction_match_rate))
    c6.metric("High-conf agree", _pct(metrics.high_confidence_agreement_rate))
    st.caption(
        f"**Offensive scrimmage rows:** {metrics.offensive_rows} · "
        f"**Special teams / other:** {metrics.special_teams_rows} · "
        "Match rates use **offense only**."
    )
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


def render_patterns_section(game: Game, rows: Sequence[UnifiedReviewRow]) -> None:
    """Cross-drive tendencies (analytics from ``review_insights.patterns``)."""
    our_id = coached_team_espn_id_for_previous_drives(st.session_state)
    ours = filter_our_offense_rows(game, rows, our_coached_espn_id=our_id)
    patterns = detect_patterns(ours, game)
    st.markdown("### Patterns")
    if not patterns:
        st.caption("No distinctive cross-drive patterns yet (need more samples or more balanced tendencies).")
        return
    for pi, p in enumerate(patterns):
        st.markdown(f"- {html.escape(p.summary)}")
        rel = related_drive_indices_for_pattern(p, ours)
        if rel:
            with st.expander("Show supporting drives", expanded=False):
                btn_cols = st.columns(min(6, len(rel)))
                for j, di in enumerate(rel[:6]):
                    with btn_cols[j]:
                        if st.button(
                            f"Drive {di + 1}",
                            key=f"pattern_nav_{pi}_{di}",
                            help=f"Focus drive {di + 1}",
                        ):
                            st.session_state[FILM_ROOM_FOCUS_DRIVE] = int(di)
                            st.rerun()


def render_top_mistakes_section(mistakes: Sequence[PlayMistake]) -> None:
    """Ranked mistake cards with jump-to-play navigation (film room expander)."""
    if not mistakes:
        return
    st.markdown("### Top Mistakes")
    for mi, m in enumerate(mistakes):
        title = f"#{mi + 1} — Drive {m.drive_number}, Play {m.play_number}"
        st.markdown(f"**{html.escape(title)}**")
        st.markdown(html.escape(m.context_summary))
        st.markdown(
            f'<p style="margin:8px 0 4px 0;color:#f8fafc">Actual: {html.escape(m.actual_summary)}</p>'
            f'<p style="margin:0;color:#94a3b8;font-size:13px">Model: {html.escape(m.model_top)}</p>',
            unsafe_allow_html=True,
        )
        st.markdown(f"- **Why it matters:** {html.escape(m.why_it_matters)}")
        if st.button(
            "Show in film room",
            key=f"top_mistake_jump_{mi}_{m.play_id}",
            help=f"Expand drive {m.drive_number} and highlight play {m.play_number}",
        ):
            st.session_state[FILM_ROOM_FOCUS_DRIVE] = int(m.drive_id)
            st.session_state[FILM_ROOM_FOCUS_PLAY] = (int(m.drive_id), int(m.play_number))
            st.rerun()
        st.divider()


def render_situational_breakdown_panel(
    game: Game,
    rows: Sequence[UnifiedReviewRow],
) -> None:
    """Chip filter + aggregates + optional compact play list (``review_insights.situational``)."""
    our_id = coached_team_espn_id_for_previous_drives(st.session_state)
    indexed = build_indexed_our_offense(game, rows, our_coached_espn_id=our_id)
    st.markdown("### Situational breakdown")
    if not indexed:
        st.caption("No offensive snaps for the coached team in this session.")
        return
    chip = st.radio(
        "Situation filter",
        options=list(SITUATION_ORDER),
        format_func=lambda k: SITUATION_LABELS[k],
        horizontal=True,
        key="review_situational_chip",
        label_visibility="collapsed",
    )
    agg = aggregate_situation(game, indexed, chip)
    idx_map = {gi: r for gi, r in indexed}
    label = agg.situation_label
    st.markdown(f"**Situation:** {html.escape(label)} · **{agg.play_count}** play(s)")
    if agg.play_count == 0:
        st.caption("No plays in this slice.")
        return
    sr = agg.success_rate
    sr_s = f"{int(round(100 * sr))}% ({agg.success_count}/{agg.play_count})" if sr is not None else "—"
    avg_s = f"{agg.avg_yards:.1f}" if agg.avg_yards is not None else "—"
    mcr = html.escape(agg.most_common_result) if agg.most_common_result else "—"
    st.markdown(
        f"- **Success rate:** {sr_s}  \n"
        f"- **Avg yards:** {avg_s}  \n"
        f"- **Run/pass:** {agg.run_count} / {agg.pass_count}  \n"
        f"- **Most common result:** {mcr}"
    )
    ordered = sorted(
        (idx_map[i] for i in agg.play_indices if i in idx_map),
        key=lambda r: (r.drive_id, r.play_index_on_drive),
    )
    with st.expander("Show all plays", expanded=False):
        for row in ordered:
            ctx_line = format_play_context(row.pre_snap, row.event_segment, game=game, drive_id=row.drive_id)
            st.markdown(
                f"**Play {row.play_index_on_drive}** — {ctx_line}"
            )
            st.markdown(f"_{html.escape(row.actual_headline)}_")
            if row.actual_detail:
                st.caption(html.escape(row.actual_detail))
            st.divider()


def render_game_flow_section(game: Game) -> None:
    """Chronological drive strip + momentum (``review_insights.timeline`` — no math here)."""
    if not game.drives:
        return
    our_id = coached_team_espn_id_for_previous_drives(st.session_state)
    st.markdown("### Game flow")
    st.caption("Reconciled outcomes, plays · yards · TOP, running score — with momentum context when sample is large enough.")
    bundle = build_game_flow(game, our_coached_espn_id=our_id)
    st.markdown(game_flow_section_html(game, bundle, our_coached_espn_id=our_id), unsafe_allow_html=True)


def render_game_story_section(game: Game, rows: Sequence[UnifiedReviewRow]) -> None:
    """Coach briefing bullets (analytics only — see ``playcaller.review_insights``)."""
    our_id = coached_team_espn_id_for_previous_drives(st.session_state)
    st.markdown("### Game story")
    bullets = generate_game_story(game, rows, our_coached_espn_id=our_id)
    if not bullets:
        st.caption("Not enough consolidated sample yet for automated story beats (or all patterns were suppressed).")
        return
    for bi, b in enumerate(bullets):
        st.markdown(f"- {html.escape(b.text)}")
        if b.related_drive_indices:
            btn_cols = st.columns(min(6, len(b.related_drive_indices)))
            for j, di in enumerate(b.related_drive_indices[:6]):
                with btn_cols[j]:
                    if st.button(f"{di + 1}", key=f"story_nav_{bi}_{di}", help=f"Focus drive {di + 1}"):
                        st.session_state[FILM_ROOM_FOCUS_DRIVE] = int(di)
                        st.rerun()


def _drive_header(
    game: Game, drive_id: int, group: Sequence[UnifiedReviewRow], *, grade: Optional[DriveGrade] = None
) -> str:
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
    if grade is not None:
        if grade.letter == "—":
            bits.append("Grade —")
        elif grade.total_score is not None:
            bits.append(f"Grade {grade.letter} ({grade.total_score})")
    return " · ".join(bits)


def _render_drive_grade_detail(grade: DriveGrade) -> None:
    if grade.letter == "—" or grade.total_score is None:
        st.caption("_Kneel / clock drive — not graded._")
        return
    st.markdown(f"**Grade {grade.letter}** ({grade.total_score})")
    if grade.failure_explanations:
        st.markdown("**Why this drive struggled**")
        for line in grade.failure_explanations:
            st.markdown(f"- {html.escape(line)}")
    oc = grade.outcome_component if grade.outcome_component is not None else 0
    ef = grade.efficiency_component if grade.efficiency_component is not None else 0
    stt = grade.situational_component if grade.situational_component is not None else 0
    md = grade.model_component if grade.model_component is not None else 0
    with st.expander("Show breakdown", expanded=False):
        st.markdown(
            f"- {oc}/40 outcome  \n"
            f"- {ef}/30 efficiency  \n"
            f"- {stt}/20 situational  \n"
            f"- {md}/10 model match"
        )


def _film_room_actual_model_html(row: UnifiedReviewRow) -> str:
    """Separate actual (primary) from model (muted) — no mixed phrasing on one line."""
    if row.event_segment != PlayEventSegment.OFFENSE:
        a = html.escape(format_actual_comparison_line(row))
        return (
            f'<div style="margin-top:6px">'
            f'<p style="margin:0;color:#f8fafc">Actual: {a}</p>'
            f'<p style="margin:8px 0 0 0;color:#94a3b8;font-size:13px">Model: —</p>'
            f'<p style="margin:4px 0 0 0;color:#64748b;font-size:12px"><em>No offensive model comparison for this snap.</em></p>'
            f"</div>"
        )
    actual = html.escape(format_actual_comparison_line(row))
    lines, _, phrase = build_model_ranked_family_lines(row)
    if not lines:
        model_block = (
            '<p style="margin:8px 0 0 0;color:#94a3b8;font-size:13px">'
            "Model: <em>No model recommendation captured for this snap.</em></p>"
        )
    else:
        parts: list[str] = []
        for i, ln in enumerate(lines[:3]):
            mt = "8px" if i == 0 else "4px"
            parts.append(
                f'<p style="margin:{mt} 0 0 0;color:#94a3b8;font-size:13px">Model: {html.escape(ln)}</p>'
            )
        model_block = "".join(parts)
    phrase_esc = html.escape(phrase)
    return (
        f'<div style="margin-top:6px">'
        f'<p style="margin:0;color:#f8fafc">Actual: {actual}</p>'
        f"{model_block}"
        f'<p style="margin:8px 0 0 0;color:#94a3b8;font-size:12px">{phrase_esc}</p>'
        f"</div>"
    )


def _render_play_card(
    row: UnifiedReviewRow,
    *,
    game: Game,
    show_conf: bool,
    breakdown_expanded: bool,
    top_mistake_ids: AbstractSet[str],
    focus_play: Optional[Tuple[int, int]],
) -> None:
    strength = match_strength(row)
    border = _border_color(strength)
    is_focus = (
        focus_play is not None
        and int(focus_play[0]) == int(row.drive_id)
        and int(focus_play[1]) == int(row.play_index_on_drive)
    )
    if is_focus:
        border = "#f97316"
    pre = row.pre_snap
    ctx_line = format_play_context(pre, row.event_segment, game=game, drive_id=row.drive_id)
    cq = label_call_quality(game, row, top_mistake_play_ids=top_mistake_ids)
    sig = cq.symbol
    if row.event_segment == PlayEventSegment.OFFENSE and row.offensive_snap_index is not None:
        snap_hdr = f"{sig} Offensive snap **{row.offensive_snap_index}** · row #{row.play_index_on_drive}"
    else:
        snap_hdr = f"{sig} **{row.event_segment.value.replace('_', ' ').title()}** · row #{row.play_index_on_drive}"

    tags_html = ""
    if row.mismatch_tags:
        tags_html = (
            "<div style='font-size:11px;color:#fbbf24;margin-top:6px'>"
            + " · ".join(html.escape(t) for t in row.mismatch_tags)
            + "</div>"
        )

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

    st.caption(snap_hdr)
    st.caption(f"_Call quality:_ **{cq.symbol}** {html.escape(cq.reason)}")
    if is_focus:
        st.caption("_Focused from Top Mistakes — scroll within this drive if needed._")
    st.markdown(html.escape(ctx_line))
    if row.event_segment != PlayEventSegment.OFFENSE:
        st.caption(
            "_Stored model line is an **offensive** recommendation — not scored against special teams outcomes._"
        )
    st.markdown(_film_room_actual_model_html(row), unsafe_allow_html=True)
    if row.event_segment == PlayEventSegment.OFFENSE:
        lines_all, _, _ = build_model_ranked_family_lines(row)
        if len(lines_all) > 3:
            with st.expander("Show all recommendations", expanded=False):
                for ln in lines_all[3:]:
                    st.markdown(
                        f'<p style="margin:0;color:#94a3b8;font-size:13px">Model: {html.escape(ln)}</p>',
                        unsafe_allow_html=True,
                    )
    if show_conf and row.confidence is not None:
        st.caption(f"Top recommendation confidence: **{row.confidence:.0%}**")
    if row.replay_error:
        st.caption(f"Replay: _{html.escape(row.replay_error)}_")
    if row.chain_error:
        st.caption(f"Chain: _{html.escape(row.chain_error)}_")

    prov_raw = pre.get("snap_provenance")
    if prov_raw:
        with st.expander("Show situation sources", expanded=False):
            if isinstance(prov_raw, dict):
                for pk, pv in sorted(prov_raw.items(), key=lambda x: str(x[0])):
                    st.caption(f"{html.escape(str(pk))}: {html.escape(str(pv))}")
            else:
                for item in prov_raw:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        st.caption(f"{html.escape(str(item[0]))}: {html.escape(str(item[1]))}")

    cmp_html = _comparison_strip_html(row.comparison)
    st.markdown(
        f"<div style='font-size:13px;margin-top:8px;padding:8px 10px;border-radius:8px;"
        f"background:rgba(255,255,255,0.04)'><strong>Direction / bucket / family</strong> · {cmp_html}</div>"
        f"{tags_html}",
        unsafe_allow_html=True,
    )

    with st.expander("Show play breakdown", expanded=breakdown_expanded):
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
    our_id = coached_team_espn_id_for_previous_drives(st.session_state)
    session_top_mistakes = rank_top_mistakes(game, rows, our_coached_espn_id=our_id)
    mistake_ids = {m.play_id for m in session_top_mistakes}

    audit_report = compute_drive_audit(game)
    st.markdown("### Score ribbon")
    render_drive_score_ribbon(audit_report)
    render_score_reconciliation_strip(game, audit_report)
    st.divider()

    render_mode_banner(mode)
    st.divider()

    render_game_story_section(game, rows)
    st.divider()
    render_patterns_section(game, rows)
    st.divider()
    render_game_flow_section(game)
    st.divider()
    render_top_mistakes_section(session_top_mistakes)
    st.divider()
    render_situational_breakdown_panel(game, rows)
    st.divider()

    with st.expander("Show coaching metrics", expanded=False):
        render_coaching_summary_panel(metrics, mode=mode)
        render_quick_insights_block(filtered)

    moments = derive_key_moments(list(game.recommendation_audit or []))
    if moments:
        with st.expander("Notable situations & turning points", expanded=False):
            st.caption("Derived from logged outcomes and score-diff shifts — not a full broadcast charting.")
            for m in moments[:14]:
                st.markdown(f"- **{m.headline}** — {m.detail}")

    pa = build_pattern_analysis(filtered)
    with st.expander("Pattern analysis (tendencies)", expanded=False):
        for line in pattern_analysis_markdown_lines(pa):
            st.markdown(line)

    md = build_model_diagnostics(filtered)
    with st.expander("Model diagnostics", expanded=False):
        for line in model_diagnostics_markdown_lines(md):
            st.markdown(line)

    st.divider()
    st.markdown(f"### {REVIEW_SECTION_FILM_ROOM}")
    st.caption(f"**{len(filtered)}** play card(s) after filters (from **{len(rows)}** total).")

    rows_by_drive_full = group_unified_rows_by_drive(list(rows))

    if not filtered:
        if not rows:
            if mode in (ReviewMode.REPLAY_ONLY, ReviewMode.WAREHOUSE_HISTORICAL):
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
    focus_idx = st.session_state.get(FILM_ROOM_FOCUS_DRIVE)
    focus_play = st.session_state.get(FILM_ROOM_FOCUS_PLAY)
    for drive_id, group in by_drive.items():
        dr = game.drives[drive_id] if 0 <= drive_id < len(game.drives) else None
        grade: Optional[DriveGrade] = None
        if dr is not None:
            rec = reconcile_drive(dr, espn=dr.feed_audit)
            side = classify_drive_team_side(dr, our_coached_espn_id=our_id)
            perspective = "defense" if side == "opp" else "possession_offense"
            grade_rows = rows_by_drive_full.get(drive_id, group)
            grade = compute_drive_grade(dr, grade_rows, rec, perspective=perspective)
        title = _drive_header(game, drive_id, group, grade=grade)
        expanded = focus_idx is not None and int(focus_idx) == int(drive_id)
        with st.expander(title, expanded=expanded):
            if grade is not None:
                _render_drive_grade_detail(grade)
            for row in group:
                st.markdown(
                    f"##### Play {row.play_index_on_drive}"
                    + (f" · snap {row.audit_index + 1}" if row.audit_index is not None else "")
                )
                _render_play_card(
                    row,
                    game=game,
                    show_conf=show_conf,
                    breakdown_expanded=breakdown_expanded,
                    top_mistake_ids=mistake_ids,
                    focus_play=focus_play,
                )
                st.divider()

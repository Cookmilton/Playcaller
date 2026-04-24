"""Streamlit rendering for archived drives + model replay (keeps logic out of bare helpers)."""

from __future__ import annotations

import html

import plotly.graph_objects as go
import streamlit as st

from playcaller import FootballPlayPredictor, Game, GameContext
from playcaller.drive_audit_report import (
    AuditLensChip,
    DriveAuditReport,
    DriveAuditRow,
    archived_drive_expander_title_from_audit,
    audit_actionable_explanation_lines,
    audit_status_header_tag,
    audit_status_kind,
    compute_drive_audit,
    filter_archived_indices_by_audit_lens,
    filter_audit_rows_for_lens,
    score_reconciliation_summary_lines,
)
from playcaller.live_data.drive_display import (
    PREVIOUS_DRIVES_FILTER_BOTH,
    PREVIOUS_DRIVES_FILTER_OPPONENT,
    PREVIOUS_DRIVES_FILTER_OUR,
    chronological_team_drive_indices,
    filter_previous_drive_indices,
    prior_drive_heading,
    previous_drives_empty_filter_message,
)
from playcaller.replay.analysis_types import ActualVsReplayComparisonRow, PreSnapContextRecord
from playcaller.replay.previous_drive_replay import REPLAY_UNAVAILABLE
from playcaller.replay.previous_drive_replay import cached_comparison_rows_for_archived_drive
from playcaller.streamlit_state.keys import (
    LIVE_FEED_TEAM_SCOPE,
    UI_DRIVE_AUDIT_FOCUS_CHRON,
    UI_DRIVE_AUDIT_LENS_CHIP,
    UI_DRIVE_AUDIT_SHOW_ALL,
)
from playcaller.streamlit_state.session import coached_team_espn_id_for_previous_drives
from playcaller.ui.product_copy import CAPTION_POST_DRIVE_REPLAY, SECTION_DRIVE_ARCHIVE


def _ribbon_marker_symbol(r: DriveAuditRow) -> str:
    scoring = r.inferred_points > 0
    flagged = r.severity != "clean"
    if scoring and flagged:
        return "diamond-open"
    if scoring:
        return "diamond"
    if flagged:
        return "circle-open"
    return "circle"


def render_drive_score_ribbon(report: DriveAuditReport) -> None:
    """Cumulative score by drive from audit rows (session OC = us)."""
    if report.score_ribbon_unavailable():
        st.warning("⚠️ Score progression unavailable — check feed sync.")
        return
    rows = list(report.rows)
    x = [r.chron_drive_number for r in rows]
    y_us = [r.score_after_us for r in rows]
    y_them = [r.score_after_them for r in rows]
    customdata = [
        (
            r.chron_drive_number,
            r.team_label,
            r.outcome_reconciled or r.outcome_inferred,
            f"{r.score_after_us}–{r.score_after_them}",
        )
        for r in rows
    ]
    hover = (
        "<b>Drive %{customdata[0]}</b><br>"
        "%{customdata[1]}<br>"
        "%{customdata[2]}<br>"
        "Score after: %{customdata[3]}"
        "<extra></extra>"
    )
    color_us = "#38bdf8"
    color_them = "#fb7185"
    fig = go.Figure()
    for name, y_vals, color in (
        ("Us (session OC)", y_us, color_us),
        ("Them", y_them, color_them),
    ):
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y_vals,
                mode="lines+markers",
                name=name,
                line=dict(color=color, width=2),
                marker=dict(
                    size=[10 if rows[i].inferred_points > 0 else 6 for i in range(len(rows))],
                    symbol=[_ribbon_marker_symbol(rows[i]) for i in range(len(rows))],
                    color=color,
                    line=dict(width=1.2, color=color),
                ),
                customdata=customdata,
                hovertemplate=hover,
            )
        )
    ymax = max(max(y_us + [0]), max(y_them + [0]), 1)
    fig.update_layout(
        height=180,
        margin=dict(l=8, r=8, t=28, b=36),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(15,23,42,0.35)",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            font=dict(size=11, color="#94a3b8"),
        ),
        xaxis=dict(
            title="Drive #",
            tickmode="linear",
            dtick=1,
            gridcolor="rgba(148,163,184,0.15)",
            zeroline=False,
            color="#94a3b8",
        ),
        yaxis=dict(
            title="Score",
            range=[0, min(55, ymax + 4)],
            gridcolor="rgba(148,163,184,0.15)",
            zeroline=False,
            color="#94a3b8",
        ),
        font=dict(color="#cbd5e1", size=11),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _audit_table_title_detail(report: DriveAuditReport, *, show_all: bool, chip: AuditLensChip) -> str:
    flagged_n = sum(1 for r in report.rows if r.severity != "clean" or r.outcome_mismatch)
    total = len(report.rows)
    if not show_all:
        if chip == "all":
            return f"{flagged_n} flagged drive(s)"
        vis = len(filter_audit_rows_for_lens(report, show_all=False, chip=chip))
        return f"{vis} drive(s) · filtered (of {flagged_n} flagged)"
    if chip == "all":
        return f"all {total} drives"
    vis = len(filter_audit_rows_for_lens(report, show_all=True, chip=chip))
    return f"{vis} drive(s) · filtered (of {total} total)"


def _lens_chip_labels() -> dict[str, str]:
    return {
        "all": "All",
        "score": "🔴 Score conflict",
        "outcome": "⚠️ Outcome mismatch",
        "clean": "✅ Clean",
    }


def render_shared_drive_audit_lens_controls(report: DriveAuditReport) -> tuple[bool, AuditLensChip]:
    """
    Single shared filter for archived drives + audit table (widgets bound once per page).
    Returns ``(show_all, chip)`` from session after widgets render.
    """
    st.markdown("**Drive integrity lens**")
    st.caption(
        "Same filter for **archived drives** below and the **audit table**. "
        "Default hides clean drives; turn on **Show all drives** for the full list."
    )
    st.checkbox("Show all drives", key=UI_DRIVE_AUDIT_SHOW_ALL, value=False)
    labs = _lens_chip_labels()
    st.radio(
        "Lens filter",
        options=["all", "score", "outcome", "clean"],
        format_func=lambda k: labs[str(k)],
        horizontal=True,
        key=UI_DRIVE_AUDIT_LENS_CHIP,
        label_visibility="collapsed",
    )
    show_all = bool(st.session_state.get(UI_DRIVE_AUDIT_SHOW_ALL, False))
    raw_chip = st.session_state.get(UI_DRIVE_AUDIT_LENS_CHIP, "all")
    chip: AuditLensChip = raw_chip if raw_chip in ("all", "score", "outcome", "clean") else "all"
    return show_all, chip


def render_score_reconciliation_strip(game: Game, report: DriveAuditReport) -> None:
    lines = score_reconciliation_summary_lines(game, report)
    if not lines:
        return
    with st.expander("Score reconciliation · session vs implied drives", expanded=False):
        for line in lines:
            st.markdown(f"- {line}")


def render_drive_focus_link(
    *,
    audit_by_index: dict[int, DriveAuditRow],
    archived_indices_filtered: list[int],
) -> int:
    """
    Shared chron focus (0 = none). Expands the matching archived drive expander on the next run.
    Streamlit cannot scroll the sidebar/main column to a widget; selection state is the practical link.
    """
    nums = [0] + [i + 1 for i in archived_indices_filtered]

    def _fmt(n: int) -> str:
        if n == 0:
            return "— No drive focus —"
        ar = audit_by_index.get(n - 1)
        if ar is None:
            return f"Drive {n}"
        tag = audit_status_header_tag(ar)
        tl = (ar.team_label or "").strip()
        short = tl[:22] + ("…" if len(tl) > 22 else "")
        return f"Chron {n} · {ar.badge} [{tag}] · {short}"

    st.selectbox(
        "Focus archived drive (links audit ↔ narrative)",
        options=nums,
        format_func=_fmt,
        key=UI_DRIVE_AUDIT_FOCUS_CHRON,
        help="Highlights the matching drive card (expanded). Same chron # as the audit table “#” column.",
    )
    focus = int(st.session_state.get(UI_DRIVE_AUDIT_FOCUS_CHRON, 0) or 0)
    if focus and focus not in nums:
        st.session_state[UI_DRIVE_AUDIT_FOCUS_CHRON] = 0
        return 0
    return focus


def render_drive_audit_panel(report: DriveAuditReport) -> None:
    """Detail table — uses :data:`UI_DRIVE_AUDIT_SHOW_ALL` / :data:`UI_DRIVE_AUDIT_LENS_CHIP` from the lens row."""
    subtitle = "integrity & score reconciliation"
    with st.expander(f"**Drive audit (debug)** — {subtitle}", expanded=False):
        st.caption(
            "Uses the **Drive integrity lens** above. Per-drive ESPN metadata (when captured), inferred outcomes, "
            "and reconciliation vs the session scoreboard. **TD = 7 pts** (6 + PAT assumed)."
        )
        st.caption(
            "If entire **opponent** possessions are missing, sidebar **Feed team scope** was likely **Our team** "
            "during sync — switch to **Both teams** and re-sync."
        )
        for w in report.global_warn:
            st.warning(w)

        show_all = bool(st.session_state.get(UI_DRIVE_AUDIT_SHOW_ALL, False))
        raw_chip = st.session_state.get(UI_DRIVE_AUDIT_LENS_CHIP, "all")
        chip: AuditLensChip = raw_chip if raw_chip in ("all", "score", "outcome", "clean") else "all"

        title_detail = _audit_table_title_detail(report, show_all=show_all, chip=chip)
        st.markdown(f"**Drive audit — {title_detail}**")

        visible = filter_audit_rows_for_lens(report, show_all=show_all, chip=chip)
        if visible:
            st.dataframe([r.to_table_row() for r in visible], use_container_width=True)
            st.caption(
                "Row **#** is chronological drive order — matches **Chron** in archived drive titles and the focus menu."
            )
        else:
            st.caption("No drives match the current lens.")


def _render_archived_drive_audit_block(ar: DriveAuditRow, *, report: DriveAuditReport) -> None:
    """Diagnostic companion: explains how the reconciled archive card was built."""
    kind = audit_status_kind(ar)
    tag = audit_status_header_tag(ar)
    st.markdown(
        f'<p style="font-size:12px;color:#94a3b8;margin:0 0 6px 0">'
        f"{ar.badge} <b>{html.escape(tag)}</b> · "
        f"<span style='color:#e2e8f0'>Chron {ar.chron_drive_number}</span> · "
        f"{html.escape(kind.replace('_', ' '))}"
        f"</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"**Drive — {html.escape(ar.team_label)} — {html.escape(ar.outcome_reconciled)}** *(reconciled)*"
    )
    st.caption(f"Provenance: {html.escape(ar.provenance_summary or '—')}")
    if ar.resolution_notes:
        st.markdown("**Resolved / notes**")
        for note in ar.resolution_notes:
            st.markdown(f"- {note}")

    tbl = ar.to_table_row()
    src = html.escape(str(tbl.get("Outcome source") or "—"))
    match_ok = "✓" if ar.inferred_vs_espn_ok else "✗"
    if kind == "clean" and ar.severity == "clean":
        st.caption(f"✅ Reconciled cleanly · {src}")
    else:
        expl = audit_actionable_explanation_lines(ar)
        if expl:
            st.markdown("**Diagnostics**")
            for line in expl:
                st.markdown(f"- {line}")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            f"- **Outcome (reconciled):** {html.escape(ar.outcome_reconciled)}\n"
            f"- **Outcome (ESPN raw):** {html.escape(ar.outcome_espn)}\n"
            f"- **Outcome (plays / inferred):** {html.escape(ar.outcome_inferred)}\n"
            f"- **Coarse buckets:** ESPN `{html.escape(ar.espn_outcome_code or '—')}` vs "
            f"plays `{html.escape(ar.inferred_outcome_code or '—')}` · raw match {match_ok}"
        )
    with c2:
        q = html.escape(ar.quarter_start)
        clk = html.escape(ar.clock_start)
        score_line = (
            f"+{ar.inferred_points} pts (reconciled) → after drive **{ar.score_after_us}–{ar.score_after_them}** "
            f"(start {ar.score_start_us}–{ar.score_start_them})"
        )
        st.markdown(
            f"- **Build source:** {src}\n"
            f"- **Threaded score:** {html.escape(score_line)}\n"
            f"- **Q / clock @ start:** Q{q} / {clk}\n"
            f"- **Field:** {html.escape(ar.field_start)}"
        )
    if report.global_score_mismatch and ar.severity == "critical":
        st.caption("🔴 This drive contributes to a **global scoreboard vs threaded** mismatch — see Score reconciliation.")

    raw = " · ".join(ar.flags) if ar.flags else ""
    if raw:
        with st.expander("Verbose diagnostic flags", expanded=False):
            st.text(raw)


def _provenance_tag(pre: PreSnapContextRecord, field: str) -> str:
    m = dict(pre.snap_provenance) if pre.snap_provenance else {}
    v = m.get(field, "")
    return "*" if v in ("reconstructed", "drive_fallback", "inherited_prior", "computed") else ""


def _ordinal_down(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(int(n), f"{n}th")


def _down_distance_segment(pre: PreSnapContextRecord) -> str:
    """Offensive down & distance with subtle provenance marker."""
    if pre.down is None:
        return ""
    prov = dict(pre.snap_provenance) if pre.snap_provenance else {}
    star = ""
    if prov.get("down") in ("reconstructed", "drive_fallback", "inherited_prior", "computed") or prov.get(
        "distance"
    ) in ("reconstructed", "drive_fallback", "inherited_prior", "computed"):
        star = "*"
    if pre.goal_to_go:
        return f"{_ordinal_down(pre.down)} & Goal{star}"
    if pre.distance is None:
        return f"{_ordinal_down(pre.down)} & —{star}" if star else f"{_ordinal_down(pre.down)} & —"
    return f"{_ordinal_down(pre.down)} & {pre.distance}{star}"


def _field_position_segment(pre: PreSnapContextRecord) -> str:
    if pre.yardline is None or not (pre.territory or "").strip():
        return ""
    yl = int(pre.yardline)
    prov = dict(pre.snap_provenance) if pre.snap_provenance else {}
    star = ""
    if prov.get("territory") in ("reconstructed", "drive_fallback", "inherited_prior", "computed") or prov.get(
        "yard_line"
    ) in ("reconstructed", "drive_fallback", "inherited_prior", "computed"):
        star = "*"
    terr = (pre.territory or "").strip().lower()
    if yl == 50 and terr == "own":
        return f"50{star}"
    if terr == "own":
        ab = (pre.possession_team_abbrev or "").strip()
        return f"{ab} {yl}{star}" if ab else f"OWN {yl}{star}"
    if terr == "opponents":
        ab = (pre.opponent_team_abbrev or "").strip() or "OPP"
        return f"{ab} {yl}{star}"
    return f"? {yl}{star}"


def _special_teams_label(r: ActualVsReplayComparisonRow) -> str:
    rt = str((r.actual_structured_result or {}).get("result_type") or "").lower()
    if rt == "punt":
        return "Punt"
    if rt == "kickoff":
        return "Kickoff"
    if rt in ("field_goal", "field_goal_miss"):
        return "Field goal"
    if rt in ("extra_point", "extra_point_miss"):
        return "Extra point"
    return "Special teams"


def _compact_snap_context_line(r: ActualVsReplayComparisonRow) -> str:
    """Single-line pre-snap context from feed + resolver; omits unknowns (no fake Q1 / 15:00)."""
    pre = r.pre_snap_context
    parts: list[str] = []
    prov = dict(pre.snap_provenance) if pre.snap_provenance else {}

    def _clock_token() -> str:
        if pre.clock_display and str(pre.clock_display).strip():
            return str(pre.clock_display).strip() + _provenance_tag(pre, "clock")
        if pre.seconds_remaining is not None:
            sec = max(0, int(pre.seconds_remaining))
            m, s = divmod(sec, 60)
            return f"{m}:{s:02d}" + _provenance_tag(pre, "seconds")
        return ""

    st_err = (r.replay_error or "").strip()
    if st_err == "Special teams — no offensive model call":
        if pre.quarter and pre.quarter > 0:
            ct = _clock_token()
            if ct:
                parts.append(f"Q{pre.quarter} {ct}")
            else:
                parts.append(f"Q{pre.quarter}")
        elif _clock_token():
            parts.append(_clock_token())
        lbl = _special_teams_label(r)
        fld = _field_position_segment(pre)
        if fld:
            parts.append(f"{lbl} from {fld.replace('*', '').strip()}")
        elif lbl:
            parts.append(lbl)
        if pre.home_score_snap is not None and pre.away_score_snap is not None:
            parts.append(f"{pre.home_score_snap}–{pre.away_score_snap}")
        return " · ".join(parts) if parts else ""

    if st_err == REPLAY_UNAVAILABLE:
        return ""

    if pre.quarter and pre.quarter > 0:
        ct = _clock_token()
        if ct:
            parts.append(f"Q{pre.quarter} {ct}")
        else:
            parts.append(f"Q{pre.quarter}" + _provenance_tag(pre, "quarter"))
    elif _clock_token():
        parts.append(_clock_token())

    dd = _down_distance_segment(pre)
    if dd:
        parts.append(dd)
    fld = _field_position_segment(pre)
    if fld:
        parts.append(fld)
    if pre.home_score_snap is not None and pre.away_score_snap is not None:
        parts.append(f"{pre.home_score_snap}–{pre.away_score_snap}")
    elif pre.score_diff != 0:
        parts.append(f"diff {pre.score_diff:+d}")
    has_time = bool(pre.quarter and pre.quarter > 0) or bool(_clock_token())
    has_sit = bool(dd or fld)
    has_score = pre.home_score_snap is not None and pre.away_score_snap is not None
    if not has_time and not has_sit and not has_score:
        return "— · unknown situation"
    return " · ".join(parts) if parts else "— · unknown situation"


def _render_comparison_breakdown(
    r: ActualVsReplayComparisonRow,
    *,
    widget_key_prefix: str,
) -> None:
    """Readable fields only (no raw JSON). Nested expanders are avoided — checkbox toggles body."""
    key = f"{widget_key_prefix}_breakdown_p{r.play_index}"
    if not st.checkbox("Breakdown", key=key, value=False):
        return
    pre = r.pre_snap_context
    m = r.model_replay_structured
    conf = m.confidence if m is not None else None
    conf_s = f"{conf:.0%}" if conf is not None else "—"
    qclk = "—"
    if pre.quarter and pre.quarter > 0:
        if pre.clock_display:
            qclk = f"Q{pre.quarter} · {html.escape(pre.clock_display)}"
        elif pre.seconds_remaining is not None:
            sr = int(pre.seconds_remaining)
            qclk = f"Q{pre.quarter} · {sr // 60}:{sr % 60:02d} in period"
        else:
            qclk = f"Q{pre.quarter}"
    prov_lines = ""
    if pre.snap_provenance:
        prov_lines = "**Sources:** " + ", ".join(f"{k}={v}" for k, v in pre.snap_provenance)
    dd_line = "—"
    if pre.down is not None:
        dd_line = _down_distance_segment(pre) or f"{pre.down} & {pre.distance if pre.distance is not None else '—'}"
    fld_line = _field_position_segment(pre) or "—"
    st.markdown(
        f"- **actual_bucket:** `{html.escape(r.actual_summary_bucket or '—')}`\n"
        f"- **replay_bucket:** `{html.escape(r.replay_summary_bucket or '—')}`\n"
        f"- **down / distance:** {html.escape(dd_line)}\n"
        f"- **field:** {html.escape(fld_line)}\n"
        f"- **goal-to-go:** {'yes' if pre.goal_to_go else 'no'}\n"
        f"- **quarter / clock:** {qclk}\n"
        f"- **run/pass:** actual `{r.actual_run_pass or '—'}` · replay `{r.model_run_pass or '—'}`\n"
        f"- **matches:** run/pass `{r.run_pass_match}` · bucket `{r.coarse_bucket_match}` · family `{r.family_match}`\n"
        f"- **replay confidence:** {conf_s}\n"
    )
    if prov_lines:
        st.caption(prov_lines)
    st.caption("Replay is **retroactive** only — not stored Generate-time truth.")


def render_drive_archive_with_replay(
    game: Game,
    *,
    predictor: FootballPlayPredictor,
    ambient_ctx: GameContext,
) -> None:
    if not game.drives:
        return
    st.markdown(f"### {SECTION_DRIVE_ARCHIVE}")
    st.caption(
        "Completed possessions this session — **audit is an overlay** on the same chron drives as the table below."
    )
    st.caption(CAPTION_POST_DRIVE_REPLAY)
    our_tid = coached_team_espn_id_for_previous_drives(st.session_state)

    audit_report = compute_drive_audit(game)
    audit_by_index = {r.drive_index: r for r in audit_report.rows}

    show_all, chip = render_shared_drive_audit_lens_controls(audit_report)

    mode = str(st.session_state.get(LIVE_FEED_TEAM_SCOPE) or PREVIOUS_DRIVES_FILTER_OUR).strip().lower()
    if mode not in (PREVIOUS_DRIVES_FILTER_OUR, PREVIOUS_DRIVES_FILTER_OPPONENT, PREVIOUS_DRIVES_FILTER_BOTH):
        mode = PREVIOUS_DRIVES_FILTER_OUR

    indices = filter_previous_drive_indices(game, mode=mode, our_coached_espn_id=our_tid)
    archived_filtered = filter_archived_indices_by_audit_lens(
        base_indices=indices,
        report=audit_report,
        show_all=show_all,
        chip=chip,
    )

    render_drive_score_ribbon(audit_report)
    render_score_reconciliation_strip(game, audit_report)

    st.caption(
        "Team list filtering follows **Feed team scope** in the sidebar (ESPN / live feed), then the **integrity lens**."
    )
    st.caption(f"**{len(archived_filtered)}** drive card(s) after feed scope + lens (chron **#** matches audit table).")

    focus_chron = render_drive_focus_link(
        audit_by_index=audit_by_index,
        archived_indices_filtered=archived_filtered if indices else [],
    )

    if not indices:
        st.info(previous_drives_empty_filter_message(mode))
        render_drive_audit_panel(audit_report)
        return

    if (
        mode != PREVIOUS_DRIVES_FILTER_BOTH
        and not our_tid
        and any(str(getattr(dr, "feed_team_espn_id", "") or "").strip() for dr in game.drives)
    ):
        st.caption(
            "Feed drives need the **coached team** from ESPN (sync once). "
            "Until then, use **Both teams** or complete team identification."
        )

    if not archived_filtered:
        st.info(
            "No archived drives match the current **integrity lens**. "
            "Try **Show all drives** or set the lens to **All** / **Clean**."
        )
        render_drive_audit_panel(audit_report)
        return

    seq = chronological_team_drive_indices(game)
    for chron_i in reversed(archived_filtered):
        dr = game.drives[chron_i]
        team_drive_n = seq[chron_i]
        ar = audit_by_index.get(chron_i)
        base_title = (
            archived_drive_expander_title_from_audit(dr, team_drive_n, ar)
            if ar
            else prior_drive_heading(dr, team_drive_n)
        )
        tag = audit_status_header_tag(ar) if ar else ""
        badge = f"{ar.badge} " if ar else ""
        bracket = f"[{tag}] · " if ar else ""
        label = f"{badge}{bracket}{base_title}"
        expanded = bool(ar and focus_chron == ar.chron_drive_number)
        with st.expander(label, expanded=expanded):
            if ar:
                _render_archived_drive_audit_block(ar, report=audit_report)
            if getattr(dr, "feed_import_tag", None) == "espn":
                st.caption("Source: ESPN completed possession import.")
            if not dr.plays:
                st.caption("No plays recorded.")
            else:
                if ar:
                    st.divider()
                st.caption(
                    "**Field & scrimmage down/distance** — reconstructed from the play sequence (touchback anchors). "
                    "**Quarter & game clock** — ESPN per-play feed when available; otherwise drive start or estimates "
                    "(Breakdown shows sources). Defensive read & weather — **current console** overlay."
                )
                rows = cached_comparison_rows_for_archived_drive(
                    st.session_state,
                    drive=dr,
                    drive_index=chron_i,
                    game=game,
                    ambient_ctx=ambient_ctx,
                    predictor=predictor,
                    plays=dr.plays,
                )
                _render_comparison_table(rows, widget_key_prefix=f"prev_drv_{chron_i}")

    render_drive_audit_panel(audit_report)


def _render_comparison_table(
    rows: list[ActualVsReplayComparisonRow],
    *,
    widget_key_prefix: str,
) -> None:
    h1, h2, h3 = st.columns([0.45, 5.6, 4])
    with h1:
        st.caption("")
    with h2:
        st.markdown("**Actual**")
    with h3:
        st.markdown("**Model replay (current engine)**")

    for r in rows:
        c0, c1, c2 = st.columns([0.45, 5.6, 4])
        with c0:
            st.markdown(f"{r.play_index}.")
        with c1:
            ctx = _compact_snap_context_line(r)
            ctx_html = (
                f'<div style="font-size:11px;font-family:ui-monospace,Menlo,monospace;color:#94a3b8;margin-bottom:4px">'
                f"{html.escape(ctx)}</div>"
                if ctx
                else ""
            )
            primary = html.escape(r.actual_play_summary_primary)
            detail = html.escape(r.actual_play_summary_detail) if r.actual_play_summary_detail else ""
            detail_html = (
                f'<div style="font-size:11px;color:#94a3b8;margin-top:2px">{detail}</div>'
                if detail
                else ""
            )
            badges = []
            if r.actual_run_pass:
                badges.append(html.escape(r.actual_run_pass))
            if r.run_pass_match is True:
                badges.append('<span style="color:#4ade80">RP match</span>')
            elif r.run_pass_match is False:
                badges.append('<span style="color:#f87171">RP diff</span>')
            if r.family_match is True:
                badges.append('<span style="color:#4ade80">Family match</span>')
            elif r.family_match is False:
                badges.append('<span style="color:#fbbf24">Family diff</span>')
            if r.coarse_bucket_match is True:
                badges.append('<span style="color:#4ade80">Scheme bucket match</span>')
            elif r.coarse_bucket_match is False:
                badges.append('<span style="color:#fbbf24">Scheme bucket diff</span>')
            ab = html.escape(r.actual_summary_bucket) if r.actual_summary_bucket else ""
            if ab:
                badges.insert(0, f'<span style="color:#94a3b8">Actual: {ab}</span>')
            badge_row = (
                f'<div style="font-size:10px;margin-top:4px">{" · ".join(badges)}</div>' if badges else ""
            )
            st.markdown(
                f"{ctx_html}"
                f'<div style="font-size:13px;line-height:1.35;color:#e2e8f0">{primary}</div>'
                f"{detail_html}{badge_row}",
                unsafe_allow_html=True,
            )
            _render_comparison_breakdown(r, widget_key_prefix=widget_key_prefix)
        with c2:
            if r.replay_error:
                st.markdown(
                    f'<span style="font-size:12px;color:#94a3b8">{html.escape(r.replay_error)}</span>',
                    unsafe_allow_html=True,
                )
            else:
                m = r.model_replay_structured
                bucket = html.escape(m.summary_bucket) if m and m.summary_bucket else ""
                lead = bucket or (html.escape(m.run_pass) if m and m.run_pass else "")
                sub_parts: list[str] = []
                if m:
                    if m.play_family:
                        sub_parts.append(html.escape(m.play_family.replace("_", " ")))
                    if m.play_call_name:
                        sub_parts.append(html.escape(f"“{m.play_call_name}”"))
                    if m.run_pass and bucket:
                        sub_parts.append(html.escape(m.run_pass))
                    if m.confidence is not None:
                        sub_parts.append(html.escape(f"{m.confidence:.0%} conf"))
                sub = " · ".join(sub_parts)
                extra = html.escape(r.model_replay_summary) if r.model_replay_summary and not lead else ""
                st.markdown(
                    f'<div style="font-size:13px;font-weight:600;color:#38bdf8">{lead or extra}</div>'
                    f'<div style="font-size:11px;color:#cbd5e1;margin-top:2px">{sub if lead else (sub or extra)}</div>',
                    unsafe_allow_html=True,
                )

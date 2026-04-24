"""Streamlit: warehouse game inventory and single-game review (via FootballWarehouseClient only)."""

from __future__ import annotations

import html
import traceback
from datetime import datetime, timezone

import streamlit as st

from football_history_warehouse.consumer import FootballWarehouseClient, GameInventoryFilters, PageParams

from playcaller.ui.product_copy import WAREHOUSE_PAGE_INTRO
from playcaller.ui.warehouse_page_state import (
    WarehouseInventoryState,
    WarehousePageContext,
    detect_warehouse_inventory_state,
    render_warehouse_status_banner,
    warehouse_dev_mode_enabled,
)


def _score_cell(h: int | None, a: int | None) -> str:
    if h is None and a is None:
        return "—"
    return f"{h if h is not None else '?'} – {a if a is not None else '?'}"


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def render_warehouse_inventory_page() -> None:
    st.title("Warehouse — loaded games")
    st.markdown(WAREHOUSE_PAGE_INTRO)

    ctx = detect_warehouse_inventory_state()
    render_warehouse_status_banner(ctx)

    if ctx.state == WarehouseInventoryState.NOT_CONFIGURED:
        return
    if ctx.state == WarehouseInventoryState.SCHEMA_NOT_INITIALIZED:
        if ctx.client is not None:
            ctx.client.dispose()
        return
    if ctx.state == WarehouseInventoryState.QUERY_FAILED:
        if ctx.client is not None:
            ctx.client.dispose()
        return

    client = ctx.client
    assert client is not None

    try:
        _render_warehouse_inventory_body(ctx, client)
    finally:
        client.dispose()


def _render_warehouse_inventory_body(ctx: WarehousePageContext, client: FootballWarehouseClient) -> None:
    st.info(
        "Counts and samples in **Generate → warehouse advisory** are **exploratory**. "
        "Thin imports (few plays) are **not** league truth — use this page to see what is actually loaded.",
        icon="ℹ️",
    )

    with st.form("wh_inventory_filters"):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.text_input("League id (optional)", key="wh_f_league")
        with c2:
            st.text_input("Season id (optional)", key="wh_f_season")
        with c3:
            st.text_input("Team id — home or away (optional)", key="wh_f_team")
        c4, c5 = st.columns(2)
        with c4:
            st.text_input("Import job id (optional)", key="wh_f_job")
        with c5:
            st.number_input("Page size", min_value=1, max_value=500, value=100, step=10, key="wh_f_limit")
        filters_submitted = st.form_submit_button("Apply filters")

    if filters_submitted:
        st.session_state["wh_inventory_offset"] = 0

    league = str(st.session_state.get("wh_f_league") or "").strip()
    season = str(st.session_state.get("wh_f_season") or "").strip()
    team = str(st.session_state.get("wh_f_team") or "").strip()
    job = str(st.session_state.get("wh_f_job") or "").strip()
    limit = int(st.session_state.get("wh_f_limit") or 100)
    limit_clamped = min(500, max(1, limit))
    offset = max(0, int(st.session_state.get("wh_inventory_offset") or 0))

    filt = GameInventoryFilters(
        league_id=league or None,
        season_id=season or None,
        team_id=team or None,
        import_job_id=job or None,
    )
    has_filters = bool(league or season or team or job)
    try:
        page = client.list_games_inventory(filt, page=PageParams(limit=limit_clamped, offset=offset))
    except Exception as e:
        detail = html.escape(f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else '(no message)'}")
        st.markdown(
            '<div style="padding:0.75rem 1rem;border-radius:6px;border-left:6px solid #c62828;'
            'background:#fff5f5;margin-bottom:1rem;">'
            '<p style="margin:0 0 0.5rem 0;"><strong>🔴 Query failed</strong> (inventory list)</p>'
            f'<p style="margin:0;font-family:ui-monospace,monospace;font-size:0.9rem;">{detail}</p></div>',
            unsafe_allow_html=True,
        )
        if warehouse_dev_mode_enabled():
            with st.expander("Full traceback (PLAYCALLER_DEV_MODE)", expanded=False):
                st.code(traceback.format_exc())
        else:
            st.caption("Set **`PLAYCALLER_DEV_MODE=1`** to show the full traceback here.")
        return

    rows = []
    for g in page.games:
        rows.append(
            {
                "game_id": g.game_id,
                "league": g.league_name,
                "season": g.season_year_label,
                "when": _fmt_dt(g.scheduled_start_utc),
                "home": g.home_team_name,
                "away": g.away_team_name,
                "score": _score_cell(g.home_score_final, g.away_score_final),
                "status": g.status,
                "drives": g.drive_count,
                "plays": g.play_count,
                "import_job": g.import_job_id or "—",
                "imported": _fmt_dt(g.imported_at),
                "source_hint": g.source_artifact_hint or "—",
            }
        )
    if not rows:
        if has_filters:
            st.warning("No games match the current filters.")
        elif ctx.state == WarehouseInventoryState.EMPTY:
            pass
        else:
            st.warning("No games match the current filters (or the warehouse is empty).")
    else:
        start_row = offset + 1
        end_row = offset + len(rows)
        more_hint = " · more on next page" if page.has_more else ""
        st.caption(f"Rows **{start_row}–{end_row}** on this page ({len(rows)} game(s)){more_hint}.")
        st.dataframe(rows, use_container_width=True)

    p1, p2, p3 = st.columns([1, 1, 4])
    with p1:
        if st.button("← Previous page", disabled=offset <= 0, key="wh_inventory_prev"):
            st.session_state["wh_inventory_offset"] = max(0, offset - limit_clamped)
            st.rerun()
    with p2:
        if st.button("Next page →", disabled=not page.has_more, key="wh_inventory_next"):
            st.session_state["wh_inventory_offset"] = offset + limit_clamped
            st.rerun()
    with p3:
        page_num = offset // limit_clamped + 1
        st.caption(f"Offset **{offset}** · page size **{limit_clamped}** · page **{page_num}**")

    st.subheader("Game detail")
    ids = [g.game_id for g in page.games]
    if not ids:
        st.caption("Load at least one game to inspect detail.")
        return
    pick = st.selectbox("Select game_id", options=ids, key="wh_pick_game")
    try:
        pkg = client.get_game_review_package(str(pick))
    except Exception as e:
        detail = html.escape(f"{type(e).__name__}: {str(e).splitlines()[0] if str(e) else '(no message)'}")
        st.markdown(
            '<div style="padding:0.75rem 1rem;border-radius:6px;border-left:6px solid #c62828;'
            'background:#fff5f5;margin-bottom:1rem;">'
            '<p style="margin:0 0 0.5rem 0;"><strong>🔴 Query failed</strong> (game review package)</p>'
            f'<p style="margin:0;font-family:ui-monospace,monospace;font-size:0.9rem;">{detail}</p></div>',
            unsafe_allow_html=True,
        )
        if warehouse_dev_mode_enabled():
            with st.expander("Full traceback (PLAYCALLER_DEV_MODE)", expanded=False):
                st.code(traceback.format_exc())
        else:
            st.caption("Set **`PLAYCALLER_DEV_MODE=1`** to show the full traceback here.")
        return
    if pkg is None:
        st.warning("No review package for that game id.")
        return

    summ = pkg.matchup
    sc = pkg.score
    st.markdown(
        f"**{summ.home.full_name}** vs **{summ.away.full_name}** · {summ.league_name or summ.league_id} · "
        f"season {summ.season_year_label or summ.season_id}"
    )
    hp = sc.home_points if sc.home_points is not None else "—"
    ap = sc.away_points if sc.away_points is not None else "—"
    st.caption(
        f"Status **{pkg.summary.status}** · "
        f"score home **{hp}** away **{ap}** "
        f"({'final on record' if sc.is_final_on_record else 'not final'})"
    )
    with st.expander("Full review package (JSON)", expanded=False):
        st.json(pkg.model_dump(mode="json"))

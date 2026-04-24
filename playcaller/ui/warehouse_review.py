"""Streamlit: warehouse game inventory and single-game review (via FootballWarehouseClient only)."""

from __future__ import annotations

import html
import traceback
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from football_history_warehouse.consumer import FootballWarehouseClient, GameInventoryFilters, PageParams

from playcaller.ui.product_copy import REVIEW_WAREHOUSE_EMPTY_PROCESSED, WAREHOUSE_PAGE_INTRO
from playcaller.ui.warehouse_page_state import (
    WarehouseInventoryState,
    WarehousePageContext,
    detect_warehouse_inventory_state,
    render_warehouse_status_banner,
    warehouse_dev_mode_enabled,
)
from warehouse.audit import (
    AuditSummary,
    audit_processed,
    discover_processed_json_paths,
    filter_affected_files,
    filtered_issue_totals,
)
from warehouse.storage import REPO_ROOT, processed_data_dir


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


def _wh_audit_init_filter_keys() -> None:
    if "wh_audit_filter_season" not in st.session_state:
        st.session_state["wh_audit_filter_season"] = "all"
    if "wh_audit_filter_week" not in st.session_state:
        st.session_state["wh_audit_filter_week"] = "all"
    if "wh_audit_filter_rules" not in st.session_state:
        st.session_state["wh_audit_filter_rules"] = []
    if "wh_audit_filter_search" not in st.session_state:
        st.session_state["wh_audit_filter_search"] = ""
    if "wh_audit_refresh_nonce" not in st.session_state:
        st.session_state["wh_audit_refresh_nonce"] = 0


def _processed_json_scan_fingerprint(
    root: Path,
    *,
    season: int | None,
    week: int | None,
) -> tuple[int, float]:
    """Stat-only token for cache invalidation: file count and max mtime in scan scope."""
    paths = discover_processed_json_paths(root, season=season, week=week)
    if not paths:
        try:
            mt = float(root.stat().st_mtime) if root.is_dir() else 0.0
        except OSError:
            mt = 0.0
        return (0, mt)
    mt = 0.0
    for p in paths:
        try:
            m = p.stat().st_mtime
        except OSError:
            m = 0.0
        if m > mt:
            mt = m
    return (len(paths), mt)


def _get_cached_audit_summary(
    root: Path,
    *,
    season: int | None,
    week: int | None,
) -> AuditSummary:
    """Return ``audit_processed`` result, reusing session cache when key + disk stamp match."""
    root_s = str(root.resolve())
    fp = _processed_json_scan_fingerprint(root, season=season, week=week)
    nonce = int(st.session_state.get("wh_audit_refresh_nonce") or 0)
    entry = st.session_state.get("wh_audit_cache_entry")
    if isinstance(entry, dict):
        if (
            entry.get("root") == root_s
            and entry.get("season") == season
            and entry.get("week") == week
            and entry.get("fingerprint") == fp
            and entry.get("nonce") == nonce
            and isinstance(entry.get("summary"), AuditSummary)
        ):
            return entry["summary"]
    summary = audit_processed(root, season=season, week=week)
    st.session_state["wh_audit_cache_entry"] = {
        "root": root_s,
        "season": season,
        "week": week,
        "fingerprint": fp,
        "nonce": nonce,
        "summary": summary,
    }
    return summary


def _rel_repo_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def _render_processed_json_audit_panel() -> None:
    """Inventory + validation/quality audit over ``data/processed`` (fixtures for Review Session)."""
    st.subheader("Processed JSON audit")
    st.markdown(
        "This section shows **processed JSON** under `data/processed/`. "
        "It is the same fixture source **Review Session** uses for nflverse games, "
        "but here you get **validation + quality** counts — not play-by-play review."
    )
    _wh_audit_init_filter_keys()
    root = processed_data_dir()
    if not root.is_dir():
        st.warning(REVIEW_WAREHOUSE_EMPTY_PROCESSED)
        return

    seasons = sorted(int(p.name) for p in root.iterdir() if p.is_dir() and p.name.isdigit())
    season_opts = ["all"] + [str(s) for s in seasons]
    c1, c2, c3 = st.columns(3)
    with c1:
        st.selectbox(
            "Processed season folder",
            options=season_opts,
            key="wh_audit_filter_season",
            help="Maps to `data/processed/{season}/`. 'all' scans every season directory.",
        )
    season_s = str(st.session_state["wh_audit_filter_season"])
    week_opts = ["all"]
    if season_s != "all":
        s_int = int(season_s)
        wroot = root / str(s_int)
        if wroot.is_dir():
            for wd in sorted(wroot.glob("week_*")):
                if wd.is_dir() and wd.name.startswith("week_") and wd.name[5:].isdigit():
                    week_opts.append(str(int(wd.name[5:])))
    with c2:
        st.selectbox(
            "Processed week folder",
            options=week_opts,
            key="wh_audit_filter_week",
            help="Maps to `week_{nn}` under the selected season. Requires a specific season.",
            disabled=season_s == "all",
        )
        if st.button(
            "Refresh audit",
            key="wh_audit_refresh",
            help="Re-scan all JSON in this filter on disk. Also use after editing files outside the app.",
        ):
            st.session_state["wh_audit_refresh_nonce"] = int(st.session_state.get("wh_audit_refresh_nonce") or 0) + 1
            st.rerun()
    season_f: int | None = None
    week_f: int | None = None
    if season_s != "all":
        season_f = int(season_s)
        wk_s = str(st.session_state["wh_audit_filter_week"])
        if wk_s != "all":
            week_f = int(wk_s)

    summary = _get_cached_audit_summary(root, season=season_f, week=week_f)
    rule_options = sorted({ic.rule_name for ic in summary.counts_by_rule})
    with c3:
        st.multiselect(
            "Issue rules (optional filter)",
            options=rule_options,
            key="wh_audit_filter_rules",
            help="When set, validation/quality metrics and the table only include these rule names.",
        )
    st.text_input(
        "Game / path search",
        key="wh_audit_filter_search",
        help="Case-insensitive substring on file path, internal game id, or external_game_id. Filters the table only.",
    )

    if summary.total_files == 0:
        st.info(
            "No processed JSON files match this scan "
            f"(season={season_f}, week={week_f}). "
            "Clear season/week filters to include all `data/processed` trees."
        )
        return

    d = summary.diagnostics
    if d is not None:
        st.subheader("Data health insights")
        if d.health_signal == "healthy":
            st.success(d.health_summary)
        elif d.health_signal == "degraded":
            st.error(d.health_summary)
        else:
            st.warning(d.health_summary)
        if d.top_suspicious:
            st.caption("Top suspicious games")
            st.dataframe(
                [
                    {
                        "game_id": t.game_id,
                        "score": t.score,
                        "top reason": t.reasons[0] if t.reasons else "—",
                    }
                    for t in d.top_suspicious
                ],
                use_container_width=True,
                hide_index=True,
            )
        with st.expander("Rule hygiene", expanded=False):
            st.dataframe(
                [
                    {
                        "rule": h.rule_name,
                        "category": h.category,
                        "classification": h.classification,
                        "pct_games": h.pct_games,
                    }
                    for h in d.rule_hygiene
                ],
                use_container_width=True,
                hide_index=True,
            )
        with st.expander("Completeness gaps", expanded=False):
            st.dataframe(
                [
                    {
                        "field": c.field,
                        "required": c.required,
                        "missing_rows": c.missing_rows,
                        "pct_missing": c.pct_missing,
                        "affected_games": c.affected_games,
                    }
                    for c in d.completeness
                ],
                use_container_width=True,
                hide_index=True,
            )
        st.caption("play_type mix (this scan)")
        st.dataframe(
            [{"play_type": n, "count": c} for n, c in d.play_type_counts],
            use_container_width=True,
            hide_index=True,
        )
        cdm1, cdm2, cdm3 = st.columns(3)
        with cdm1:
            st.metric("Plays / game (median)", f"{d.plays_per_game.median:.1f}")
            st.caption(f"p95: {d.plays_per_game.p95:.1f}")
        with cdm2:
            st.metric("Drives / game (median)", f"{d.drives_per_game.median:.1f}")
            st.caption(f"p95: {d.drives_per_game.p95:.1f}")
        with cdm3:
            st.metric("Yards gained / play (median)", f"{d.yards_gained.median:.1f}")
            st.caption(f"max: {d.yards_gained.max:.1f}")
        st.divider()

    rules_sel = st.session_state.get("wh_audit_filter_rules") or []
    rule_fset = frozenset(str(r) for r in rules_sel) if rules_sel else None
    v_tot, q_tot = filtered_issue_totals(summary, rule_filter=rule_fset)
    search_t = str(st.session_state.get("wh_audit_filter_search") or "")
    rows = filter_affected_files(summary, rule_filter=rule_fset, search_text=search_t)
    if rules_sel or search_t.strip():
        st.caption(
            "Games / plays / drives reflect the full scan; validation and quality totals follow the rule filter. "
            "Path search narrows the table only."
        )

    specs: list[tuple[str, int, str | None]] = [
        ("Games (loaded OK)", summary.total_games, None),
        ("Plays", summary.total_plays, None),
    ]
    if summary.total_drives is not None:
        specs.append(
            (
                "Σ max(drive #) / game",
                summary.total_drives,
                "Sum of max `drive_number` per loaded game (quick corpus size hint).",
            )
        )
    specs.extend(
        [
            ("Validation issues", v_tot, None),
            ("Quality issues", q_tot, None),
        ]
    )
    cols = st.columns(len(specs))
    for i, col in enumerate(cols):
        label, val, h = specs[i]
        with col:
            st.metric(label, val, help=h)

    if summary.load_errors:
        with st.expander(f"Load errors ({len(summary.load_errors)})", expanded=False):
            for p, msg in summary.load_errors:
                st.text(f"{p}: {msg}")

    st.caption("Counts by rule (verbatim names)")
    st.dataframe(
        [
            {"category": ic.category, "rule_name": ic.rule_name, "count": ic.count}
            for ic in summary.counts_by_rule
            if not rule_fset or ic.rule_name in rule_fset
        ],
        use_container_width=True,
        hide_index=True,
    )

    if not rows and summary.affected_files and (rules_sel or search_t.strip()):
        st.warning(
            "No files match the current table filters "
            f"(rules={rules_sel or 'all'}, search={search_t!r}). "
            "Clear filters to see all files with issues."
        )
    elif rows:
        st.caption("Files with issues (sorted by issue count)")
        st.dataframe(
            [
                {
                    "path": _rel_repo_path(af.path),
                    "game_id": af.game_id,
                    "external_game_id": af.external_game_id,
                    "validation": af.validation_count,
                    "quality": af.quality_count,
                    "rules": ", ".join(f"{k}={v}" for k, v in sorted(af.issue_counts_by_rule.items())),
                }
                for af in rows
            ],
            use_container_width=True,
            hide_index=True,
        )
    elif not summary.affected_files:
        st.success("No validation or quality issues in this scan.")


def render_warehouse_inventory_page() -> None:
    st.title("Warehouse — loaded games")
    _render_processed_json_audit_panel()
    st.divider()
    st.markdown(WAREHOUSE_PAGE_INTRO)
    st.markdown(
        "**Below:** **DB-backed inventory** in the football history warehouse. "
        "It is **not** the same as `data/processed/` above. "
        "A game listed here with **0 plays** is metadata-only in that DB and is **not** review-ready there."
    )

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

"""
Warehouse inventory page: classify DB readiness into explicit operator-facing states.

Detection runs a lightweight schema probe (``games`` table + row count). Inventory
queries are not executed here except indirectly via the same engine the page uses.
"""

from __future__ import annotations

import html
import os
import traceback
from dataclasses import dataclass
from enum import IntEnum

from sqlalchemy import inspect, text

from football_history_warehouse.config.database import resolve_warehouse_database_url
from football_history_warehouse.config.exceptions import WarehouseConfigError
from football_history_warehouse.consumer.client import FootballWarehouseClient


class WarehouseInventoryState(IntEnum):
    NOT_CONFIGURED = 1
    SCHEMA_NOT_INITIALIZED = 2
    EMPTY = 3
    POPULATED = 4
    QUERY_FAILED = 5


@dataclass(frozen=True)
class WarehousePageContext:
    state: WarehouseInventoryState
    client: FootballWarehouseClient | None = None
    game_count: int | None = None
    exc_type: str | None = None
    exc_message_first_line: str | None = None
    traceback_text: str | None = None
    used_dev_fallback: bool = False


def _first_line(msg: str) -> str:
    s = (msg or "").strip()
    if not s:
        return "(no message)"
    return s.splitlines()[0]


def detect_warehouse_inventory_state() -> WarehousePageContext:
    """
    Return the current warehouse inventory state and optional live client.

    * State 1 — no resolved URL (env unset and no dev-mode SQLite fallback).
    * State 2 — URL set, engine usable, ``games`` table missing (run migrations).
    * State 3 — ``games`` exists, count is 0.
    * State 4 — at least one game row.
    * State 5 — connection, reflection, or count failed (schema mismatch, corrupt DB, etc.).

    Exceptions during detection are captured as state 5 with traceback text for dev display.
    """
    url, used_dev_fallback = resolve_warehouse_database_url()
    if not url:
        return WarehousePageContext(state=WarehouseInventoryState.NOT_CONFIGURED, client=None)

    client: FootballWarehouseClient | None = None
    try:
        client = FootballWarehouseClient.from_env()
        engine = client._engine
        insp = inspect(engine)
        if not insp.has_table("games"):
            return WarehousePageContext(
                state=WarehouseInventoryState.SCHEMA_NOT_INITIALIZED,
                client=client,
                used_dev_fallback=used_dev_fallback,
            )
        with engine.connect() as conn:
            n = conn.execute(text("SELECT COUNT(*) FROM games")).scalar_one()
        count = int(n)
        if count == 0:
            return WarehousePageContext(
                state=WarehouseInventoryState.EMPTY,
                client=client,
                game_count=0,
                used_dev_fallback=used_dev_fallback,
            )
        return WarehousePageContext(
            state=WarehouseInventoryState.POPULATED,
            client=client,
            game_count=count,
            used_dev_fallback=used_dev_fallback,
        )
    except WarehouseConfigError:
        return WarehousePageContext(state=WarehouseInventoryState.NOT_CONFIGURED, client=None)
    except Exception as e:  # noqa: BLE001 — intentional: surface as state 5 for operators
        tb = traceback.format_exc()
        return WarehousePageContext(
            state=WarehouseInventoryState.QUERY_FAILED,
            client=client,
            exc_type=type(e).__name__,
            exc_message_first_line=_first_line(str(e)),
            traceback_text=tb,
            used_dev_fallback=used_dev_fallback,
        )


def warehouse_dev_mode_enabled() -> bool:
    return str(os.environ.get("PLAYCALLER_DEV_MODE") or "").strip().lower() in ("1", "true", "yes")


def format_warehouse_sidebar_pill_html(ctx: WarehousePageContext) -> str:
    """
    Compact single-line pill for Game Setup (matches :func:`detect_warehouse_inventory_state` semantics).
    """
    dev_suffix = " · dev fallback" if ctx.used_dev_fallback else ""
    base = "display:inline-block;padding:4px 12px;border-radius:999px;font-size:12px;font-weight:600;"
    if ctx.state == WarehouseInventoryState.NOT_CONFIGURED:
        label = "🔴 Not configured"
        style = f"{base}background:#450a0a;color:#fecaca;"
        title = ""
    elif ctx.state == WarehouseInventoryState.SCHEMA_NOT_INITIALIZED:
        label = f"🟡 Schema not initialized{dev_suffix}"
        style = f"{base}background:#713f12;color:#fef9c3;"
        title = ""
    elif ctx.state == WarehouseInventoryState.EMPTY:
        label = f"🟡 Empty (no games){dev_suffix}"
        style = f"{base}background:#713f12;color:#fef9c3;"
        title = ""
    elif ctx.state == WarehouseInventoryState.POPULATED:
        n = ctx.game_count if ctx.game_count is not None else 0
        label = f"🟢 {n} game{'s' if n != 1 else ''} archived{dev_suffix}"
        style = f"{base}background:#14532d;color:#bbf7d0;"
        title = ""
    else:
        detail = f"{ctx.exc_type or 'Error'}: {ctx.exc_message_first_line or '(no message)'}"
        label = f"🔴 Query failed{dev_suffix}"
        style = f"{base}background:#450a0a;color:#fecaca;"
        title = html.escape(detail, quote=True)
    esc_label = html.escape(label)
    title_attr = f' title="{title}"' if title else ""
    return f'<span style="{html.escape(style, quote=True)}"{title_attr}>{esc_label}</span>'


def render_warehouse_status_banner(ctx: WarehousePageContext) -> None:
    """Single consistent alert strip for all five states (markdown + inline HTML)."""
    import streamlit as st

    from playcaller.ui import product_copy as pc

    # Border colors aligned with severity; background kept light for readability.
    if ctx.state == WarehouseInventoryState.NOT_CONFIGURED:
        border, bg = "#c62828", "#fff5f5"
        pill = "🔴 Not configured"
        body = (
            f'<p style="margin:0 0 0.5rem 0;"><strong>{html.escape(pill)}</strong></p>'
            f'<p style="margin:0;">{html.escape(pc.WAREHOUSE_STATUS_ACTION_NOT_CONFIGURED)}</p>'
            f'<p style="margin:0.5rem 0 0 0;">{html.escape(pc.WAREHOUSE_STATUS_DOC_HINT)}</p>'
        )
    elif ctx.state == WarehouseInventoryState.SCHEMA_NOT_INITIALIZED:
        border, bg = "#f9a825", "#fffdf5"
        pill = "🟡 Schema not initialized"
        if ctx.used_dev_fallback:
            pill += " · dev fallback"
        body = (
            f'<p style="margin:0 0 0.5rem 0;"><strong>{html.escape(pill)}</strong></p>'
            f'<p style="margin:0;">{html.escape(pc.WAREHOUSE_STATUS_ACTION_SCHEMA)}</p>'
        )
    elif ctx.state == WarehouseInventoryState.EMPTY:
        border, bg = "#f9a825", "#fffdf5"
        pill = "🟡 Empty"
        if ctx.used_dev_fallback:
            pill += " · dev fallback"
        body = (
            f'<p style="margin:0 0 0.5rem 0;"><strong>{html.escape(pill)}</strong></p>'
            f'<p style="margin:0;">{html.escape(pc.WAREHOUSE_STATUS_ACTION_EMPTY)}</p>'
        )
    elif ctx.state == WarehouseInventoryState.POPULATED:
        border, bg = "#2e7d32", "#f4fff5"
        n = ctx.game_count if ctx.game_count is not None else 0
        pill = f"🟢 Connected · {n} game{'s' if n != 1 else ''} archived"
        if ctx.used_dev_fallback:
            pill += " · dev fallback"
        body = f'<p style="margin:0;"><strong>{html.escape(pill)}</strong></p>'
    else:
        border, bg = "#c62828", "#fff5f5"
        pill = "🔴 Query failed"
        if ctx.used_dev_fallback:
            pill += " · dev fallback"
        detail = html.escape(f"{ctx.exc_type or 'Error'}: {ctx.exc_message_first_line or '(no message)'}")
        body = (
            f'<p style="margin:0 0 0.5rem 0;"><strong>{html.escape(pill)}</strong></p>'
            f'<p style="margin:0;font-family:ui-monospace,monospace;font-size:0.9rem;">{detail}</p>'
            f'<p style="margin:0.5rem 0 0 0;">{html.escape(pc.WAREHOUSE_STATUS_ACTION_QUERY_FAILED)}</p>'
        )

    st.markdown(
        f'<div style="padding:0.75rem 1rem;border-radius:6px;border-left:6px solid {border};'
        f"background:{bg};margin-bottom:1rem;\">{body}</div>",
        unsafe_allow_html=True,
    )

    if ctx.state == WarehouseInventoryState.QUERY_FAILED and ctx.traceback_text:
        if warehouse_dev_mode_enabled():
            with st.expander("Full traceback (PLAYCALLER_DEV_MODE)", expanded=False):
                st.code(ctx.traceback_text)
        else:
            st.caption("Set **`PLAYCALLER_DEV_MODE=1`** to show the full traceback here.")

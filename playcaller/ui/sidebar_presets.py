"""Sidebar snap presets: built-ins, custom session presets, apply/highlight helpers."""

from __future__ import annotations

import html
import uuid
from typing import Any, Mapping, MutableMapping

import streamlit as st

from playcaller.services.game_controller import apply_and_rerun, preset_snap_only, preset_two_minute_drill
from playcaller.streamlit_state.keys import GAME_CLOCK_TOTAL_SECONDS

CUSTOM_PRESETS_SS_KEY = "sidebar_custom_snap_presets_v1"
PRESET_EDIT_ID_SS_KEY = "sidebar_preset_edit_target_id"


def _snap_from_session(ss: MutableMapping[str, Any]) -> tuple[int, int, str, int, int, int]:
    down = int(ss.get("ui_down", 1))
    distance = int(ss.get("ui_distance", 10))
    territory = str(ss.get("ui_territory", "own"))
    yardline = int(ss.get("ui_yardline", 25))
    period = int(ss.get("ui_game_period", 1))
    sec = int(
        ss.get(
            GAME_CLOCK_TOTAL_SECONDS,
            int(ss.get("ui_quarter_clock_mins", 0)) * 60 + int(ss.get("ui_quarter_clock_secs", 0)),
        )
    )
    return down, distance, territory, yardline, period, sec


def snap_matches_preset(ss: MutableMapping[str, Any], p: Mapping[str, Any]) -> bool:
    d, dist, terr, yl, per, clk = _snap_from_session(ss)
    return (
        d == int(p.get("down", -1))
        and dist == int(p.get("distance", -1))
        and terr == str(p.get("territory", ""))
        and yl == int(p.get("yardline", -1))
        and per == int(p.get("period", -1))
        and clk == int(p.get("clock_total_seconds", -1))
    )


def _core_match(ss: MutableMapping[str, Any], *, down: int, distance: int, territory: str, yardline: int) -> bool:
    d, dist, terr, yl, _, _ = _snap_from_session(ss)
    return d == down and dist == distance and terr == territory and yl == yardline


def builtin_own25_active(ss: MutableMapping[str, Any]) -> bool:
    return _core_match(ss, down=1, distance=10, territory="own", yardline=25)


def builtin_opp35_active(ss: MutableMapping[str, Any]) -> bool:
    return _core_match(ss, down=3, distance=6, territory="opponents", yardline=35)


def builtin_rz_active(ss: MutableMapping[str, Any]) -> bool:
    return _core_match(ss, down=2, distance=7, territory="opponents", yardline=12)


def builtin_twomin_active(ss: MutableMapping[str, Any]) -> bool:
    per = int(ss.get("ui_game_period", 0))
    sec = int(ss.get(GAME_CLOCK_TOTAL_SECONDS, 0))
    mode = str(ss.get("ui_game_mode", ""))
    return per == 4 and sec == 70 and mode == "two_minute"


def ensure_custom_presets_list(ss: MutableMapping[str, Any]) -> list[dict[str, Any]]:
    cur = ss.get(CUSTOM_PRESETS_SS_KEY)
    if not isinstance(cur, list):
        cur = []
        ss[CUSTOM_PRESETS_SS_KEY] = cur
    return cur  # type: ignore[return-value]


def apply_custom_preset(entry: Mapping[str, Any]) -> None:
    sec = int(entry.get("clock_total_seconds", 0))
    apply_and_rerun(
        ui_down=int(entry["down"]),
        ui_distance=int(entry["distance"]),
        ui_territory=str(entry["territory"]),
        ui_yardline=int(entry["yardline"]),
        ui_game_period=int(entry["period"]),
        ui_quarter_clock_mins=sec // 60,
        ui_quarter_clock_secs=sec % 60,
        **{GAME_CLOCK_TOTAL_SECONDS: sec},
        ui_auto_generate=False,
    )


def _prime_edit_fields(ss: MutableMapping[str, Any], entry: Mapping[str, Any]) -> None:
    sec = int(entry.get("clock_total_seconds", 0))
    ss["sidebar_pedit_label"] = str(entry.get("label") or "Preset")
    ss["sidebar_pedit_down"] = int(entry.get("down", 1))
    ss["sidebar_pedit_distance"] = int(entry.get("distance", 10))
    ss["sidebar_pedit_territory"] = str(entry.get("territory", "own"))
    ss["sidebar_pedit_yardline"] = int(entry.get("yardline", 25))
    ss["sidebar_pedit_period"] = int(entry.get("period", 1))
    ss["sidebar_pedit_clock_m"] = sec // 60
    ss["sidebar_pedit_clock_s"] = sec % 60


def render_custom_presets_subsection() -> None:
    """+ New preset, list with apply / ✏️ / delete."""
    ss = st.session_state
    presets = ensure_custom_presets_list(ss)

    st.caption("My presets")
    with st.form("sidebar_new_preset_form", clear_on_submit=True):
        name = st.text_input("New preset name", placeholder="e.g. 3rd & short", key="sidebar_new_preset_draft_name")
        save = st.form_submit_button("+ Save current snap as preset", use_container_width=True, type="secondary")
    if save and name.strip():
        d, dist, terr, yl, per, clk = _snap_from_session(ss)
        presets.append(
            {
                "id": uuid.uuid4().hex[:10],
                "label": name.strip(),
                "down": d,
                "distance": dist,
                "territory": terr,
                "yardline": yl,
                "period": per,
                "clock_total_seconds": clk,
            }
        )
        ss[CUSTOM_PRESETS_SS_KEY] = presets
        st.rerun()

    edit_id = str(ss.get(PRESET_EDIT_ID_SS_KEY) or "").strip()

    for i, raw in enumerate(list(presets)):
        entry = dict(raw)
        pid = str(entry.get("id") or f"idx{i}")
        active = snap_matches_preset(ss, entry)
        label = str(entry.get("label") or "Preset")
        if edit_id == pid:
            if f"sidebar_pedit_seeded_{pid}" not in ss:
                _prime_edit_fields(ss, entry)
                ss[f"sidebar_pedit_seeded_{pid}"] = True
            with st.container(border=True):
                st.caption(f"Edit **{html.escape(label)}**")
                st.text_input("Label", key="sidebar_pedit_label")
                e1, e2 = st.columns(2)
                with e1:
                    st.number_input("Down", 1, 4, key="sidebar_pedit_down")
                    st.number_input("Distance", 1, 99, key="sidebar_pedit_distance")
                with e2:
                    st.selectbox(
                        "Territory",
                        ["own", "opponents"],
                        format_func=lambda x: "Own" if x == "own" else "Opp",
                        key="sidebar_pedit_territory",
                    )
                    st.number_input("Yard line", 1, 50, key="sidebar_pedit_yardline")
                st.number_input("Period", 1, 5, key="sidebar_pedit_period")
                ec1, ec2 = st.columns(2)
                with ec1:
                    st.number_input("Clock min", 0, 15, key="sidebar_pedit_clock_m")
                with ec2:
                    st.number_input("Clock sec", 0, 59, key="sidebar_pedit_clock_s")
                b1, b2, b3 = st.columns(3)
                with b1:
                    if st.button("Save", use_container_width=True, key=f"sidebar_preset_save_{pid}"):
                        em = int(ss.get("sidebar_pedit_clock_m", 0))
                        es = int(ss.get("sidebar_pedit_clock_s", 0))
                        presets[i] = {
                            "id": pid,
                            "label": str(ss.get("sidebar_pedit_label") or label).strip(),
                            "down": int(ss.get("sidebar_pedit_down", 1)),
                            "distance": int(ss.get("sidebar_pedit_distance", 10)),
                            "territory": str(ss.get("sidebar_pedit_territory", "own")),
                            "yardline": int(ss.get("sidebar_pedit_yardline", 25)),
                            "period": int(ss.get("sidebar_pedit_period", 1)),
                            "clock_total_seconds": em * 60 + es,
                        }
                        ss[CUSTOM_PRESETS_SS_KEY] = presets
                        ss[PRESET_EDIT_ID_SS_KEY] = ""
                        ss.pop(f"sidebar_pedit_seeded_{pid}", None)
                        st.rerun()
                with b2:
                    if st.button("Cancel", use_container_width=True, key=f"sidebar_preset_cancel_{pid}"):
                        ss[PRESET_EDIT_ID_SS_KEY] = ""
                        ss.pop(f"sidebar_pedit_seeded_{pid}", None)
                        st.rerun()
                with b3:
                    if st.button("Delete", use_container_width=True, key=f"sidebar_preset_del_{pid}"):
                        presets.pop(i)
                        ss[CUSTOM_PRESETS_SS_KEY] = presets
                        ss[PRESET_EDIT_ID_SS_KEY] = ""
                        ss.pop(f"sidebar_pedit_seeded_{pid}", None)
                        st.rerun()
            continue

        c1, c2 = st.columns([0.82, 0.18])
        with c1:
            if st.button(
                label,
                use_container_width=True,
                type="primary" if active else "secondary",
                key=f"sidebar_custom_preset_apply_{pid}",
            ):
                apply_custom_preset(entry)
        with c2:
            if st.button("✏️", key=f"sidebar_custom_preset_editbtn_{pid}", help="Edit preset"):
                ss[PRESET_EDIT_ID_SS_KEY] = pid
                for k in list(ss.keys()):
                    if isinstance(k, str) and k.startswith("sidebar_pedit_seeded_"):
                        ss.pop(k, None)
                _prime_edit_fields(ss, entry)
                st.rerun()

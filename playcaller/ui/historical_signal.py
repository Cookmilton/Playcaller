"""Streamlit panel: warehouse processed advisory (parallel track; not rule-based)."""

from __future__ import annotations

from typing import Any, Optional

import streamlit as st

from warehouse import recommender as wh_rec


def render_historical_signal_panel(historical: Optional[Any]) -> None:
    if not wh_rec.is_enabled() or historical is None:
        return
    st.subheader("Historical signal")
    if historical.status == "insufficient":
        st.info(
            f"Not enough similar historical plays to generate a signal ({int(historical.sample_size)} matches)."
        )
    else:
        st.caption(
            f"Tier {int(historical.tier_used)} match"
            f"{' (relaxed)' if historical.status == 'fallback' else ''} — based on {int(historical.sample_size)} plays"
        )
        rows = [
            {
                "play_type": c.play_type.value,
                "frequency %": round(100.0 * float(c.frequency), 1),
                "success rate %": round(100.0 * float(c.success_rate), 1),
                "avg EPA": round(float(c.avg_epa), 3),
                "count": int(c.sample_count),
            }
            for c in historical.candidates
        ]
        if rows:
            st.table(rows)
    if historical.note:
        st.caption(historical.note)
    st.caption("Advisory only — does not override the rule-based recommendation.")

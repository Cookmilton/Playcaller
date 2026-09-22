"""K1.3: the operator confirms the call, and only then does it reach the logged play.

The UI had no family/concept input at all (K1.2), so every logged play silently claimed
the recommendation. One checkbox now supplies that evidence. It defaults to unchecked, is
read only at Log time, and is seeded/reset through the pre-widget pending path — never by
writing its key after it has rendered.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from playcaller.domain import (
    CALL_SOURCE_OPERATOR_CONFIRMED,
    CALL_SOURCE_UNOBSERVED,
    ActualPlayResult,
)
from playcaller.evaluation.metrics import evaluate_audit_records
from playcaller.streamlit_state.keys import LOG_CALL_CONFIRMED, PENDING_LOG_CALL_CONFIRMED
from playcaller.streamlit_state.pending import apply_all_pending, apply_pending_log_call_confirmed
from tests.test_k11_drive_ending_log import _boot_manual, _generate, _ss

ROOT = Path(__file__).resolve().parents[1]


# ──────────────────────────────────────────────────────────────────────────────
# The checkbox is seeded/reset pre-widget, never written after render
# ──────────────────────────────────────────────────────────────────────────────


def test_k13_pending_seeds_the_checkbox_before_widgets() -> None:
    ss: dict = {PENDING_LOG_CALL_CONFIRMED: True}
    apply_pending_log_call_confirmed(ss)
    assert ss[LOG_CALL_CONFIRMED] is True
    assert PENDING_LOG_CALL_CONFIRMED not in ss, "the buffer must be consumed"

    ss = {PENDING_LOG_CALL_CONFIRMED: False, LOG_CALL_CONFIRMED: True}
    apply_pending_log_call_confirmed(ss)
    assert ss[LOG_CALL_CONFIRMED] is False


def test_k13_pending_is_a_noop_without_a_queued_value() -> None:
    ss: dict = {LOG_CALL_CONFIRMED: True}
    apply_pending_log_call_confirmed(ss)
    assert ss[LOG_CALL_CONFIRMED] is True, "an operator tick must survive an unrelated run"


def test_k13_reset_runs_from_the_shared_pending_entrypoint() -> None:
    ss: dict = {PENDING_LOG_CALL_CONFIRMED: False, LOG_CALL_CONFIRMED: True}
    apply_all_pending(ss)
    assert ss[LOG_CALL_CONFIRMED] is False


def test_k13_log_handler_never_assigns_the_widget_key_directly() -> None:
    """The handler may queue the reset; assigning the rendered widget key is forbidden."""
    src = (ROOT / "playcaller/ui/recommendations.py").read_text(encoding="utf-8")
    assert f"st.session_state[{LOG_CALL_CONFIRMED!r}]" not in src
    assert "st.session_state[LOG_CALL_CONFIRMED]" not in src
    # It is read at Log time, and the reset goes through the pending buffer.
    assert "st.session_state.get(LOG_CALL_CONFIRMED, False)" in src
    assert "st.session_state[PENDING_LOG_CALL_CONFIRMED] = False" in src


def test_k13_clearing_log_state_also_queues_the_reset() -> None:
    """Archiving a drive (End drive / drive-ending Log) clears the tick for the next series."""
    from playcaller.streamlit_state.pending import clear_in_progress_log_state

    ss: dict = {LOG_CALL_CONFIRMED: True}
    clear_in_progress_log_state(ss)
    assert ss[PENDING_LOG_CALL_CONFIRMED] is False


# ──────────────────────────────────────────────────────────────────────────────
# Metric: confirmed rows only
# ──────────────────────────────────────────────────────────────────────────────


def test_k13_family_match_counts_only_confirmed_rows() -> None:
    rows = [
        {
            "status": "closed",
            "selected_family": "power",
            "linked_actual": {"family": "power", "call_source": CALL_SOURCE_OPERATOR_CONFIRMED},
        },
        {
            "status": "closed",
            "selected_family": "power",
            "linked_actual": {"family": "screen", "call_source": CALL_SOURCE_OPERATOR_CONFIRMED},
        },
        # Unobserved: excluded entirely, not scored as a mismatch.
        {
            "status": "closed",
            "selected_family": "power",
            "linked_actual": {"family": None, "call_source": CALL_SOURCE_UNOBSERVED},
        },
        # Feed family is a text-parse normalization, not an observed call.
        {
            "status": "closed",
            "selected_family": "power",
            "linked_actual": {"family": "power", "call_source": "feed"},
        },
        # Legacy row with no provenance: untrusted.
        {"status": "closed", "selected_family": "power", "linked_actual": {"family": "power"}},
    ]
    ev = evaluate_audit_records(rows)
    assert ev["n_closed_vs_actual"] == 5
    assert ev["family_match_count"] == 1
    assert ev["family_mismatch_count"] == 1
    assert ev["n_family_match_scored"] == 2
    assert ev["n_family_match_unobserved"] == 3
    # The rate divides by the rows actually scored, not by every closed row.
    assert ev["family_match_rate"] == 0.5


def test_k13_all_unobserved_reports_no_rate_rather_than_zero() -> None:
    rows = [
        {
            "status": "closed",
            "selected_family": "power",
            "linked_actual": {"family": None, "call_source": CALL_SOURCE_UNOBSERVED},
        }
    ]
    ev = evaluate_audit_records(rows)
    assert ev["family_match_rate"] is None, "no confirmed calls means no rate, not 0%"
    assert ev["n_family_match_scored"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# AppTest: the board
# ──────────────────────────────────────────────────────────────────────────────


def _log_checkbox(at):
    for cb in at.checkbox:
        if getattr(cb, "key", None) == LOG_CALL_CONFIRMED:
            return cb
    raise AssertionError("the 'Ran the recommended call' checkbox did not render")


def test_k13_checkbox_renders_unchecked_by_default() -> None:
    at = _boot_manual({"ui_down": 1, "ui_distance": 10, "ui_territory": "own", "ui_yardline": 25})
    _generate(at)
    assert _log_checkbox(at).value is False
    assert _ss(at, LOG_CALL_CONFIRMED) is False


def test_k13_unchecked_log_is_unobserved() -> None:
    at = _boot_manual({"ui_down": 1, "ui_distance": 10, "ui_territory": "own", "ui_yardline": 25})
    _generate(at)
    at.button(key="main_log_yards_plus5").click().run()
    assert not at.exception, at.exception
    logged = at.session_state.drive_log.results[-1]
    assert logged.call_source == CALL_SOURCE_UNOBSERVED
    assert logged.family is None
    assert logged.concept_name is None


def test_k13_checked_log_records_the_recommended_call() -> None:
    at = _boot_manual({"ui_down": 1, "ui_distance": 10, "ui_territory": "own", "ui_yardline": 25})
    _generate(at)
    recommended_family = at.session_state.game.recommendation_audit[-1]["selected_family"]
    recommended_name = at.session_state.game.recommendation_audit[-1]["selected_play_name"]
    assert recommended_family

    _log_checkbox(at).check().run()
    assert not at.exception, at.exception
    assert _ss(at, LOG_CALL_CONFIRMED) is True

    at.button(key="main_log_yards_plus5").click().run()
    assert not at.exception, at.exception
    logged = at.session_state.drive_log.results[-1]
    assert logged.call_source == CALL_SOURCE_OPERATOR_CONFIRMED
    assert logged.family == recommended_family
    assert logged.concept_name == recommended_name

    closed = [r for r in at.session_state.game.recommendation_audit if r.get("actual_result")]
    assert closed[-1]["actual_result"]["call_source"] == CALL_SOURCE_OPERATOR_CONFIRMED
    assert closed[-1]["actual_result"]["family"] == recommended_family


def test_k13_tick_resets_for_the_next_snap() -> None:
    """A confirmation applies to one play only — the next snap starts unticked."""
    at = _boot_manual({"ui_down": 1, "ui_distance": 10, "ui_territory": "own", "ui_yardline": 25})
    _generate(at)
    _log_checkbox(at).check().run()
    at.button(key="main_log_yards_plus5").click().run()
    assert not at.exception, at.exception
    assert at.session_state.drive_log.results[-1].call_source == CALL_SOURCE_OPERATOR_CONFIRMED

    # Next snap (auto-generated after a non-ending log): the box is clear again, in
    # session state and in what the operator sees.
    assert _ss(at, LOG_CALL_CONFIRMED) is False
    assert _log_checkbox(at).value is False

    # AppTest keeps re-submitting a value set with ``.check()`` on the immediately
    # following ``.click()``; one plain run settles the harness to the rendered state.
    # A browser never does this — it submits the unticked box shown above.
    at.run()
    assert not at.exception, at.exception
    assert _log_checkbox(at).value is False

    at.button(key="main_log_yards_plus5").click().run()
    assert not at.exception, at.exception
    assert at.session_state.drive_log.results[-1].call_source == CALL_SOURCE_UNOBSERVED
    assert at.session_state.drive_log.results[-1].family is None


def test_k13_confirmed_field_goal_miss_still_records_the_kick_not_the_call() -> None:
    """Even confirmed, play_type comes from the outcome — the kick is not the concept."""
    a = ActualPlayResult(
        family="dropback_pass",
        concept_name="Drive",
        play_type="field_goal",
        result_type="field_goal_miss",
        call_source=CALL_SOURCE_OPERATOR_CONFIRMED,
    )
    assert a.play_type == "field_goal"
    assert a.family == "dropback_pass"

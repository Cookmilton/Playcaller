"""Pure helpers for the game review Streamlit page."""

from playcaller.evaluation.metrics import evaluate_audit_records
from playcaller.game import Game
from playcaller.ui.review_helpers import (
    build_takeaways,
    compute_review_overview,
    humanize_situation_bucket,
    match_explanation,
    overview_summary_sentence,
)


def test_humanize_situation_bucket_fourth_down() -> None:
    assert "4th down" in humanize_situation_bucket("4th_red_zone")


def test_build_takeaways_empty_audit() -> None:
    ev = evaluate_audit_records([])
    assert any("No recommendation" in b for b in build_takeaways(ev))


def test_compute_review_overview_smoke() -> None:
    g = Game.new_game()
    ev = evaluate_audit_records([])
    ov = compute_review_overview(g, [], ev)
    assert ov["game_id"] == g.game_id
    assert ov["total_logged_plays"] == 0
    assert "session_summary_line" in ov
    assert isinstance(ov["session_summary_line"], str)


def test_overview_summary_includes_operator_session_line() -> None:
    g = Game.new_game()
    assert g.session_metadata is not None
    g.session_metadata["team_name"] = "T"
    g.session_metadata["opponent"] = "O"
    g.session_metadata["game_date"] = "2026-08-01"
    g.session_metadata["is_simulated"] = False
    ev = evaluate_audit_records([])
    ov = compute_review_overview(g, [], ev)
    s = overview_summary_sentence(ov, ev)
    assert "Operator session" in s
    assert "T" in s


def test_match_explanation_open_row() -> None:
    row = {"status": "open", "selected_family": "inside_zone"}
    h, d = match_explanation(row)
    assert "outcome" in h.lower() or "No outcome" in h

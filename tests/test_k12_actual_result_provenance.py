"""K1.2: a logged play no longer inherits the recommendation's identity.

Defect K1(b): a logged field-goal miss carried ``play_type=field_goal`` but
``family=dropback_pass`` and ``concept_name=Drive`` — both copied from the
recommendation on screen, for every operator log, with no operator input for either.

``family`` / ``concept_name`` are now ``Optional`` and default to ``None`` ("not
recorded"), ``play_type`` comes from the outcome rather than the family, and
``call_source`` records provenance. A missing ``call_source`` in a legacy export means
untrusted — the same rule as J3's ``time_source``.
"""

from __future__ import annotations

import json

import pytest
from streamlit.testing.v1 import AppTest

from playcaller.actual_result import (
    NOT_RECORDED_LABEL,
    assemble_actual_semantics,
    family_display_color,
    family_display_label,
    format_actual_play_analysis_detail,
)
from playcaller.domain import (
    CALL_SOURCE_FEED,
    CALL_SOURCE_OPERATOR_CONFIRMED,
    CALL_SOURCE_UNOBSERVED,
    ActualPlayResult,
    call_is_observed,
    play_type_for_family,
)
from playcaller.evaluation.audit import actual_result_summary
from playcaller.game import classify_drive_end
from playcaller.state import DriveLogger
from playcaller.ui_components import FAM_COLOR
from tests.test_k11_drive_ending_log import _boot_manual, _generate


# ──────────────────────────────────────────────────────────────────────────────
# The copy assignment is gone
# ──────────────────────────────────────────────────────────────────────────────


def test_k12_unobserved_log_records_no_family_or_concept() -> None:
    a = assemble_actual_semantics(
        concept_name="Drive",
        family="dropback_pass",
        play={"name": "Drive"},
        yards_gained=0,
        target_choice="Auto from play",
        outcome_ui="Field goal missed",
        sack_from_chip=False,
    )
    # Exactly defect K1(b): play_type is the kick, family/concept are NOT the call.
    assert a.play_type == "field_goal"
    assert a.family is None
    assert a.concept_name is None
    assert a.call_source == CALL_SOURCE_UNOBSERVED
    assert call_is_observed(a) is False


def test_k12_confirmed_log_keeps_the_recommendation_identity() -> None:
    a = assemble_actual_semantics(
        concept_name="Drive",
        family="dropback_pass",
        play={"name": "Drive"},
        yards_gained=7,
        target_choice="Auto from play",
        outcome_ui="Complete pass",
        sack_from_chip=False,
        call_source=CALL_SOURCE_OPERATOR_CONFIRMED,
    )
    assert a.family == "dropback_pass"
    assert a.concept_name == "Drive"
    assert a.call_source == CALL_SOURCE_OPERATOR_CONFIRMED
    assert call_is_observed(a) is True


def test_k12_defaults_are_none_not_empty_string() -> None:
    a = ActualPlayResult()
    assert a.family is None
    assert a.concept_name is None
    assert a.play_type is None
    assert a.call_source is None
    # Legacy exports carry no call_source at all: untrusted.
    assert call_is_observed(a) is False


# ──────────────────────────────────────────────────────────────────────────────
# play_type is decoupled from family
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("outcome_ui", "want_play_type"),
    [
        ("Complete pass", "pass"),
        ("Incomplete pass", "pass"),
        ("Run", "run"),
        ("QB scramble", "qb_scramble"),
        ("Sack", "pass"),
        ("Interception", "pass"),
        ("Field goal good", "field_goal"),
        ("Field goal missed", "field_goal"),
    ],
)
def test_k12_play_type_comes_from_the_outcome_alone(outcome_ui: str, want_play_type: str) -> None:
    for family in (None, "dropback_pass", "inside_zone"):
        a = assemble_actual_semantics(
            concept_name=None,
            family=family,
            play={},
            yards_gained=4,
            target_choice="Auto from play",
            outcome_ui=outcome_ui,
            sack_from_chip=False,
        )
        assert a.play_type == want_play_type, (outcome_ui, family)


def test_k12_auto_with_no_family_does_not_guess() -> None:
    for yards in (-8, 0, 5, 20):
        a = assemble_actual_semantics(
            concept_name=None,
            family=None,
            play={},
            yards_gained=yards,
            target_choice="Auto from play",
            outcome_ui="Auto (from call + yards)",
            sack_from_chip=False,
        )
        assert a.play_type is None, yards
        assert a.pass_result == ""


def test_k12_play_type_for_family_never_stringifies_none() -> None:
    assert play_type_for_family(None) == ""
    assert play_type_for_family("") == ""
    assert play_type_for_family("inside_zone") == "run"


# ──────────────────────────────────────────────────────────────────────────────
# Provenance travels; legacy stays untrusted; exports are not rewritten
# ──────────────────────────────────────────────────────────────────────────────


def test_k12_call_source_travels_into_the_audit_summary() -> None:
    a = ActualPlayResult(family="power", concept_name="Iso", call_source=CALL_SOURCE_OPERATOR_CONFIRMED)
    summary = actual_result_summary(a)
    assert summary["call_source"] == CALL_SOURCE_OPERATOR_CONFIRMED
    assert summary["family"] == "power"
    legacy = actual_result_summary(ActualPlayResult())
    assert legacy["call_source"] is None
    assert legacy["family"] is None


def test_k12_legacy_export_without_call_source_loads_as_untrusted() -> None:
    """Old files are read, not rewritten: no call_source means untrusted."""
    from playcaller.game import Game, game_from_dict, game_to_dict

    legacy = {
        "schema_version": 1,
        "game_id": "legacy",
        "possession": "offense",
        "drives": [
            {
                "plays": [
                    {
                        "concept_name": "Drive",
                        "family": "dropback_pass",
                        "play_type": "pass",
                        "result_type": "short",
                        "yards_gained": 6,
                    }
                ],
                "total_yards": 6,
                "play_count": 1,
                "possessing_team": "offense",
                "result": None,
            }
        ],
    }
    game = game_from_dict(json.loads(json.dumps(legacy)))
    play = game.drives[0].plays[0]
    assert play.family == "dropback_pass"  # value preserved, not blanked
    assert play.call_source is None  # but provenance is absent
    assert call_is_observed(play) is False
    # Re-exporting does not invent a provenance for it.
    assert game_to_dict(game)["drives"][0]["plays"][0]["call_source"] is None


def test_k12_espn_plays_are_tagged_feed() -> None:
    from playcaller.live_data.espn_play_normalize import espn_play_to_actual

    play = {
        "id": "p1",
        "type": {"text": "Pass Reception"},
        "text": {"text": "(10:00) P.Mahomes pass short right to T.Kelce for 9 yards."},
        "statYardage": 9,
    }
    a = espn_play_to_actual(play)
    assert a is not None
    assert a.call_source == CALL_SOURCE_FEED
    # Feed rows are normalized, not operator-confirmed, so they are not "observed calls".
    assert call_is_observed(a) is False


# ──────────────────────────────────────────────────────────────────────────────
# Null-safe readers
# ──────────────────────────────────────────────────────────────────────────────


def test_k12_display_says_not_recorded_rather_than_blank() -> None:
    assert family_display_label(None) == NOT_RECORDED_LABEL
    assert family_display_label("") == NOT_RECORDED_LABEL
    assert family_display_label("inside_zone") == "inside zone"
    detail = format_actual_play_analysis_detail(ActualPlayResult(yards_gained=5))
    assert NOT_RECORDED_LABEL in detail


def test_k12_unrecorded_family_does_not_borrow_a_family_colour() -> None:
    unknown = family_display_color(None, FAM_COLOR)
    assert unknown not in FAM_COLOR.values(), "unrecorded calls must not reuse a family colour"
    assert family_display_color("inside_zone", FAM_COLOR) == FAM_COLOR["inside_zone"]


def test_k12_drive_logger_excludes_unobserved_plays_from_tendencies() -> None:
    dl = DriveLogger()
    dl.log(ActualPlayResult(family=None, play_type="pass"))
    dl.log(ActualPlayResult(family="inside_zone", play_type="run"))
    assert dl.family_counts == {"inside_zone": 1}, "None must not become a family key"
    assert dl.recent_families() == ["inside_zone"]
    assert dl.run_pass_split() == (1, 0), "an unobserved play is neither a run nor a pass"
    dl.pop_last()
    assert dl.family_counts == {}
    dl.pop_last()
    assert dl.family_counts == {}


def test_k12_predictor_survives_a_drive_of_unobserved_plays() -> None:
    """A None family used to crash the stable-seed mix (heuristic_predictor.py:278)."""
    from playcaller import FootballPlayPredictor, Game, GameContext

    dl = DriveLogger()
    for _ in range(3):
        dl.log(ActualPlayResult(family=None, play_type=None, yards_gained=4))
    ctx = GameContext(
        down=2,
        distance=6,
        yardline=30,
        territory="own",
        plays_this_drive=len(dl.results),
        shown_concepts=list(dl.family_counts.keys()),
        run_plays_this_drive=dl.run_count(),
    )
    rec = FootballPlayPredictor().recommend(ctx, drive_log=dl, game=Game.new_game())
    assert rec is not None


def test_k12_family_match_excludes_unobserved_rows() -> None:
    """A None family is excluded from match rates — never counted as a mismatch."""
    from playcaller.evaluation.metrics import _family_match
    from playcaller.review.derived import _family_match_row

    confirmed = {"call_source": CALL_SOURCE_OPERATOR_CONFIRMED}
    unobserved = {"selected_family": "power", "linked_actual": {"family": None, **confirmed}}
    matched = {"selected_family": "power", "linked_actual": {"family": "power", **confirmed}}
    mismatched = {"selected_family": "power", "linked_actual": {"family": "screen", **confirmed}}
    for fn in (_family_match, _family_match_row):
        assert fn(unobserved) is None, fn
        assert fn(matched) is True, fn
        assert fn(mismatched) is False, fn


def test_k12_review_insight_readers_skip_unobserved_families() -> None:
    """The insight readers bucket on a stripped family, so None drops out."""
    for value in (None, ""):
        assert str(value or "").strip() == ""


# ──────────────────────────────────────────────────────────────────────────────
# classify_drive_end no longer trusts concept names
# ──────────────────────────────────────────────────────────────────────────────


def test_k12_concept_name_cannot_declare_a_field_goal() -> None:
    """A recommendation named after a field goal must not archive the drive as one."""
    play = ActualPlayResult(
        concept_name="Field Goal Range Shot",
        family="dropback_pass",
        play_type="pass",
        result_type="short",
        yards_gained=6,
        call_source=CALL_SOURCE_OPERATOR_CONFIRMED,
    )
    res = classify_drive_end([play])
    assert res.kind != "field_goal", "concept_name must not decide the drive outcome"
    assert res.kind == "unknown"
    # result_type still decides it.
    made = ActualPlayResult(result_type="field_goal")
    assert classify_drive_end([made]).kind == "field_goal"


def test_k12_game_py_has_no_concept_substring_inference() -> None:
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "playcaller/game.py").read_text(encoding="utf-8")
    assert '"field goal" in (last.concept_name' not in src


# ──────────────────────────────────────────────────────────────────────────────
# AppTest: the board
# ──────────────────────────────────────────────────────────────────────────────


def test_k12_operator_log_lands_unobserved_on_the_board() -> None:
    at = _boot_manual({"ui_down": 1, "ui_distance": 10, "ui_territory": "own", "ui_yardline": 25})
    _generate(at)
    at.button(key="main_log_yards_plus5").click().run()
    assert not at.exception, at.exception

    logged = at.session_state.drive_log.results[-1]
    assert logged.family is None, "the logged play inherited the recommendation's family"
    assert logged.concept_name is None
    assert logged.call_source == CALL_SOURCE_UNOBSERVED

    # A non-ending log auto-regenerates, so the last row is the NEW open snap.
    closed = [r for r in at.session_state.game.recommendation_audit if r.get("actual_result")]
    assert closed, "the logged snap's review row was not closed"
    row = closed[-1]
    assert row["actual_result"]["family"] is None
    assert row["actual_result"]["concept_name"] is None
    assert row["actual_result"]["call_source"] == CALL_SOURCE_UNOBSERVED
    # The recommendation's own family is still recorded on the row — as the *model's* call.
    assert row["selected_family"]


def test_k12_fg_miss_log_does_not_claim_the_recommended_call() -> None:
    """Defect K1(b), asserted end to end on the board."""
    at = _boot_manual()
    _generate(at)
    recommended = at.session_state.game.recommendation_audit[-1]["selected_family"]
    at.button(key="main_log_fg_miss").click().run()
    assert not at.exception, at.exception

    logged = at.session_state.game.drives[0].plays[-1]
    assert logged.result_type == "field_goal_miss"
    assert logged.play_type == "field_goal"
    assert logged.family is None, f"logged play claimed the recommended family {recommended!r}"
    assert logged.concept_name is None
    assert logged.call_source == CALL_SOURCE_UNOBSERVED

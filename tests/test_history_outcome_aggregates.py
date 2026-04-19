"""Outcome aggregation on matched historical plays (evaluation-aligned definitions)."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult, GameContext
from playcaller.evaluation import actual_fields_is_explosive, actual_fields_is_turnover
from playcaller.game import Game, complete_drive_from_plays
from playcaller.history import (
    aggregate_matched_play_outcomes,
    attach_outcome_summary,
    build_normalized_plays,
    outcome_summary_to_dict,
    query_similar_plays,
    situation_signature_from_context,
)


def _closed_row(
    *,
    pre: dict,
    play: ActualPlayResult,
    reco: str = "inside_zone",
):
    g = Game.new_game()
    g.drives = [complete_drive_from_plays([play], possessing_team="offense")]
    linked = {
        "concept_name": play.concept_name,
        "family": play.family,
        "yards_gained": play.yards_gained,
        "result_type": play.result_type,
        "turnover": play.turnover,
        "pass_result": play.pass_result,
    }
    g.recommendation_audit = [
        {
            "snap_id": "x",
            "status": "closed",
            "drive_epoch": 0,
            "plays_at_recommend": 0,
            "pre_snap": pre,
            "selected_family": reco,
            "bucket": "b",
            "linked_actual": linked,
        }
    ]
    return build_normalized_plays(g, source_path="t.json")[0]


def test_aggregate_overall_success_conversion_explosive() -> None:
    pre = {
        "down": 2,
        "distance": 7,
        "yardline": 40,
        "territory": "opponents",
        "quarter": 2,
        "seconds_remaining": 800,
        "score_diff": 0,
    }
    rows = [
        _closed_row(
            pre=pre,
            play=ActualPlayResult(
                yards_gained=8,
                family="inside_zone",
                play_type="run",
                result_type="first_down",
                first_down=True,
            ),
        ),
        _closed_row(
            pre=pre,
            play=ActualPlayResult(
                yards_gained=2,
                family="power",
                play_type="run",
                result_type="short",
            ),
        ),
        _closed_row(
            pre=pre,
            play=ActualPlayResult(
                yards_gained=20,
                family="quick_game",
                play_type="pass",
                result_type="complete",
            ),
        ),
    ]
    s = aggregate_matched_play_outcomes(rows)
    assert s.overall.n == 3
    assert s.overall.n_success_evaluable == 3
    assert s.overall.success_rate is not None
    assert s.overall.success_rate == round(2 / 3, 4)
    assert s.overall.conversion_rate == round(1 / 3, 4)
    assert s.overall.explosive_rate == round(1 / 3, 4)
    assert s.overall.mean_yards == round(30 / 3, 3)
    assert s.overall.median_yards == 8.0


def test_turnover_uses_evaluation_helper() -> None:
    play = ActualPlayResult(
        yards_gained=0,
        family="dropback_pass",
        play_type="pass",
        result_type="interception",
        pass_result="intercepted",
        turnover_kind="interception",
        turnover=True,
    )
    assert actual_fields_is_turnover(
        {"yards_gained": 0, "result_type": "interception", "pass_result": "intercepted"}
    )
    pre = {
        "down": 1,
        "distance": 10,
        "yardline": 25,
        "territory": "own",
        "quarter": 1,
        "seconds_remaining": 900,
        "score_diff": 0,
    }
    row = _closed_row(pre=pre, play=play)
    s = aggregate_matched_play_outcomes([row])
    assert s.overall.turnover_rate == 1.0


def test_run_vs_pass_lane_breakdown() -> None:
    pre = {
        "down": 1,
        "distance": 10,
        "yardline": 30,
        "territory": "own",
        "quarter": 1,
        "seconds_remaining": 900,
        "score_diff": 0,
    }
    rows = [
        _closed_row(
            pre=pre,
            play=ActualPlayResult(yards_gained=4, family="inside_zone", play_type="run"),
        ),
        _closed_row(
            pre=pre,
            play=ActualPlayResult(yards_gained=0, family="quick_game", play_type="pass"),
        ),
    ]
    s = aggregate_matched_play_outcomes(rows)
    assert s.by_actual_lane["run_family"].n == 1
    assert s.by_actual_lane["pass_family"].n == 1
    assert s.by_actual_lane["run_family"].mean_yards == 4.0
    assert s.by_actual_lane["pass_family"].mean_yards == 0.0


def test_small_sample_caveats() -> None:
    pre = {
        "down": 1,
        "distance": 10,
        "yardline": 25,
        "territory": "own",
        "quarter": 1,
        "seconds_remaining": 900,
        "score_diff": 0,
    }
    row = _closed_row(
        pre=pre,
        play=ActualPlayResult(yards_gained=3, family="draw", play_type="run"),
    )
    s = aggregate_matched_play_outcomes([row])
    assert s.overall.n == 1
    assert any("very small" in c.lower() for c in s.overall.caveats)


def test_empty_matches() -> None:
    s = aggregate_matched_play_outcomes([])
    assert s.overall.n == 0
    assert s.overall.success_rate is None
    d = outcome_summary_to_dict(s)
    assert d["overall"]["n"] == 0


def test_per_family_omitted_when_tiny() -> None:
    pre = {
        "down": 1,
        "distance": 10,
        "yardline": 25,
        "territory": "own",
        "quarter": 1,
        "seconds_remaining": 900,
        "score_diff": 0,
    }
    row = _closed_row(
        pre=pre,
        play=ActualPlayResult(yards_gained=1, family="duo", play_type="run"),
    )
    s = aggregate_matched_play_outcomes([row], min_family_report_n=3)
    assert "duo" not in s.by_actual_family
    assert any("omitted" in g for g in s.global_caveats)


def test_attach_outcome_summary_on_query_result() -> None:
    pre = {
        "down": 1,
        "distance": 10,
        "yardline": 25,
        "territory": "own",
        "quarter": 1,
        "seconds_remaining": 900,
        "score_diff": 0,
    }
    rows = [
        _closed_row(
            pre=pre,
            play=ActualPlayResult(yards_gained=10, family="inside_zone", play_type="run"),
        ),
    ]
    sig = situation_signature_from_context(
        GameContext(
            down=1,
            distance=10,
            yardline=25,
            territory="own",
            def_personnel="nickel",
            box_count=7,
            coverage_shell="cover_3",
            blitz_likely=False,
            safeties="single_high",
        )
    )
    res = query_similar_plays(rows, sig, min_matches=1)
    assert res.outcome_summary is None
    res2 = attach_outcome_summary(res)
    assert res2.outcome_summary is not None
    assert res2.outcome_summary.overall.n == 1
    assert actual_fields_is_explosive({"yards_gained": 10}) is False
    assert actual_fields_is_explosive({"yards_gained": 15}) is True

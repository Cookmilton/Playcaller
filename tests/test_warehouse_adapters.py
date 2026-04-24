from __future__ import annotations

from dataclasses import fields
from datetime import date

from playcaller.play_event_segment import PlayEventSegment
from playcaller.review.unified_review import ReviewMode, UnifiedComparison, UnifiedReviewRow

from warehouse.adapters import to_review_rows
from warehouse.models import DataSource, DerivedPlayFeatures, Game, GameStatus, GameType, Play
from warehouse.taxonomy import PlayResult, PlayType


def _expected_actual_keys() -> frozenset[str]:
    return frozenset(
        {
            "summary_bucket",
            "actual_bucket",
            "family",
            "run_pass",
            "yards_gained",
            "play_type",
            "result_type",
        }
    )


def _expected_model_keys() -> frozenset[str]:
    return frozenset({"summary_bucket", "family", "play_name", "run_pass"})


def _expected_pre_snap_keys() -> frozenset[str]:
    return frozenset(
        {
            "down",
            "distance",
            "territory",
            "yardline",
            "quarter",
            "seconds_remaining",
            "score_diff",
        }
    )


def test_to_review_rows_shape_matches_unified_review_row() -> None:
    g = Game(
        id="g1",
        source=DataSource.NFLVERSE,
        external_game_id="401772938",
        season=2024,
        week=1,
        game_type=GameType.REG,
        home_team="KC",
        away_team="BUF",
        game_date=date(2024, 9, 5),
        status=GameStatus.FINAL,
        final_home_score=27,
        final_away_score=24,
    )
    p = Play(
        id="play-1",
        game_id="g1",
        external_play_id="1",
        play_sequence=1,
        quarter=1,
        score_offense=0,
        score_defense=0,
        play_type=PlayType.RUN,
        play_result=PlayResult.RUSH_GAIN,
        first_down=True,
        touchdown=False,
        turnover=False,
        raw_description="(15:00) (Shotgun) J.Allen left tackle to KC 45 for 5 yards.",
        clock_seconds=900,
        down=1,
        distance=10,
        yardline_100=55,
        yards_gained=5,
    )
    f = DerivedPlayFeatures(
        play_id="play-1",
        red_zone=False,
        goal_to_go=False,
        four_down_territory=False,
        two_minute=False,
        score_diff=0,
        score_diff_bucket="tied",
        field_zone="opp",
        distance_bucket="medium",
        game_script="neutral",
        previous_play_type=None,
        drive_number=1,
    )

    rows = to_review_rows([p], [f], g)
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row, UnifiedReviewRow)

    for fdef in fields(UnifiedReviewRow):
        assert hasattr(row, fdef.name)

    assert row.review_mode is ReviewMode.WAREHOUSE_HISTORICAL
    assert row.audit_index is None
    assert row.drive_id == 0
    assert row.play_index_on_drive == 1
    assert row.team_side is None
    assert row.actual_headline == p.raw_description.strip()
    assert row.actual_detail == ""
    assert row.model_headline == "—"
    assert row.model_subline == ""
    assert row.confidence is None
    assert row.is_replay is True
    assert row.is_historical is False
    assert row.mismatch_tags == ()
    assert row.replay_error is None
    assert row.chain_error is None
    assert row.drive_result_kind is None
    assert row.event_segment is PlayEventSegment.OFFENSE
    assert row.offensive_snap_index == 1

    assert isinstance(row.comparison, UnifiedComparison)
    assert row.comparison.run_pass_match is None
    assert row.comparison.summary_bucket_match is None
    assert row.comparison.family_match is None

    assert frozenset(row.pre_snap.keys()) == _expected_pre_snap_keys()
    assert frozenset(row.actual_structured.keys()) == _expected_actual_keys()
    assert frozenset(row.model_structured.keys()) == _expected_model_keys()

    assert row.pre_snap["down"] == 1
    assert row.pre_snap["distance"] == 10
    assert row.pre_snap["territory"] is None
    assert row.pre_snap["yardline"] == 55
    assert row.pre_snap["quarter"] == 1
    assert row.pre_snap["seconds_remaining"] == 900
    assert row.pre_snap["score_diff"] == 0

    assert row.actual_structured["run_pass"] == "Run"
    assert row.actual_structured["yards_gained"] == 5
    assert row.actual_structured["play_type"] == "RUN"
    assert row.actual_structured["result_type"] == "RUSH_GAIN"

    assert row.model_structured["summary_bucket"] == ""
    assert row.model_structured["family"] == ""
    assert row.model_structured["play_name"] == ""
    assert row.model_structured["run_pass"] is None

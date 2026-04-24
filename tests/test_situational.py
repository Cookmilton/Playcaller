"""Situational aggregates (``playcaller.review_insights.situational``)."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult
from playcaller.game import Drive, Game
from playcaller.play_event_segment import PlayEventSegment
from playcaller.review.unified_review import ReviewMode, UnifiedComparison, UnifiedReviewRow
from playcaller.review_insights.situational import (
    aggregate_situation,
    build_indexed_our_offense,
    row_matches_situation,
)


def _row(
    *,
    drive_id: int = 0,
    play_index_on_drive: int = 1,
    pre_snap: dict,
    run_pass: str | None,
    result_type: str = "first_down",
    team_side: str | None = "our",
) -> UnifiedReviewRow:
    ar = {
        "run_pass": run_pass,
        "result_type": result_type,
        "summary_bucket": "short pass",
        "yards_gained": 6,
    }
    return UnifiedReviewRow(
        review_mode=ReviewMode.REPLAY_ONLY,
        audit_index=None,
        drive_id=drive_id,
        play_index_on_drive=play_index_on_drive,
        team_side=team_side,
        pre_snap=pre_snap,
        actual_headline="Test",
        actual_detail="",
        actual_structured=ar,
        model_headline="—",
        model_subline="",
        model_structured={"run_pass": run_pass},
        comparison=UnifiedComparison(None, None, None),
        confidence=None,
        is_replay=True,
        is_historical=False,
        event_segment=PlayEventSegment.OFFENSE,
        offensive_snap_index=1,
    )


def test_first_down_filter_counts_only_first() -> None:
    g = Game.new_game()
    indexed = [
        (0, _row(pre_snap={"down": 1, "distance": 10, "territory": "own", "yardline": 25, "quarter": 1}, run_pass="Run")),
        (1, _row(pre_snap={"down": 1, "distance": 10, "territory": "own", "yardline": 25, "quarter": 1}, run_pass="Pass")),
        (2, _row(pre_snap={"down": 2, "distance": 8, "territory": "own", "yardline": 35, "quarter": 1}, run_pass="Run")),
    ]
    agg = aggregate_situation(g, indexed, "1st_down")
    assert agg.play_count == 2
    assert row_matches_situation(indexed[0][1], "1st_down")
    assert not row_matches_situation(indexed[2][1], "1st_down")


def test_aggregate_matches_hand_computed_values() -> None:
    g = Game.new_game()
    # Three first-down plays: 2 successes (first_down), 1 failure — yards 4,6,8
    plays = [
        ActualPlayResult(
            play_type="run",
            result_type="first_down",
            yards_gained=4,
            first_down=True,
            feed_presnap_down=1,
            feed_presnap_distance=10,
            feed_presnap_territory="own",
            feed_presnap_yardline=30,
        ),
        ActualPlayResult(
            play_type="pass",
            result_type="incomplete",
            yards_gained=0,
            first_down=False,
            feed_presnap_down=1,
            feed_presnap_distance=10,
            feed_presnap_territory="own",
            feed_presnap_yardline=35,
        ),
        ActualPlayResult(
            play_type="run",
            result_type="first_down",
            yards_gained=8,
            first_down=True,
            feed_presnap_down=1,
            feed_presnap_distance=10,
            feed_presnap_territory="own",
            feed_presnap_yardline=40,
        ),
    ]
    g.drives = [Drive(plays=plays, possessing_team="offense", feed_team_espn_id="9")]
    indexed = [
        (0, _row(drive_id=0, play_index_on_drive=1, pre_snap={"down": 1, "distance": 10, "territory": "own", "yardline": 30, "quarter": 1}, run_pass="Run")),
        (1, _row(drive_id=0, play_index_on_drive=2, pre_snap={"down": 1, "distance": 10, "territory": "own", "yardline": 35, "quarter": 1}, run_pass="Pass", result_type="incomplete")),
        (2, _row(drive_id=0, play_index_on_drive=3, pre_snap={"down": 1, "distance": 10, "territory": "own", "yardline": 40, "quarter": 1}, run_pass="Run")),
    ]
    agg = aggregate_situation(g, indexed, "1st_down")
    assert agg.play_count == 3
    assert agg.success_count == 2
    assert abs((agg.success_rate or 0) - 2 / 3) < 1e-9
    assert agg.avg_yards is not None
    assert abs(agg.avg_yards - (4 + 0 + 8) / 3) < 1e-9
    assert agg.run_count == 2
    assert agg.pass_count == 1


def test_empty_aggregate_no_division() -> None:
    g = Game.new_game()
    agg = aggregate_situation(g, [], "all")
    assert agg.play_count == 0
    assert agg.success_rate is None
    assert agg.avg_yards is None


def test_build_indexed_respects_team_filter() -> None:
    g = Game.new_game()
    g.drives = [
        Drive(plays=[], feed_team_espn_id="9"),
        Drive(plays=[], feed_team_espn_id="99"),
    ]
    rows = [
        _row(
            drive_id=0,
            play_index_on_drive=1,
            pre_snap={"down": 1, "distance": 10, "territory": "own", "yardline": 25, "quarter": 1},
            run_pass="Run",
            team_side=None,
        ),
        _row(
            drive_id=1,
            play_index_on_drive=1,
            pre_snap={"down": 1, "distance": 10, "territory": "own", "yardline": 25, "quarter": 1},
            run_pass="Pass",
            team_side=None,
        ),
    ]
    ours = build_indexed_our_offense(g, rows, our_coached_espn_id="9")
    assert len(ours) == 1

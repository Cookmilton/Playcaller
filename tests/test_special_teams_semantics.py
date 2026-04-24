"""Kickoff / special teams classification, review segmentation, and analytics scope."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult
from playcaller.live_data.espn_play_normalize import espn_play_to_actual, validate_actual_for_engine
from playcaller.play_event_segment import PlayEventSegment, segment_from_actual
from playcaller.replay.comparison import actual_run_pass_bucket
from playcaller.review.session_analytics import build_pattern_analysis
from playcaller.review.unified_review import ReviewMode, UnifiedComparison, UnifiedReviewRow
from playcaller.situation import advance_game_state_after_actual


def test_espn_normalize_kickoff_row() -> None:
    play = {
        "id": "k1",
        "type": {"text": "Kickoff"},
        "text": {"text": "(13:12) M.Prater kicks 65 yards from DET 35 to end zone, Touchback."},
        "statYardage": 0,
    }
    a = espn_play_to_actual(play)
    assert a is not None
    assert a.result_type == "kickoff"
    assert a.play_type == "special"
    a2 = validate_actual_for_engine(a)
    assert a2.family == "special_teams"


def test_espn_normalize_extra_point() -> None:
    play = {
        "id": "e1",
        "type": {"text": "Extra Point"},
        "text": {"text": "J.Myers extra point is GOOD, Center-T.Ott, Holder-M.Dickson."},
        "statYardage": 0,
    }
    a = espn_play_to_actual(play)
    assert a is not None
    assert a.result_type == "extra_point"


def test_advance_state_after_kickoff_sets_first_offense() -> None:
    a = ActualPlayResult(
        concept_name="Kickoff",
        family="special_teams",
        play_type="special",
        result_type="kickoff",
        yards_gained=0,
        description="[ESPN] Kickoff",
    )
    snap = advance_game_state_after_actual(
        territory="own", yardline=25, down=1, distance=10, actual=a
    )
    assert snap.down == 1 and snap.distance == 10


def test_segment_from_actual_kickoff() -> None:
    a = ActualPlayResult(result_type="kickoff", play_type="special", family="special_teams")
    assert segment_from_actual(a) == PlayEventSegment.KICKOFF


def test_pattern_analysis_excludes_kickoff_row() -> None:
    def _row(model_rp: str, actual_rp: str | None, seg: PlayEventSegment) -> UnifiedReviewRow:
        return UnifiedReviewRow(
            review_mode=ReviewMode.TRUE_STORED,
            audit_index=0,
            drive_id=0,
            play_index_on_drive=1,
            team_side="our",
            pre_snap={"down": 1, "distance": 10, "territory": "own", "yardline": 25},
            actual_headline="x",
            actual_detail="",
            actual_structured={"run_pass": actual_rp},
            model_headline="y",
            model_subline="",
            model_structured={"run_pass": model_rp},
            comparison=UnifiedComparison(True, True, True),
            confidence=0.8,
            is_replay=False,
            is_historical=True,
            event_segment=seg,
            offensive_snap_index=1 if seg == PlayEventSegment.OFFENSE else None,
        )

    rows = [
        _row("Pass", "Run", PlayEventSegment.KICKOFF),
        _row("Pass", "Pass", PlayEventSegment.OFFENSE),
        _row("Run", "Run", PlayEventSegment.OFFENSE),
    ]
    rep = build_pattern_analysis(rows)
    m1, a1 = rep.by_down[1]
    assert m1.n == 2


def test_actual_run_pass_bucket_kickoff_is_none() -> None:
    a = ActualPlayResult(result_type="kickoff", play_type="special", family="special_teams")
    assert actual_run_pass_bucket(a) is None

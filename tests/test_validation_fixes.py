"""Tests for 2025 corpus validation/quality tuning (kickoff score lag, kickoff possession, timeouts)."""

from __future__ import annotations

from warehouse.models import Play
from warehouse.quality import check_quality
from warehouse.taxonomy import PlayResult, PlayType
from warehouse.validation import validate_play_sequence

from tests.test_validation import _play, _sample_game


def test_score_only_kickoff_small_delta_suppressed_after_penalty_no_play() -> None:
    """NFLVERSE often applies PAT/2PT points on the kickoff row (false positive before fix)."""
    plays = [
        _play(
            id="p1",
            external_play_id="1",
            play_sequence=1,
            quarter=2,
            score_offense=6,
            score_defense=7,
            play_type=PlayType.PENALTY_NO_PLAY,
            play_result=PlayResult.NO_PLAY,
            touchdown=False,
            raw_description="Offsetting penalties.",
            clock_seconds=300,
        ),
        _play(
            id="p2",
            external_play_id="2",
            play_sequence=2,
            quarter=2,
            score_offense=6,
            score_defense=9,
            play_type=PlayType.KICKOFF,
            play_result=PlayResult.KICKOFF_NORMAL,
            touchdown=False,
            raw_description="Kickoff after scoreboard catches up.",
            clock_seconds=300,
        ),
    ]
    report = validate_play_sequence(_sample_game(), plays)
    assert not any(i.rule == "score_only_on_scoring_play" for i in report.issues)


def test_score_only_kickoff_large_jump_still_errors() -> None:
    """Do not silence implausible score jumps on kickoff rows (|Δ| > 8)."""
    plays = [
        _play(
            id="p1",
            external_play_id="1",
            play_sequence=1,
            score_offense=0,
            score_defense=0,
            clock_seconds=900,
        ),
        _play(
            id="p2",
            external_play_id="2",
            play_sequence=2,
            score_offense=14,
            score_defense=0,
            play_type=PlayType.KICKOFF,
            play_result=PlayResult.KICKOFF_NORMAL,
            touchdown=False,
            clock_seconds=880,
        ),
    ]
    report = validate_play_sequence(_sample_game(), plays)
    assert any(i.rule == "score_only_on_scoring_play" for i in report.issues)


def test_quarter_regress_on_timeout_row_not_flagged() -> None:
    """Timeout rows sometimes carry a lower quarter id than the prior snap (source quirk)."""
    plays = [
        _play(
            id="a",
            external_play_id="10",
            play_sequence=10,
            quarter=3,
            raw_description="Run",
            clock_seconds=100,
        ),
        _play(
            id="b",
            external_play_id="11",
            play_sequence=11,
            quarter=2,
            raw_description="Timeout #1 by ARI at 00:01.",
            clock_seconds=1,
        ),
    ]
    report = validate_play_sequence(_sample_game(), plays)
    assert not any(i.rule == "quarter_progression" for i in report.issues)


def test_quarter_regress_without_timeout_still_error() -> None:
    plays = [
        _play(
            id="a",
            external_play_id="10",
            play_sequence=10,
            quarter=3,
            raw_description="Run",
            clock_seconds=100,
        ),
        _play(
            id="b",
            external_play_id="11",
            play_sequence=11,
            quarter=2,
            raw_description="No administrative row — suspicious ordering.",
            clock_seconds=1,
        ),
    ]
    report = validate_play_sequence(_sample_game(), plays)
    assert any(i.rule == "quarter_progression" for i in report.issues)


def test_quality_possession_kickoff_explained() -> None:
    prev = _play(
        id="a",
        external_play_id="50",
        play_sequence=50,
        play_type=PlayType.PASS,
        play_result=PlayResult.COMPLETE,
        possession_team="BUF",
        defense_team="KC",
        raw_description="Short gain",
    )
    curr = _play(
        id="b",
        external_play_id="51",
        play_sequence=51,
        play_type=PlayType.KICKOFF,
        play_result=PlayResult.KICKOFF_NORMAL,
        possession_team="KC",
        defense_team="BUF",
        raw_description="Kickoff",
    )
    g = _sample_game()
    assert not check_quality(g, [prev, curr])


def test_quality_possession_flip_on_scrimmage_still_flagged() -> None:
    prev = _play(
        id="a",
        external_play_id="60",
        play_sequence=60,
        play_type=PlayType.RUN,
        play_result=PlayResult.RUSH_GAIN,
        possession_team="BUF",
        defense_team="KC",
        down=2,
        raw_description="Run",
    )
    curr = _play(
        id="b",
        external_play_id="61",
        play_sequence=61,
        play_type=PlayType.RUN,
        play_result=PlayResult.RUSH_GAIN,
        possession_team="KC",
        defense_team="BUF",
        down=1,
        raw_description="Run",
    )
    issues = check_quality(_sample_game(), [prev, curr])
    assert any(i.rule == "unexplained_possession_change" for i in issues)


def test_declares_scoring_extra_point_play_type_quality_import() -> None:
    """_declares_scoring_event treats PAT/2PT play types as scoring context (shared with validation)."""
    p = _play(
        play_type=PlayType.EXTRA_POINT,
        play_result=PlayResult.NO_PLAY,
        touchdown=False,
        raw_description="",
    )
    from warehouse.validation import _declares_scoring_event

    assert _declares_scoring_event(p) is True

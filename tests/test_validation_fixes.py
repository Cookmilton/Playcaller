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


def test_clock_monotonic_suppresses_stragglers_after_end_period_markers() -> None:
    """Rows after END QUARTER / END GAME often have non-zero clocks but must not chain from 0s."""
    g = _sample_game()
    end_quarter_then_penalty = [
        _play(
            id="a",
            external_play_id="120",
            play_sequence=120,
            quarter=3,
            clock_seconds=36,
            raw_description="(:36) Normal snap.",
        ),
        _play(
            id="b",
            external_play_id="121",
            play_sequence=121,
            quarter=3,
            clock_seconds=0,
            play_type=PlayType.UNKNOWN,
            play_result=PlayResult.UNKNOWN,
            raw_description="END QUARTER 3",
        ),
        _play(
            id="c",
            external_play_id="122",
            play_sequence=122,
            quarter=3,
            clock_seconds=7,
            play_type=PlayType.PENALTY_NO_PLAY,
            play_result=PlayResult.NO_PLAY,
            raw_description="(:07) PENALTY on DEF, Offside, 5 yards.",
        ),
    ]
    r1 = validate_play_sequence(g, end_quarter_then_penalty)
    assert not any(i.rule == "clock_monotonic" for i in r1.issues)

    end_game_then_kneel = [
        _play(
            id="d",
            external_play_id="170",
            play_sequence=170,
            quarter=4,
            clock_seconds=50,
            play_type=PlayType.KNEEL,
            play_result=PlayResult.KNEEL,
            raw_description="(:50) QB kneels.",
        ),
        _play(
            id="e",
            external_play_id="171",
            play_sequence=171,
            quarter=4,
            clock_seconds=0,
            play_type=PlayType.UNKNOWN,
            play_result=PlayResult.UNKNOWN,
            raw_description="END GAME",
        ),
        _play(
            id="f",
            external_play_id="172",
            play_sequence=172,
            quarter=4,
            clock_seconds=33,
            play_type=PlayType.KNEEL,
            play_result=PlayResult.KNEEL,
            raw_description="(:33) QB kneels (nflverse straggler row).",
        ),
    ]
    r2 = validate_play_sequence(g, end_game_then_kneel)
    assert not any(i.rule == "clock_monotonic" for i in r2.issues)


def test_clock_monotonic_scrimmage_clock_increase_still_warns() -> None:
    """Ordinary same-quarter scrimmage: game clock must not run backward in the feed."""
    plays = [
        _play(
            id="a",
            external_play_id="60",
            play_sequence=60,
            quarter=1,
            clock_seconds=500,
            raw_description="(8:20) Run.",
        ),
        _play(
            id="b",
            external_play_id="61",
            play_sequence=61,
            quarter=1,
            clock_seconds=520,
            raw_description="(8:40) Clock moved the wrong direction vs prior snap.",
        ),
    ]
    report = validate_play_sequence(_sample_game(), plays)
    warns = [i for i in report.issues if i.rule == "clock_monotonic"]
    assert len(warns) == 1


def test_clock_monotonic_kickoff_row_skipped_stale_clock_suppressed() -> None:
    """Kickoff rows often carry a non-monotonic clock vs prior scrimmage; chain skips them."""
    plays = [
        _play(
            id="a",
            external_play_id="100",
            play_sequence=100,
            quarter=2,
            clock_seconds=500,
            raw_description="(8:20) Run.",
        ),
        _play(
            id="k",
            external_play_id="101",
            play_sequence=101,
            quarter=2,
            play_type=PlayType.KICKOFF,
            play_result=PlayResult.KICKOFF_NORMAL,
            clock_seconds=520,
            raw_description="Kickoff — feed clock lags prior snap.",
        ),
        _play(
            id="b",
            external_play_id="102",
            play_sequence=102,
            quarter=2,
            clock_seconds=480,
            raw_description="(8:00) Next scrimmage.",
        ),
    ]
    report = validate_play_sequence(_sample_game(), plays)
    assert not any(i.rule == "clock_monotonic" for i in report.issues)


def test_clock_monotonic_q4_equal_second_stack_tolerated() -> None:
    """Q4 replay / administrative stacks: wider same-second budget than other quarters."""
    plays = [
        _play(
            id=f"p{i}",
            external_play_id=str(200 + i),
            play_sequence=200 + i,
            quarter=4,
            clock_seconds=65,
            raw_description=f"(1:05) Q4 play {i}.",
        )
        for i in range(7)
    ]
    report = validate_play_sequence(_sample_game(), plays)
    assert not any(i.rule == "clock_monotonic" for i in report.issues)


def test_clock_monotonic_equal_second_cap_unchanged_outside_q4() -> None:
    """Non-Q4 quarters keep the original equal-second cap (5th same-second transition warns)."""
    plays = [
        _play(
            id=f"p{i}",
            external_play_id=str(300 + i),
            play_sequence=300 + i,
            quarter=2,
            clock_seconds=200,
            raw_description=f"Q2 same clock {i}.",
        )
        for i in range(6)
    ]
    report = validate_play_sequence(_sample_game(), plays)
    warns = [i for i in report.issues if i.rule == "clock_monotonic"]
    assert len(warns) == 1


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

"""Regression tests for warehouse validation / quality rule tuning (2025 W1 noise fixes)."""

from __future__ import annotations

from warehouse.models import Play
from warehouse.quality import check_quality
from warehouse.taxonomy import PlayResult, PlayType
from warehouse.validation import validate_play_sequence

from tests.test_validation import _play, _sample_game


def test_score_prev_extra_point_declares_kickoff_pat_lag_no_error() -> None:
    """PAT row declares scoring; +1 on following kickoff is not flagged (was false positive)."""
    plays = [
        _play(
            id="p1",
            external_play_id="1",
            play_sequence=1,
            score_offense=6,
            score_defense=0,
            play_type=PlayType.EXTRA_POINT,
            play_result=PlayResult.EXTRA_POINT_MADE,
            touchdown=False,
            raw_description="Kicker extra point is GOOD.",
            clock_seconds=600,
        ),
        _play(
            id="p2",
            external_play_id="2",
            play_sequence=2,
            score_offense=7,
            score_defense=0,
            play_type=PlayType.KICKOFF,
            play_result=PlayResult.KICKOFF_NORMAL,
            touchdown=False,
            raw_description="Kicker kicks 65 yards.",
            clock_seconds=600,
        ),
    ]
    report = validate_play_sequence(_sample_game(), plays)
    assert not any(i.rule == "score_only_on_scoring_play" for i in report.issues)


def test_score_jump_without_scoring_still_error() -> None:
    """Illegal total jump when neither adjacent play declares scoring."""
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
            score_offense=7,
            score_defense=0,
            play_result=PlayResult.INCOMPLETE,
            touchdown=False,
            clock_seconds=880,
        ),
    ]
    report = validate_play_sequence(_sample_game(), plays)
    errs = [i for i in report.issues if i.rule == "score_only_on_scoring_play"]
    assert len(errs) == 1
    assert errs[0].play_id == "2"


def test_possession_kickoff_after_extra_point_not_flagged() -> None:
    prev = _play(
        id="a",
        external_play_id="10",
        play_sequence=10,
        play_type=PlayType.EXTRA_POINT,
        play_result=PlayResult.EXTRA_POINT_MADE,
        possession_team="BUF",
        defense_team="KC",
        raw_description="XP good",
    )
    curr = _play(
        id="b",
        external_play_id="11",
        play_sequence=11,
        play_type=PlayType.KICKOFF,
        play_result=PlayResult.KICKOFF_NORMAL,
        possession_team="KC",
        defense_team="BUF",
        raw_description="Kickoff",
    )
    report = validate_play_sequence(_sample_game(), [prev, curr])
    assert not any(i.rule == "possession_change_explained" for i in report.issues)


def test_possession_flip_without_explanation_still_warned() -> None:
    prev = _play(
        id="a",
        external_play_id="20",
        play_sequence=20,
        play_type=PlayType.RUN,
        play_result=PlayResult.RUSH_GAIN,
        possession_team="BUF",
        defense_team="KC",
        down=2,
        first_down=False,
        raw_description="Short run",
    )
    curr = _play(
        id="b",
        external_play_id="21",
        play_sequence=21,
        play_type=PlayType.RUN,
        play_result=PlayResult.RUSH_GAIN,
        possession_team="KC",
        defense_team="BUF",
        down=1,
        first_down=False,
        raw_description="Other team runs",
    )
    report = validate_play_sequence(_sample_game(), [prev, curr])
    warns = [i for i in report.issues if i.rule == "possession_change_explained"]
    assert len(warns) == 1


def test_quarter_end_bookkeeping_row_not_regression_error() -> None:
    prev = _play(
        id="a",
        external_play_id="30",
        play_sequence=30,
        quarter=2,
        raw_description="(14:00) Pass complete.",
    )
    curr = _play(
        id="b",
        external_play_id="31",
        play_sequence=31,
        quarter=1,
        play_type=PlayType.UNKNOWN,
        play_result=PlayResult.UNKNOWN,
        raw_description="END QUARTER 1",
    )
    report = validate_play_sequence(_sample_game(), [prev, curr])
    assert not any(i.rule == "quarter_progression" for i in report.issues)


def test_quarter_real_regression_still_error() -> None:
    prev = _play(
        id="a",
        external_play_id="40",
        play_sequence=40,
        quarter=3,
        raw_description="Q3 play",
    )
    curr = _play(
        id="b",
        external_play_id="41",
        play_sequence=41,
        quarter=2,
        raw_description="Bad data Q2 after Q3",
    )
    report = validate_play_sequence(_sample_game(), [prev, curr])
    errs = [i for i in report.issues if i.rule == "quarter_progression"]
    assert len(errs) == 1


def test_clock_skips_timeout_lines_with_bad_clock() -> None:
    plays = [
        _play(
            id="a",
            external_play_id="50",
            play_sequence=50,
            quarter=4,
            clock_seconds=65,
            raw_description="(1:05) Pass incomplete.",
        ),
        _play(
            id="b",
            external_play_id="51",
            play_sequence=51,
            quarter=4,
            clock_seconds=105,
            play_type=PlayType.PENALTY_NO_PLAY,
            play_result=PlayResult.NO_PLAY,
            raw_description="Timeout #4 by TEN at 01:45.",
        ),
        _play(
            id="c",
            external_play_id="52",
            play_sequence=52,
            quarter=4,
            clock_seconds=65,
            raw_description="(1:05) Next snap.",
        ),
    ]
    report = validate_play_sequence(_sample_game(), plays)
    assert not any(i.rule == "clock_monotonic" for i in report.issues)


def test_clock_increase_within_quarter_still_warning() -> None:
    plays = [
        _play(
            id="a",
            external_play_id="60",
            play_sequence=60,
            quarter=1,
            clock_seconds=500,
            raw_description="First snap",
        ),
        _play(
            id="b",
            external_play_id="61",
            play_sequence=61,
            quarter=1,
            clock_seconds=520,
            raw_description="Clock wrong",
        ),
    ]
    report = validate_play_sequence(_sample_game(), plays)
    warns = [i for i in report.issues if i.rule == "clock_monotonic"]
    assert len(warns) == 1


def test_quality_unexplained_jump_suppressed_when_prev_touchdown() -> None:
    game = _sample_game()
    prev = Play(
        id="q1",
        game_id=game.id,
        external_play_id="70",
        play_sequence=70,
        quarter=1,
        score_offense=0,
        score_defense=0,
        play_type=PlayType.PASS,
        play_result=PlayResult.TOUCHDOWN_PASS,
        first_down=True,
        touchdown=True,
        turnover=False,
        raw_description="TD pass",
        possession_team="BUF",
        defense_team="KC",
        down=3,
        distance=5,
        yardline_100=10,
    )
    curr = Play(
        id="q2",
        game_id=game.id,
        external_play_id="71",
        play_sequence=71,
        quarter=1,
        score_offense=0,
        score_defense=14,
        play_type=PlayType.KICKOFF,
        play_result=PlayResult.KICKOFF_NORMAL,
        first_down=False,
        touchdown=False,
        turnover=False,
        raw_description="Kickoff after TD",
        possession_team="KC",
        defense_team="BUF",
        down=None,
        distance=None,
        yardline_100=40,
    )
    issues = check_quality(game, [prev, curr])
    assert not any(i.rule == "unexplained_score_jump" for i in issues)


def test_quality_unexplained_jump_still_fires_on_mystery_spike() -> None:
    game = _sample_game()
    prev = Play(
        id="q1",
        game_id=game.id,
        external_play_id="80",
        play_sequence=80,
        quarter=1,
        score_offense=0,
        score_defense=0,
        play_type=PlayType.RUN,
        play_result=PlayResult.RUSH_GAIN,
        first_down=False,
        touchdown=False,
        turnover=False,
        raw_description="Run",
        possession_team="BUF",
        defense_team="KC",
        down=1,
        distance=10,
        yardline_100=50,
    )
    curr = Play(
        id="q2",
        game_id=game.id,
        external_play_id="81",
        play_sequence=81,
        quarter=1,
        score_offense=0,
        score_defense=20,
        play_type=PlayType.RUN,
        play_result=PlayResult.RUSH_GAIN,
        first_down=False,
        touchdown=False,
        turnover=False,
        raw_description="Twenty point jump",
        possession_team="BUF",
        defense_team="KC",
        down=2,
        distance=6,
        yardline_100=45,
    )
    issues = check_quality(game, [prev, curr])
    assert any(i.rule == "unexplained_score_jump" for i in issues)


def test_quality_two_point_attempt_skips_missing_situation() -> None:
    game = _sample_game()
    p = Play(
        id="m1",
        game_id=game.id,
        external_play_id="90",
        play_sequence=90,
        quarter=2,
        score_offense=7,
        score_defense=7,
        play_type=PlayType.PASS,
        play_result=PlayResult.INCOMPLETE,
        first_down=False,
        touchdown=False,
        turnover=False,
        raw_description="TWO-POINT CONVERSION ATTEMPT. Pass incomplete. ATTEMPT FAILS.",
        possession_team="BUF",
        defense_team="KC",
        down=None,
        distance=0,
        yardline_100=2,
    )
    issues = check_quality(game, [p])
    assert not any(i.rule == "missing_situation" for i in issues)


def test_quality_missing_situation_still_fires_on_normal_pass() -> None:
    game = _sample_game()
    p = Play(
        id="m2",
        game_id=game.id,
        external_play_id="91",
        play_sequence=91,
        quarter=2,
        score_offense=7,
        score_defense=7,
        play_type=PlayType.PASS,
        play_result=PlayResult.COMPLETE,
        first_down=True,
        touchdown=False,
        turnover=False,
        raw_description="Ordinary pass",
        possession_team="BUF",
        defense_team="KC",
        down=None,
        distance=None,
        yardline_100=None,
    )
    issues = check_quality(game, [p])
    assert any(i.rule == "missing_situation" for i in issues)


def test_quality_incomplete_after_challenge_ignores_yards() -> None:
    game = _sample_game()
    p = Play(
        id="n1",
        game_id=game.id,
        external_play_id="100",
        play_sequence=100,
        quarter=3,
        score_offense=10,
        score_defense=10,
        play_type=PlayType.PASS,
        play_result=PlayResult.INCOMPLETE,
        first_down=False,
        touchdown=False,
        turnover=False,
        raw_description="Pass incomplete. Houston challenged the ruling, and the play was overturned.",
        possession_team="BUF",
        defense_team="KC",
        yards_gained=-7,
        down=2,
        distance=8,
        yardline_100=40,
    )
    issues = check_quality(game, [p])
    assert not any(i.rule == "negative_yards_on_incomplete" for i in issues)


def test_quality_negative_yards_on_plain_incomplete_still_fires() -> None:
    game = _sample_game()
    p = Play(
        id="n2",
        game_id=game.id,
        external_play_id="101",
        play_sequence=101,
        quarter=3,
        score_offense=10,
        score_defense=10,
        play_type=PlayType.PASS,
        play_result=PlayResult.INCOMPLETE,
        first_down=False,
        touchdown=False,
        turnover=False,
        raw_description="Pass incomplete short left.",
        possession_team="BUF",
        defense_team="KC",
        yards_gained=-5,
        down=2,
        distance=8,
        yardline_100=40,
    )
    issues = check_quality(game, [p])
    assert any(i.rule == "negative_yards_on_incomplete" for i in issues)


def test_quality_possession_after_two_point_attempt_text_not_flagged() -> None:
    game = _sample_game()
    prev = Play(
        id="t1",
        game_id=game.id,
        external_play_id="110",
        play_sequence=110,
        quarter=4,
        score_offense=21,
        score_defense=20,
        play_type=PlayType.PASS,
        play_result=PlayResult.INCOMPLETE,
        first_down=False,
        touchdown=False,
        turnover=False,
        raw_description="TWO-POINT CONVERSION ATTEMPT. Pass incomplete. ATTEMPT FAILS.",
        possession_team="BUF",
        defense_team="KC",
        down=None,
        distance=0,
        yardline_100=2,
    )
    curr = Play(
        id="t2",
        game_id=game.id,
        external_play_id="111",
        play_sequence=111,
        quarter=4,
        score_offense=21,
        score_defense=20,
        play_type=PlayType.KICKOFF,
        play_result=PlayResult.KICKOFF_NORMAL,
        first_down=False,
        touchdown=False,
        turnover=False,
        raw_description="Kickoff",
        possession_team="KC",
        defense_team="BUF",
        down=None,
        distance=None,
        yardline_100=40,
    )
    issues = check_quality(game, [prev, curr])
    assert not any(i.rule == "unexplained_possession_change" for i in issues)


def test_quality_possession_flip_unexplained_still_flagged() -> None:
    game = _sample_game()
    prev = Play(
        id="t1",
        game_id=game.id,
        external_play_id="120",
        play_sequence=120,
        quarter=4,
        score_offense=21,
        score_defense=20,
        play_type=PlayType.RUN,
        play_result=PlayResult.RUSH_GAIN,
        first_down=False,
        touchdown=False,
        turnover=False,
        raw_description="Run",
        possession_team="BUF",
        defense_team="KC",
        down=2,
        distance=5,
        yardline_100=50,
    )
    curr = Play(
        id="t2",
        game_id=game.id,
        external_play_id="121",
        play_sequence=121,
        quarter=4,
        score_offense=21,
        score_defense=20,
        play_type=PlayType.RUN,
        play_result=PlayResult.RUSH_GAIN,
        first_down=False,
        touchdown=False,
        turnover=False,
        raw_description="Other team",
        possession_team="KC",
        defense_team="BUF",
        down=1,
        distance=10,
        yardline_100=60,
    )
    issues = check_quality(game, [prev, curr])
    assert any(i.rule == "unexplained_possession_change" for i in issues)

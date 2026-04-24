"""Drive timeline + momentum (``playcaller.review_insights.timeline``)."""

from __future__ import annotations

from playcaller.game import Drive, DriveFeedAuditSnapshot, Game
from playcaller.review_insights.timeline import (
    MIN_DRIVES_FOR_MOMENTUM,
    build_game_flow,
    detect_droughts,
    detect_scoring_runs,
    detect_turning_points,
)


def _audit(outcome: str, *, start_q: int = 1) -> DriveFeedAuditSnapshot:
    return DriveFeedAuditSnapshot(
        espn_display_result=outcome,
        espn_result_code=outcome,
        start_period=start_q,
        start_yard_line=35,
        feed_offensive_plays=6,
        feed_yards=40,
        time_elapsed_display="3:00",
    )


def test_three_same_team_scoring_drives_is_scoring_run() -> None:
    g = Game.new_game()
    tid = "9"
    g.drives = [
        Drive(feed_audit=_audit("TOUCHDOWN"), feed_team_espn_id=tid, feed_team_abbr="GB"),
        Drive(feed_audit=_audit("TOUCHDOWN"), feed_team_espn_id=tid, feed_team_abbr="GB"),
        Drive(feed_audit=_audit("FIELD GOAL"), feed_team_espn_id=tid, feed_team_abbr="GB"),
    ]
    runs = detect_scoring_runs(g)
    assert len(runs) == 1
    assert runs[0].start_drive == 1
    assert runs[0].end_drive == 3
    assert runs[0].points_scored >= 17


def test_four_consecutive_punts_same_team_is_drought() -> None:
    g = Game.new_game()
    tid = "9"
    g.drives = [
        Drive(feed_audit=_audit("PUNT"), feed_team_espn_id=tid, feed_team_abbr="GB"),
        Drive(feed_audit=_audit("PUNT"), feed_team_espn_id=tid, feed_team_abbr="GB"),
        Drive(feed_audit=_audit("PUNT"), feed_team_espn_id=tid, feed_team_abbr="GB"),
        Drive(feed_audit=_audit("PUNT"), feed_team_espn_id=tid, feed_team_abbr="GB"),
    ]
    d = detect_droughts(g)
    assert len(d) == 1
    assert d[0].start_drive == 1
    assert d[0].end_drive == 4


def test_response_drive_after_opponent_score() -> None:
    g = Game.new_game()
    our = "9"
    opp = "8"
    g.drives = [
        Drive(
            feed_audit=_audit("TOUCHDOWN"),
            feed_team_espn_id=opp,
            feed_team_abbr="DET",
        ),
        Drive(
            feed_audit=_audit("PUNT"),
            feed_team_espn_id=our,
            feed_team_abbr="GB",
        ),
    ]
    tps = detect_turning_points(g, our_coached_espn_id=our)
    assert any(tp.category == "response" and tp.drive_number == 2 for tp in tps)


def test_short_game_suppresses_momentum_bundle() -> None:
    g = Game.new_game()
    g.drives = [
        Drive(feed_audit=_audit("PUNT"), feed_team_espn_id="9", feed_team_abbr="GB")
        for _ in range(MIN_DRIVES_FOR_MOMENTUM - 1)
    ]
    assert len(g.drives) < MIN_DRIVES_FOR_MOMENTUM
    b = build_game_flow(g, our_coached_espn_id="9")
    assert b.momentum_suppressed
    assert b.scoring_runs == ()
    assert b.droughts == ()
    assert b.turning_points == ()


def test_timeline_row_count_matches_drive_count() -> None:
    g = Game.new_game()
    g.drives = [
        Drive(feed_audit=_audit("PUNT"), feed_team_espn_id="9", feed_team_abbr="GB"),
        Drive(feed_audit=_audit("PUNT"), feed_team_espn_id="8", feed_team_abbr="DET"),
    ]
    b = build_game_flow(g, our_coached_espn_id="9")
    assert len(b.rows) == len(g.drives)

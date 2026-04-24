"""Drive archive debug audit — scoring reconciliation and ESPN metadata flags."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult
from playcaller.drive_audit_report import compute_drive_audit, compute_drive_audit_report
from playcaller.game import (
    DriveFeedAuditSnapshot,
    Game,
    complete_drive_from_plays,
    game_from_json,
    game_to_json,
)


def test_audit_global_warning_when_implied_score_differs_from_board() -> None:
    g = Game.new_game()
    g.offense_points = 24
    g.defense_points = 31
    d = complete_drive_from_plays(
        [
            ActualPlayResult(
                yards_gained=7,
                family="quick_game",
                play_type="pass",
                touchdown=True,
            )
        ],
        possessing_team="offense",
    )
    g.drives = [d]
    _, warns = compute_drive_audit_report(g)
    assert any("session scoreboard" in w for w in warns)
    assert any("7" in w or "24" in w for w in warns)

    rep = compute_drive_audit(g)
    assert rep.rows[0].badge == "🔴"
    assert rep.rows[0].severity == "critical"


def test_game_json_roundtrip_preserves_feed_audit() -> None:
    g = Game.new_game()
    audit = DriveFeedAuditSnapshot(
        espn_display_result="Touchdown",
        espn_result_code="TD",
        start_period=2,
        start_clock_display="7:32",
        start_field_text="NYG 35",
    )
    d = complete_drive_from_plays(
        [
            ActualPlayResult(
                yards_gained=12,
                family="quick_game",
                play_type="pass",
                touchdown=True,
            )
        ],
        possessing_team="offense",
        feed_audit=audit,
    )
    g.drives = [d]
    g.offense_points = 7
    g2 = game_from_json(game_to_json(g))
    assert g2.drives[0].feed_audit is not None
    assert g2.drives[0].feed_audit.start_period == 2
    assert g2.drives[0].feed_audit.start_clock_display == "7:32"

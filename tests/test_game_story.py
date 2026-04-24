"""Game Story bullets (``playcaller.review_insights.game_story``)."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult
from playcaller.game import Drive, DriveFeedAuditSnapshot, DriveResult, Game
from playcaller.review_insights.game_story import generate_game_story


def _drive_with_audit(*, outcome: str, start_q: int = 1, yl: int = 55) -> Drive:
    audit = DriveFeedAuditSnapshot(
        espn_display_result=outcome,
        espn_result_code=outcome,
        start_period=start_q,
        start_yard_line=yl,
    )
    return Drive(plays=[], feed_audit=audit, feed_team_espn_id="9")


def test_three_straight_scoring_produces_scoring_bullet() -> None:
    g = Game.new_game()
    g.drives = [
        _drive_with_audit(outcome="TOUCHDOWN", start_q=1),
        _drive_with_audit(outcome="TOUCHDOWN", start_q=1),
        _drive_with_audit(outcome="FIELD GOAL", start_q=1),
    ]
    bullets = generate_game_story(g, [], our_coached_espn_id="9")
    texts = [b.text for b in bullets]
    assert any("3 straight" in t.lower() or "scored on 3" in t.lower() for t in texts)


def test_low_sample_third_down_suppressed() -> None:
    g = Game.new_game()
    # Single drive — third-down stats should not emit conversion bullet
    p = ActualPlayResult(
        family="inside_zone",
        play_type="run",
        yards_gained=2,
        feed_presnap_down=3,
        feed_presnap_distance=2,
        first_down=False,
    )
    g.drives = [
        Drive(plays=[p], possessing_team="offense", feed_team_espn_id="9"),
    ]
    bullets = generate_game_story(g, [], our_coached_espn_id="9")
    assert not any("3rd down" in b.text.lower() for b in bullets)


def test_deterministic_order() -> None:
    g = Game.new_game()
    g.drives = [
        _drive_with_audit(outcome="TOUCHDOWN", start_q=1),
        _drive_with_audit(outcome="TOUCHDOWN", start_q=1),
        _drive_with_audit(outcome="TOUCHDOWN", start_q=1),
    ]
    a = [b.text for b in generate_game_story(g, [], our_coached_espn_id="9")]
    b = [b.text for b in generate_game_story(g, [], our_coached_espn_id="9")]
    assert a == b


def test_top_bullets_sorted_by_significance() -> None:
    g = Game.new_game()
    # 3 scoring + many drives for half split - significance sorts scoring run first
    g.drives = [
        _drive_with_audit(outcome="TOUCHDOWN", start_q=1),
        _drive_with_audit(outcome="TOUCHDOWN", start_q=1),
        _drive_with_audit(outcome="TOUCHDOWN", start_q=1),
    ]
    bullets = generate_game_story(g, [], our_coached_espn_id="9")
    if len(bullets) >= 2:
        assert bullets[0].significance >= bullets[1].significance

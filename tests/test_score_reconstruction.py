"""Drive implied score (warehouse play-level) and reconciliation helpers."""

from __future__ import annotations

from playcaller.domain import ActualPlayResult
from playcaller.game import DRIVE_END_UNKNOWN, Game, complete_drive_from_plays
from playcaller.implied_scoring import (
    points_for_play,
    warehouse_possession_one_team_only_warning,
    warehouse_session_points_for_play,
)
from warehouse.taxonomy import PlayResult, PlayType


def _warehouse_game(
    h: int,
    a: int,
    d1: list[ActualPlayResult],
    d1_side: str = "offense",
    d2: list[ActualPlayResult] | None = None,
    d2_side: str = "defense",
) -> Game:
    dr1 = complete_drive_from_plays(d1, end_kind_override=DRIVE_END_UNKNOWN, possessing_team=d1_side)
    drives = [dr1]
    if d2 is not None:
        drives.append(complete_drive_from_plays(d2, end_kind_override=DRIVE_END_UNKNOWN, possessing_team=d2_side))
    return Game(
        drives=drives,
        offense_points=h,
        defense_points=a,
        session_metadata={
            "warehouse_processed": True,
            "warehouse_home_team": "H",
            "warehouse_away_team": "A",
            "warehouse_offense_is_home": True,
        },
    )


def _fp(wt: str, wr: str, *, ab: str = "H", db: str | None = "A", td: bool = False) -> ActualPlayResult:
    psrc = "feed" if (ab and str(ab).strip()) else "missing"
    dsrc = "feed" if (db and str(db).strip()) else "missing"
    return ActualPlayResult(
        feed_warehouse_play_type=wt,
        feed_warehouse_play_result=wr,
        feed_possession_team_abbr=ab,
        display_possession_team_abbr=ab,
        posteam_source=psrc,
        defteam_source=dsrc,
        feed_defense_team_abbr=db,
        touchdown=td,
    )


def test_td_pat_separation() -> None:
    d = [
        _fp("PASS", "TOUCHDOWN_PASS", ab="H"),
        _fp("EXTRA_POINT", "EXTRA_POINT_MADE", ab="H"),
    ]
    g = _warehouse_game(7, 0, d)
    a, b, r, src, _ = warehouse_session_points_for_play(d[0], None, g, home_team="H", away_team="A")
    assert a + b == 6 and r == 6
    a2, b2, r2, src2, _ = warehouse_session_points_for_play(d[1], d[0], g, home_team="H", away_team="A")
    assert a2 + b2 + a + b == 7
    assert r2 == 1 and src2 == "enum"


def test_no_pat_assumption() -> None:
    d = [_fp("PASS", "TOUCHDOWN_PASS", ab="H")]
    g = _warehouse_game(6, 0, d)
    a, b, r, src, _ = warehouse_session_points_for_play(d[0], None, g, home_team="H", away_team="A")
    assert a + b == 6
    assert r == 6


def test_opponent_scoring() -> None:
    d1 = [_fp("PASS", "TOUCHDOWN_PASS", ab="H"), _fp("EXTRA_POINT", "EXTRA_POINT_MADE", ab="H")]
    d2 = [_fp("FIELD_GOAL", "FIELD_GOAL_MADE", ab="A")]
    g = _warehouse_game(7, 3, d1, d2=d2)
    prev: ActualPlayResult | None = None
    o = de = 0
    for dr in g.drives:
        for p in dr.plays:
            a, b, r, _, _ = warehouse_session_points_for_play(p, prev, g, home_team="H", away_team="A")
            o += a
            de += b
            prev = p
    assert o == 7
    assert de == 3


def test_drive_score_matches_game() -> None:
    """Mini 6+ scoring events (both teams), explicit plays only; matches :attr:`Game` board."""
    d1 = [
        _fp("PASS", "TOUCHDOWN_PASS", ab="H"),
        _fp("EXTRA_POINT", "EXTRA_POINT_MADE", ab="H"),
        _fp("FIELD_GOAL", "FIELD_GOAL_MADE", ab="H"),
    ]
    d2 = [
        _fp("RUN", "TOUCHDOWN_RUN", ab="A"),
        _fp("EXTRA_POINT", "EXTRA_POINT_MADE", ab="A"),
        _fp("FIELD_GOAL", "FIELD_GOAL_MADE", ab="A"),
    ]
    g = _warehouse_game(10, 10, d1, d2=d2)
    prev: ActualPlayResult | None = None
    o = de = 0
    for dr in g.drives:
        for p in dr.plays:
            a, b, _, _, _ = warehouse_session_points_for_play(p, prev, g, home_team="H", away_team="A")
            o += a
            de += b
            prev = p
    assert o == 10
    assert de == 10


def test_defensive_td_credits_defense() -> None:
    p = _fp("PASS", "TOUCHDOWN_RETURN", ab="A", db="H")
    pts, side = points_for_play(p, home_team="H", away_team="A")
    assert pts == 6
    assert side == "away"
    g = _warehouse_game(0, 6, [p], d1_side="defense")
    a, b, r, src, _ = warehouse_session_points_for_play(p, None, g, home_team="H", away_team="A")
    assert a == 0 and b == 6 and r == 6
    assert src == "enum"


def test_safety_credits_defense() -> None:
    p = ActualPlayResult(
        feed_warehouse_play_type=PlayType.PASS.value,
        feed_warehouse_play_result=PlayResult.SAFETY.value,
        feed_possession_team_abbr="H",
        display_possession_team_abbr="H",
        posteam_source="feed",
        defteam_source="feed",
        feed_defense_team_abbr="A",
    )
    pts, side = points_for_play(p, home_team="H", away_team="A")
    assert pts == 2
    assert side == "away"
    g = _warehouse_game(0, 2, [p], d1_side="offense")
    a, b, r, src, _ = warehouse_session_points_for_play(p, None, g, home_team="H", away_team="A")
    assert a == 0 and b == 2
    assert r == 2 and src == "enum"


def test_drive_coverage_check_fires_when_one_team_missing() -> None:
    d = [
        _fp("PASS", "TOUCHDOWN_PASS", ab="H"),
        _fp("EXTRA_POINT", "EXTRA_POINT_MADE", ab="H"),
    ]
    g = _warehouse_game(7, 0, d, d1_side="offense", d2=None)
    w = warehouse_possession_one_team_only_warning(g)
    assert w is not None
    assert "only" in w.lower() and "offense" in w.lower()

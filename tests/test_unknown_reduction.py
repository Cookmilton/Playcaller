"""
UNKNOWN reduction: kickoff-lagged conversion delta (Category 2) and scoring-path guards.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from playcaller.domain import ActualPlayResult
from playcaller.game import DRIVE_END_UNKNOWN, Game, complete_drive_from_plays
from playcaller.implied_scoring import (
    UnattributableScoreAccumulator,
    attribute_scoring_points,
    implied_totals_and_breakdown_from_warehouse_plays,
    points_for_play,
    warehouse_session_points_for_play,
)


def _game(*plays: ActualPlayResult, o: int = 0, d: int = 0) -> Game:
    dr = complete_drive_from_plays(
        list(plays), end_kind_override=DRIVE_END_UNKNOWN, possessing_team="offense"
    )
    return Game(
        drives=[dr],
        offense_points=o,
        defense_points=d,
        session_metadata={
            "warehouse_processed": True,
            "warehouse_home_team": "H",
            "warehouse_away_team": "A",
            "warehouse_offense_is_home": True,
        },
    )


def _p(
    wt: str,
    wr: str,
    *,
    ch: int,
    ca: int,
    ab: str = "H",
    db: str | None = "A",
    td: bool = False,
) -> ActualPlayResult:
    return ActualPlayResult(
        feed_warehouse_play_type=wt,
        feed_warehouse_play_result=wr,
        feed_possession_team_abbr=ab,
        display_possession_team_abbr=ab,
        posteam_source="feed",
        defteam_source="feed",
        feed_defense_team_abbr=db,
        feed_cumulative_home=ch,
        feed_cumulative_away=ca,
        touchdown=td,
    )


def test_kickoff_lagged_pat_positive() -> None:
    """+2 (two-point) lags to KICKOFF when prior snap was not a dedicated TWO_POINT / EXTRA_POINT row."""
    t1 = _p("RUN", "RUSH_NO_GAIN", ch=0, ca=0, ab="A", db="H")
    t2 = _p("PENALTY_NO_PLAY", "NO_PLAY", ch=0, ca=0, ab="A", db="H")
    t3 = _p("KICKOFF", "KICKOFF_NORMAL", ch=0, ca=2, ab="A", db="H")
    g = _game(t1, t2, t3, o=0, d=2)
    a_off, a_def, r3, s3, _ = warehouse_session_points_for_play(t3, t2, g, home_team="H", away_team="A")
    assert r3 == 2 and s3 == "delta" and a_def == 2 and a_off == 0


def test_kickoff_lagged_pat_negative() -> None:
    """PAT on dedicated EXTRA_POINT row: following KICKOFF +1 must not be double-counted."""
    t1 = _p("PASS", "TOUCHDOWN_PASS", ch=0, ca=0, ab="H", db="A")
    t2 = _p("EXTRA_POINT", "EXTRA_POINT_MADE", ch=0, ca=0, ab="H", db="A")
    t3 = _p("KICKOFF", "KICKOFF_NORMAL", ch=0, ca=1, ab="A", db="H")
    g = _game(t1, t2, t3, o=7, d=0)
    _, _, r2, s2, _ = warehouse_session_points_for_play(t2, t1, g, home_team="H", away_team="A")
    assert (r2, s2) == (1, "enum")
    a_off, a_def, r3, s3, _ = warehouse_session_points_for_play(t3, t2, g, home_team="H", away_team="A")
    assert (r3, s3) == (0, "none") and a_off + a_def == 0


def test_scoring_possession_team_still_locked() -> None:
    p = replace(
        _p("PASS", "TOUCHDOWN_PASS", ch=0, ca=0, ab="H", db="A"),
        posteam_source="inferred_offense_team",
    )
    with pytest.raises(AssertionError, match="scoring field leak"):
        attribute_scoring_points(
            p, 6, team_abbr="H", provenance="inferred_offense_team", role="poss", unattributable=None
        )


def _assert_no_display_possession_in_scoring_code() -> None:
    p = Path(__file__).resolve().parents[1] / "playcaller" / "implied_scoring.py"
    mod = ast.parse(p.read_text(encoding="utf-8"))
    for node in ast.walk(mod):
        if isinstance(node, ast.Attribute):
            n = node.attr
            if n == "display_possession_team_abbr" or n == "display_possession_team":
                raise AssertionError("scoring must not read display possession fields")
        if isinstance(node, ast.Name) and node.id == "display_possession_team_abbr":
            raise AssertionError("scoring must not reference display_possession_team_abbr")


def test_no_display_fallback_in_scoring() -> None:
    _assert_no_display_possession_in_scoring_code()


def test_mini_game_2pt_lag_matches_session() -> None:
    """Hand-constructed: session 0-2, implied 0-2 from KICKOFF lag only (no other scoring)."""
    t0 = _p("RUN", "RUSH_NO_GAIN", ch=0, ca=0, ab="A", db="H")
    t1 = _p("PENALTY_NO_PLAY", "NO_PLAY", ch=0, ca=0, ab="A", db="H")
    t2 = _p("KICKOFF", "KICKOFF_NORMAL", ch=0, ca=2, ab="A", db="H")
    g = _game(t0, t1, t2, o=0, d=2)
    io, id_, _ = implied_totals_and_breakdown_from_warehouse_plays(g)
    assert io == 0 and id_ == 2


def test_corpus_baseline_preserved_trivial_clean_game() -> None:
    t1 = _p("RUN", "RUSH_GAIN", ch=0, ca=0, ab="H", db="A")
    t2 = _p("PUNT", "PUNT_NORMAL", ch=0, ca=0, ab="H", db="A")
    g = _game(t1, t2, o=0, d=0)
    io, id_, _ = implied_totals_and_breakdown_from_warehouse_plays(g)
    assert io == 0 and id_ == 0 and int(g.offense_points) == 0 and int(g.defense_points) == 0


def test_kickoff_punt_miscode_allows_scoreboard_delta() -> None:
    """KICKOFF w/ punt-shaped result: do not admin-skip; +2 is visible to normal delta (DET_CIN style)."""
    t0 = _p("SACK", "SACK_TAKEN", ch=17, ca=35, ab="A", db="H")
    t1 = _p("KICKOFF", "PUNT_FAIR_CATCH", ch=17, ca=37, ab="A", db="H")
    g = _game(t0, t1, o=17, d=37)
    a_off, a_def, r, s, _ = warehouse_session_points_for_play(t1, t0, g, home_team="H", away_team="A")
    assert r == 2 and s == "delta" and a_def == 2


def test_enum_still_unattributable_without_feed_posteam() -> None:
    """Choke point: enum scoring needs feed postem; no silent fallback to display or inference."""
    t1 = replace(
        _p("PASS", "TOUCHDOWN_PASS", ch=0, ca=0, ab="", db="A"),
        feed_possession_team_abbr="",
        posteam_source="",
    )
    n, side = points_for_play(t1, home_team="H", away_team="A", unattributable=UnattributableScoreAccumulator())
    assert (n, side) == (0, None)

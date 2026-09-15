"""
J1.5 — MNF 401872931 (DEN @ KC, 2026-09-14) drive outcome + yards correctness.

Ground-truth notes (1-based drive index, coached DEN=7):
  TD drives: 2, 3, 10, 13, 19 (handoff listed 1/2/9/12/18 — wrong vs export/ESPN)
  FG drives: 16, 17 (handoff listed 15/16)
  First KC drive is index 2; implied score DEN 10 / KC 31.
"""

from __future__ import annotations

import json
from pathlib import Path

from playcaller.drive_audit_report import implied_points_for_drive
from playcaller.game import (
    DRIVE_END_FIELD_GOAL,
    DRIVE_END_TOUCHDOWN,
    OUTCOME_SOURCE_ESPN,
    Game,
)
from playcaller.live_data.espn_completed_drives import extract_completed_drives_from_espn_payload
from playcaller.live_data.espn_import_merge import merge_completed_espn_drives_into_game

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_mnf_401872931.json"
DEN_ID = "7"
EVENT_ID = "401872931"

# 1-based indices after chronological import.
TD_DRIVES_1BASED = (2, 3, 10, 13, 19)
FG_DRIVES_1BASED = (16, 17)


def _imported_game() -> Game:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    feeds = extract_completed_drives_from_espn_payload(payload, event_id=EVENT_ID)
    game = Game.new_game()
    n, _ = merge_completed_espn_drives_into_game(
        game, {}, feeds, coached_team_id=DEN_ID, feed_team_scope="both"
    )
    assert n == 24
    assert len(game.drives) == 24
    return game


def test_mnf_implied_score_den_10_kc_31() -> None:
    game = _imported_game()
    den = sum(implied_points_for_drive(d) for d in game.drives if d.possessing_team == "offense")
    kc = sum(implied_points_for_drive(d) for d in game.drives if d.possessing_team == "defense")
    assert (den, kc) == (10, 31)


def test_mnf_no_drive_total_yards_over_100() -> None:
    game = _imported_game()
    assert max(int(d.total_yards) for d in game.drives) <= 100


def test_mnf_scoring_drive_kinds_and_espn_source() -> None:
    game = _imported_game()
    for i in TD_DRIVES_1BASED:
        dr = game.drives[i - 1]
        assert dr.result is not None
        assert dr.result.kind == DRIVE_END_TOUCHDOWN, f"drive {i}"
        assert dr.outcome_source == OUTCOME_SOURCE_ESPN, f"drive {i}"
    for i in FG_DRIVES_1BASED:
        dr = game.drives[i - 1]
        assert dr.result is not None
        assert dr.result.kind == DRIVE_END_FIELD_GOAL, f"drive {i}"
        assert dr.outcome_source == OUTCOME_SOURCE_ESPN, f"drive {i}"


def test_mnf_first_kc_drive_exactly_one_td_play() -> None:
    """Drive 2 (first KC possession): nullified scramble is not a TD; real +15 is."""
    game = _imported_game()
    d2 = game.drives[1]
    assert d2.possessing_team == "defense"
    tds = [p for p in d2.plays if p.touchdown]
    assert len(tds) == 1
    assert tds[0].yards_gained == 15
    assert tds[0].external_play_id == "401872931379"


def test_mnf_posteam_split_and_unique_play_ids() -> None:
    game = _imported_game()
    den = [d for d in game.drives if d.possessing_team == "offense"]
    kc = [d for d in game.drives if d.possessing_team == "defense"]
    assert len(den) == 12
    assert len(kc) == 12
    ids = [str(p.external_play_id) for d in game.drives for p in d.plays if p.external_play_id]
    assert ids
    assert len(ids) == len(set(ids))

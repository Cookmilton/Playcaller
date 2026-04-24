"""
Regression: coaching insights on Packers @ Lions golden ingest (401772891).

Locks a few high-level story + grade outcomes so tuning weights surfaces intentionally.
"""

from __future__ import annotations

import json
from pathlib import Path

from playcaller.game import Game
from playcaller.live_data.espn_completed_drives import extract_completed_drives_from_espn_payload
from playcaller.live_data.espn_import_merge import merge_completed_espn_drives_into_game
from playcaller.reconciliation.drive_reconciler import reconcile_drive
from playcaller.review_insights import compute_drive_grade, generate_game_story

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_packers_lions_401772891.json"
EVENT_ID = "401772891"
GB_ID = "9"


def _loaded_game() -> Game:
    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    fds = extract_completed_drives_from_espn_payload(data, event_id=EVENT_ID)
    g = Game.new_game()
    g.offense_points = 31
    g.defense_points = 24
    merge_completed_espn_drives_into_game(g, {}, fds, coached_team_id=GB_ID, feed_team_scope="both")
    return g


def test_packers_lions_game_story_has_scoring_run_bullet() -> None:
    g = _loaded_game()
    bullets = generate_game_story(g, [], our_coached_espn_id=GB_ID)
    assert bullets, "expected at least one story beat on full game"
    top = bullets[0]
    assert top.significance >= 80
    assert "scor" in top.text.lower() or "straight" in top.text.lower() or "possession" in top.text.lower()


def test_packers_lions_first_gb_drive_grade_sane() -> None:
    g = _loaded_game()
    dr = g.drives[0]
    assert dr.feed_team_espn_id == GB_ID
    rec = reconcile_drive(dr, espn=dr.feed_audit)
    grade = compute_drive_grade(dr, [], rec, perspective="possession_offense")
    assert grade.letter != "—"
    assert grade.total_score is not None
    # Field goal possession — not a failure tier on offense
    assert grade.total_score >= 40

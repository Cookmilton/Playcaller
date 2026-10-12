"""Contract pin for MNF 401872931 (DEN @ KC).

Load copied from ``_imported_game`` in ``tests/test_j1_mnf_drive_outcomes.py``:
read the tracked summary fixture and merge completed ESPN drives. The same
shape is ``_loaded_game`` in ``tests/test_review_insights_packers_lions.py``.

This does not read ``data/processed/``. That tree is gitignored and absent on
Cloud; the fixture below is in the repo, so a missing file fails the test
instead of skipping.
"""

from __future__ import annotations

import json
from pathlib import Path

from playcaller.drive_audit_report import implied_points_for_drive
from playcaller.game import (
    OUTCOME_SOURCE_ESPN,
    TIME_SOURCE_ESPN,
    YARDS_SOURCE_ESPN,
    Game,
)
from playcaller.live_data.espn_completed_drives import extract_completed_drives_from_espn_payload
from playcaller.live_data.espn_import_merge import merge_completed_espn_drives_into_game

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_mnf_401872931.json"
DEN_ID = "7"
EVENT_ID = "401872931"


def _imported_game() -> Game:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    feeds = extract_completed_drives_from_espn_payload(payload, event_id=EVENT_ID)
    game = Game.new_game()
    n, _, _ = merge_completed_espn_drives_into_game(
        game, {}, feeds, coached_team_id=DEN_ID, feed_team_scope="both"
    )
    assert n == 24
    assert len(game.drives) == 24
    return game


def test_contract_401872931_implied_score_sources_and_plays() -> None:
    game = _imported_game()
    den = [d for d in game.drives if d.possessing_team == "offense"]
    kc = [d for d in game.drives if d.possessing_team == "defense"]
    assert (
        sum(implied_points_for_drive(d) for d in den),
        sum(implied_points_for_drive(d) for d in kc),
    ) == (10, 31)
    assert len(game.drives) == 24
    for i, dr in enumerate(game.drives, 1):
        assert (dr.outcome_source, dr.yards_source, dr.time_source) == (
            OUTCOME_SOURCE_ESPN,
            YARDS_SOURCE_ESPN,
            TIME_SOURCE_ESPN,
        ), f"drive {i}"
    assert (len(den), len(kc)) == (12, 12)
    assert max(int(d.total_yards) for d in game.drives) == 80
    ids = [str(p.external_play_id) for d in game.drives for p in d.plays if p.external_play_id]
    assert len(ids) == len(set(ids)) == 145

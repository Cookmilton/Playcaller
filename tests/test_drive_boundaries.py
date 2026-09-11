"""Drive boundaries: ESPN play ids exist once across DriveLogger and ``game.drives``."""

from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

from playcaller.domain import ActualPlayResult
from playcaller.game import Game, complete_drive_from_plays
from playcaller.live_data.drive_boundaries import PREVIOUS_FEED_DRIVE_OPEN
from playcaller.live_data.espn_football import parse_espn_summary
from playcaller.live_data.sync import SyncOptions, apply_snapshot
from playcaller.state import DriveLogger
from playcaller.streamlit_state.keys import (
    LIVE_FEED_LAST_AUDIT,
    LIVE_FEED_SEEN_PLAY_IDS,
    LIVE_FEED_TEAM_SCOPE,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LAR = "14"


def _summary() -> dict:
    return json.loads((FIXTURES / "espn_summary_live_401872657.json").read_text())


def _scoreboard() -> dict:
    return json.loads((FIXTURES / "espn_scoreboard_live_401872657.json").read_text())


def _snap(summary: dict | None = None, scoreboard: dict | None = None):
    return parse_espn_summary(
        summary if summary is not None else _summary(),
        sport="nfl",
        our_team_id=LAR,
        scoreboard_payload=scoreboard if scoreboard is not None else _scoreboard(),
    )


def _espn_ids(drive_log: DriveLogger, game: Game) -> list[str]:
    ids = [str(p.external_play_id) for p in drive_log.results if p.external_play_id]
    for drive in game.drives:
        for play in drive.plays or []:
            if play.external_play_id:
                ids.append(str(play.external_play_id))
    return ids


def _assert_unique(ids: list[str]) -> None:
    dup = {k: v for k, v in Counter(ids).items() if v > 1}
    assert not dup, dup


def _end_drive(game: Game, drive_log: DriveLogger, session: dict) -> None:
    finished = complete_drive_from_plays(list(drive_log.results), possessing_team="offense")
    game.drives.append(finished)
    drive_log.reset()
    session[LIVE_FEED_SEEN_PLAY_IDS] = []


def test_two_coached_drives_skip_completed_import_until_end_drive() -> None:
    session: dict = {LIVE_FEED_SEEN_PLAY_IDS: [], LIVE_FEED_TEAM_SCOPE: "our"}
    game = Game.new_game()
    dl = DriveLogger()
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=_snap(), options=SyncOptions())
    x_ids = [p.external_play_id for p in dl.results]
    assert x_ids == ["401872657543", "401872657573"]
    n_archived_after_first = len(game.drives)
    _assert_unique(_espn_ids(dl, game))

    sm2 = _summary()
    x = copy.deepcopy(sm2["drives"]["current"])
    sm2["drives"]["previous"] = list(sm2["drives"]["previous"]) + [x]
    sm2["drives"]["current"] = {
        "id": "40187265799",
        "team": dict(x["team"]),
        "plays": copy.deepcopy(x["plays"]),
    }
    for i, play in enumerate(sm2["drives"]["current"]["plays"]):
        play["id"] = f"Y{i}"

    res2 = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=_snap(sm2),
        options=SyncOptions(),
    )
    assert PREVIOUS_FEED_DRIVE_OPEN in res2.skipped_reasons
    assert res2.current_drive_plays_merged == 0
    assert [p.external_play_id for p in dl.results] == x_ids
    assert len(game.drives) == n_archived_after_first
    assert "drive_log_reset:completed_feed_match" not in res2.applied_fields
    aud = session[LIVE_FEED_LAST_AUDIT]
    assert PREVIOUS_FEED_DRIVE_OPEN in (aud.get("skipped") or [])
    _assert_unique(_espn_ids(dl, game))

    _end_drive(game, dl, session)
    res3 = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=_snap(sm2),
        options=SyncOptions(),
    )
    assert res3.current_drive_plays_merged == 2
    assert [p.external_play_id for p in dl.results] == ["Y0", "Y1"]
    archived_ids = [p.external_play_id for d in game.drives for p in (d.plays or []) if p.external_play_id]
    assert archived_ids.count("401872657543") == 1
    assert archived_ids.count("401872657573") == 1
    _assert_unique(_espn_ids(dl, game))


def test_end_drive_after_completion_does_not_duplicate_play_ids() -> None:
    session: dict = {LIVE_FEED_SEEN_PLAY_IDS: [], LIVE_FEED_TEAM_SCOPE: "our"}
    game = Game.new_game()
    dl = DriveLogger()
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=_snap(), options=SyncOptions())
    x_ids = [p.external_play_id for p in dl.results]
    _end_drive(game, dl, session)
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=_snap(), options=SyncOptions())
    _assert_unique(_espn_ids(dl, game))
    for pid in x_ids:
        assert pid not in {p.external_play_id for p in dl.results}


def test_manual_logger_row_is_kept_when_feed_drive_completes() -> None:
    session: dict = {LIVE_FEED_SEEN_PLAY_IDS: [], LIVE_FEED_TEAM_SCOPE: "our"}
    game = Game.new_game()
    dl = DriveLogger()
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=_snap(), options=SyncOptions())
    dl.log(
        ActualPlayResult(
            family="inside_zone",
            concept_name="Manual",
            play_type="run",
            result_type="run",
            yards_gained=3,
            description="manual",
        )
    )
    sm2 = _summary()
    x = copy.deepcopy(sm2["drives"]["current"])
    sm2["drives"]["previous"] = list(sm2["drives"]["previous"]) + [x]
    sm2["drives"]["current"] = {"id": "40187265799", "team": dict(x["team"]), "plays": []}
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=_snap(sm2), options=SyncOptions())
    assert any(p.description == "manual" for p in dl.results)
    assert len(dl.results) == 3

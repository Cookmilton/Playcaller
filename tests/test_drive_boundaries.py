"""Drive boundaries: ESPN play ids exist once across DriveLogger and ``game.drives``."""

from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

from playcaller.domain import ActualPlayResult
from playcaller.game import Game, complete_drive_from_plays
from playcaller.live_data.drive_boundaries import (
    PREVIOUS_FEED_DRIVE_OPEN,
    sort_game_drives_by_feed_sequence,
)
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
    sort_game_drives_by_feed_sequence(game)
    drive_log.reset()
    session[LIVE_FEED_SEEN_PLAY_IDS] = []


def _td_play(base: dict, play_id: str) -> dict:
    td = copy.deepcopy(base)
    td["id"] = play_id
    td["sequenceNumber"] = "60000"
    td["text"] = "M.Stafford pass complete to P.Nacua for 66 yards, TOUCHDOWN."
    td["statYardage"] = 66
    td["scoringPlay"] = True
    td["type"] = {"id": "67", "text": "Passing Touchdown", "abbreviation": "TD"}
    return td


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


def test_tail_td_between_syncs_is_in_logger_then_archived() -> None:
    session: dict = {LIVE_FEED_SEEN_PLAY_IDS: [], LIVE_FEED_TEAM_SCOPE: "our"}
    game = Game.new_game()
    dl = DriveLogger()
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=_snap(), options=SyncOptions())
    assert [p.external_play_id for p in dl.results] == ["401872657543", "401872657573"]

    sm2 = _summary()
    x = copy.deepcopy(sm2["drives"]["current"])
    td_id = "401872657600"
    x["plays"] = list(x["plays"]) + [_td_play(x["plays"][-1], td_id)]
    sm2["drives"]["previous"] = list(sm2["drives"]["previous"]) + [x]
    sm2["drives"]["current"] = {
        "id": "40187265799",
        "team": dict(x["team"]),
        "plays": [
            {**copy.deepcopy(x["plays"][0]), "id": "Y0", "sequenceNumber": "90000"},
            {**copy.deepcopy(x["plays"][1]), "id": "Y1", "sequenceNumber": "90100"},
        ],
    }
    res2 = apply_snapshot(
        game=game, session=session, drive_log=dl, snapshot=_snap(sm2), options=SyncOptions()
    )
    assert PREVIOUS_FEED_DRIVE_OPEN in res2.skipped_reasons
    assert td_id in [p.external_play_id for p in dl.results]
    assert any("TOUCHDOWN" in (p.description or "").upper() or p.touchdown for p in dl.results)
    _assert_unique(_espn_ids(dl, game))
    n_before_end = len(game.drives)

    _end_drive(game, dl, session)
    assert td_id in [p.external_play_id for d in game.drives for p in (d.plays or [])]
    _assert_unique(_espn_ids(dl, game))

    res3 = apply_snapshot(
        game=game, session=session, drive_log=dl, snapshot=_snap(sm2), options=SyncOptions()
    )
    assert res3.current_drive_plays_merged == 2
    assert [p.external_play_id for p in dl.results] == ["Y0", "Y1"]
    assert len(game.drives) == n_before_end + 1
    _assert_unique(_espn_ids(dl, game))


def test_archived_drives_order_by_espn_sequence_not_insertion() -> None:
    session: dict = {LIVE_FEED_SEEN_PLAY_IDS: [], LIVE_FEED_TEAM_SCOPE: "our"}
    game = Game.new_game()
    dl = DriveLogger()
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=_snap(), options=SyncOptions())
    n_prior = len(game.drives)

    sm2 = _summary()
    x = copy.deepcopy(sm2["drives"]["current"])
    later_opp = {
        "id": "401872657z",
        "team": {"id": "25", "abbreviation": "SF"},
        "plays": [
            {
                **copy.deepcopy(x["plays"][0]),
                "id": "401872657900",
                "sequenceNumber": "90000",
            }
        ],
    }
    sm2["drives"]["previous"] = list(sm2["drives"]["previous"]) + [x, later_opp]
    sm2["drives"]["current"] = {"id": "40187265799", "team": {"id": "25"}, "plays": []}
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=_snap(sm2), options=SyncOptions())
    imported_ids = [
        p.external_play_id for d in game.drives[n_prior:] for p in (d.plays or []) if p.external_play_id
    ]
    assert imported_ids == ["401872657900"]
    assert [p.external_play_id for p in dl.results] == ["401872657543", "401872657573"]

    _end_drive(game, dl, session)
    seq_ids = []
    for d in game.drives:
        pids = [p.external_play_id for p in (d.plays or []) if p.external_play_id]
        if pids:
            seq_ids.append(min(int(pid) for pid in pids if str(pid).isdigit()))
    assert seq_ids == sorted(seq_ids)
    x_idx = next(
        i
        for i, d in enumerate(game.drives)
        if any(p.external_play_id == "401872657543" for p in (d.plays or []))
    )
    z_idx = next(
        i
        for i, d in enumerate(game.drives)
        if any(p.external_play_id == "401872657900" for p in (d.plays or []))
    )
    assert x_idx < z_idx
    _assert_unique(_espn_ids(dl, game))


def _drive_with(*, seq: int | None, pid: str = "", epoch: int | None = None) -> object:
    from playcaller.game import Drive

    plays = []
    if seq is not None or pid:
        plays = [
            ActualPlayResult(
                family="inside_zone",
                play_type="run",
                yards_gained=1,
                external_play_id=pid or None,
                feed_sequence_number=seq,
            )
        ]
    return Drive(plays=plays, possessing_team="offense", session_drive_epoch=epoch)


def test_sort_uses_sequence_number_not_play_id() -> None:
    from playcaller.game import Game
    from playcaller.live_data.drive_boundaries import sort_game_drives_by_feed_sequence

    late_id_early_seq = _drive_with(seq=10, pid="999")
    early_id_late_seq = _drive_with(seq=50, pid="001")
    game = Game(drives=[late_id_early_seq, early_id_late_seq])
    sort_game_drives_by_feed_sequence(game)
    assert game.drives[0] is late_id_early_seq
    assert game.drives[1] is early_id_late_seq


def test_manual_drive_keeps_middle_slot() -> None:
    from playcaller.game import Game
    from playcaller.live_data.drive_boundaries import sort_game_drives_by_feed_sequence

    espn_late = _drive_with(seq=90, pid="z")
    manual = _drive_with(seq=None, epoch=7)
    espn_early = _drive_with(seq=10, pid="a")
    game = Game(drives=[espn_late, manual, espn_early])
    sort_game_drives_by_feed_sequence(game)
    assert game.drives[0] is espn_early
    assert game.drives[1] is manual
    assert game.drives[2] is espn_late


def test_sort_does_not_raise_on_missing_sequence() -> None:
    from playcaller.game import Game
    from playcaller.live_data.drive_boundaries import sort_game_drives_by_feed_sequence

    game = Game(drives=[_drive_with(seq=None), _drive_with(seq=3, pid="p")])
    sort_game_drives_by_feed_sequence(game)


def test_re_sort_does_not_move_review_or_comparison_identity() -> None:
    from playcaller.game import Game, DriveResult, drive_index_for_session_epoch
    from playcaller.live_data.drive_boundaries import (
        archived_drive_identity_key,
        sort_game_drives_by_feed_sequence,
    )
    from playcaller.review.derived import _game_drive_headline
    from playcaller.review.unified_review import ReviewMode, build_unified_rows_from_audit

    coached = _drive_with(seq=80, pid="coached", epoch=0)
    coached.result = DriveResult(kind="punt", headline="Coached punt", detail_line="3 plays")
    imported = _drive_with(seq=10, pid="imported")
    imported.result = DriveResult(kind="touchdown", headline="Import TD", detail_line="1 play")
    game = Game(drives=[coached, imported])
    marker = archived_drive_identity_key(coached)
    game.recommendation_audit = [
        {
            "status": "closed",
            "drive_epoch": 0,
            "plays_at_recommend": 0,
            "pre_snap": {"down": 1, "distance": 10, "yardline": 25, "territory": "own"},
            "selected_family": "inside_zone",
            "linked_actual": {"family": "inside_zone", "play_type": "run", "yards_gained": 1},
        }
    ]
    sort_game_drives_by_feed_sequence(game)
    assert game.drives[0] is imported
    assert game.drives[1] is coached
    assert archived_drive_identity_key(coached) == marker
    assert drive_index_for_session_epoch(game, 0) == 1
    from playcaller.game import display_drive_detail_line

    assert _game_drive_headline(game, 0) == f"Coached punt — {display_drive_detail_line(coached)}"
    rows = build_unified_rows_from_audit(game, game.recommendation_audit, ReviewMode.TRUE_STORED)
    assert rows[0].drive_id == 1
    assert rows[0].drive_result_kind == "punt"

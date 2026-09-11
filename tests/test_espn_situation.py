"""
ESPN live situation sourcing: scoreboard block, ``last_play_end`` fallback, and honest skips.

Fixtures are trimmed captures of a real live game (SF @ LAR, event 401872657, 1st quarter):
LAR is **home** with ESPN id ``14``, SF is **away** with id ``25``, and LAR has the ball at
its own 34 on 2nd & 1.
"""

import copy
import json
from pathlib import Path

import pytest

from playcaller.game import Game
from playcaller.live_data.espn_football import parse_espn_summary
from playcaller.live_data.espn_situation import (
    parse_last_play_end_situation,
    parse_scoreboard_situation,
    scoreboard_event_competition,
    situation_timeouts_for_coached_team,
    yards_to_endzone_from_possession_text,
)
from playcaller.live_data.sync import (
    SITUATION_FIELDS,
    SKIP_ABSENT_IN_SOURCE,
    SKIP_LOCKED,
    SKIP_NO_SITUATION_SOURCE,
    SKIP_OUT_OF_RANGE,
    SyncOptions,
    apply_snapshot,
)
from playcaller.state import DriveLogger
from playcaller.streamlit_state.keys import (
    GAME_DISTANCE,
    GAME_DOWN,
    GAME_OPP_TOS,
    GAME_OWN_TOS,
    GAME_POSSESSION_SIDE,
    GAME_TERRITORY,
    GAME_YARDLINE,
    LIVE_FEED_SEEN_PLAY_IDS,
    LIVE_FEED_TEAM_SCOPE,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EVENT = "401872657"
LAR, SF = "14", "25"


def _summary() -> dict:
    return json.loads((FIXTURES / "espn_summary_live_401872657.json").read_text(encoding="utf-8"))


def _scoreboard() -> dict:
    return json.loads((FIXTURES / "espn_scoreboard_live_401872657.json").read_text(encoding="utf-8"))


def _snapshot(summary=None, scoreboard=None, *, our_team_id=LAR, scoreboard_error=None):
    return parse_espn_summary(
        summary if summary is not None else _summary(),
        sport="nfl",
        our_team_id=our_team_id,
        scoreboard_payload=scoreboard,
        scoreboard_error=scoreboard_error,
    )


def _apply(snap, *, options=None, session=None, drive_log=None):
    ss = session if session is not None else {LIVE_FEED_SEEN_PLAY_IDS: []}
    res = apply_snapshot(
        game=Game.new_game(),
        session=ss,
        drive_log=drive_log if drive_log is not None else DriveLogger(),
        snapshot=snap,
        options=options or SyncOptions(),
    )
    return res, ss


def _skips(res) -> dict[str, str]:
    return {e["field"]: e["reason"] for e in res.skipped_reasons if isinstance(e, dict)}


# --------------------------------------------------------------------------- possessionText


@pytest.mark.parametrize(
    ("text", "own_abbr", "expected"),
    [
        ("LAR 34", "LAR", 66),  # own side: 34 from own goal -> 66 to go
        ("SF 34", "LAR", 34),  # opponent side: 34 to go
        ("50", "LAR", 50),  # midfield, no abbreviation
        ("LAR 50", "LAR", 50),  # midfield named from our side
        ("LAR 1", "LAR", 99),  # backed up on our own goal line
        ("SF 1", "LAR", 1),  # goal-to-go
        ("LAR 34", "", None),  # possessing team unknown -> refuse to guess
        ("midfield", "LAR", None),  # unparseable
        ("", "LAR", None),
        (None, "LAR", None),
        ("LAR 60", "LAR", None),  # impossible yard number
    ],
)
def test_yards_to_endzone_from_possession_text(text, own_abbr, expected) -> None:
    assert yards_to_endzone_from_possession_text(text, possession_team_abbr=own_abbr) == expected


# --------------------------------------------------------------------------- source selection


def test_scoreboard_event_selected_by_id_not_position() -> None:
    comp = scoreboard_event_competition(_scoreboard(), event_id=EVENT)
    assert comp is not None
    assert comp["id"] == EVENT
    # The decoy event is listed first; selecting by position would have returned it.
    assert _scoreboard()["events"][0]["id"] != EVENT


def test_scoreboard_event_absent_returns_none() -> None:
    assert scoreboard_event_competition(_scoreboard(), event_id="404000000") is None


def test_live_scoreboard_situation_is_primary_source() -> None:
    snap = _snapshot(scoreboard=_scoreboard())
    assert snap.situation_source == "scoreboard"
    assert snap.down == 2
    assert snap.distance == 1
    assert snap.yards_to_endzone == 66
    assert snap.abs_yards_from_own_goal == 34
    assert snap.possession_team_id == LAR
    assert snap.possession_is_our_team is True
    assert snap.current_feed_drive_id == "4018726573"


def test_scoreboard_situation_applies_every_field() -> None:
    res, ss = _apply(_snapshot(scoreboard=_scoreboard()))
    assert res.situation_source == "scoreboard"
    assert _skips(res) == {}
    assert ss[GAME_DOWN] == 2
    assert ss[GAME_DISTANCE] == 1
    assert ss[GAME_TERRITORY] == "own"
    assert ss[GAME_YARDLINE] == 34
    assert ss[GAME_POSSESSION_SIDE] == "Our team"
    for f in SITUATION_FIELDS:
        assert f in res.applied_fields


def test_missing_scoreboard_falls_back_to_last_play_end() -> None:
    snap = _snapshot(scoreboard=None)
    assert snap.situation_source == "last_play_end"
    assert snap.down == 2
    assert snap.distance == 1
    assert snap.yards_to_endzone == 66
    assert snap.possession_team_id == LAR
    assert any("drives.current.plays[-1].end" in n for n in snap.debug_notes)


def test_scoreboard_fetch_error_falls_back_and_notes_the_error() -> None:
    snap = _snapshot(scoreboard=None, scoreboard_error="timed out")
    assert snap.situation_source == "last_play_end"
    assert any("scoreboard fetch failed (timed out)" in n for n in snap.debug_notes)


def test_event_absent_from_scoreboard_falls_back() -> None:
    sb = _scoreboard()
    sb["events"] = [e for e in sb["events"] if e["id"] != EVENT]
    snap = _snapshot(scoreboard=sb)
    assert snap.situation_source == "last_play_end"
    assert any("not present in the scoreboard response" in n for n in snap.debug_notes)


def test_scoreboard_event_without_situation_block_falls_back() -> None:
    sb = _scoreboard()
    for ev in sb["events"]:
        ev["competitions"][0].pop("situation", None)
    snap = _snapshot(scoreboard=sb)
    assert snap.situation_source == "last_play_end"
    assert any("no situation block" in n for n in snap.debug_notes)


def test_both_sources_agree_on_the_live_snap() -> None:
    """The scoreboard block and the play ``end`` object describe the same upcoming snap."""
    sb_sit = parse_scoreboard_situation(_scoreboard(), event_id=EVENT)
    end_sit = parse_last_play_end_situation(_summary())
    assert sb_sit is not None and end_sit is not None
    assert (sb_sit.down, sb_sit.distance, sb_sit.yards_to_endzone, sb_sit.possession_team_id) == (
        end_sit.down,
        end_sit.distance,
        end_sit.yards_to_endzone,
        end_sit.possession_team_id,
    )


# --------------------------------------------------------------------------- no source at all


def test_no_situation_source_skips_every_field_with_a_reason() -> None:
    sm = _summary()
    sm["drives"]["current"]["plays"] = []
    snap = _snapshot(sm, scoreboard=None)
    assert snap.situation_source is None
    assert snap.down is None and snap.distance is None
    assert snap.yards_to_endzone is None and snap.possession_team_id is None

    res, ss = _apply(snap)
    assert res.situation_source is None
    assert _skips(res) == {f: SKIP_NO_SITUATION_SOURCE for f in SITUATION_FIELDS}
    for key in (GAME_DOWN, GAME_DISTANCE, GAME_TERRITORY, GAME_YARDLINE, GAME_POSSESSION_SIDE):
        assert key not in ss
    assert any("unavailable from both" in n for n in snap.debug_notes)


def test_last_play_without_end_object_has_no_source() -> None:
    sm = _summary()
    for p in sm["drives"]["current"]["plays"]:
        p.pop("end", None)
    assert parse_last_play_end_situation(sm) is None


# --------------------------------------------------------------------------- possession


def test_empty_possession_never_defaults_to_our_ball() -> None:
    sb = _scoreboard()
    sb["events"][1]["competitions"][0]["situation"]["possession"] = ""
    sm = _summary()
    for p in sm["drives"]["current"]["plays"]:
        p["end"].pop("team", None)
    sm["drives"]["current"].pop("team", None)

    snap = _snapshot(sm, scoreboard=sb)
    assert snap.situation_source == "scoreboard"
    assert snap.possession_team_id is None
    assert snap.possession_is_our_team is None
    # Field position needs the possessing team to know which side "LAR 34" names.
    assert snap.yards_to_endzone is None

    res, ss = _apply(snap)
    assert _skips(res)["possession"] == SKIP_ABSENT_IN_SOURCE
    assert _skips(res)["field_position"] == SKIP_ABSENT_IN_SOURCE
    assert GAME_POSSESSION_SIDE not in ss


def test_opponent_possession_maps_to_opponent() -> None:
    """Same payload, coached from the SF sideline: LAR's ball is the opponent's ball."""
    res, ss = _apply(_snapshot(scoreboard=_scoreboard(), our_team_id=SF))
    assert ss[GAME_POSSESSION_SIDE] == "Opponent"
    assert "possession" in res.applied_fields


def test_our_scope_skip_message_names_current_feed_drive() -> None:
    from playcaller.live_data.feed_team_scope import current_feed_plays_merge_allowed

    allow, msg = current_feed_plays_merge_allowed(
        scope="our",
        coached_team_id=LAR,
        current_drive_team_espn_id=SF,
        possession_team_id=SF,
    )
    assert allow is False
    assert "current feed drive belongs to opponent" in msg
    assert "possession is opponent" not in msg


def test_possession_change_across_two_syncs_does_not_reset_seen_without_drive_id_change() -> None:
    """Board possession (and even ``drives.current.team``) can flip while the feed drive id is unchanged."""
    session: dict = {LIVE_FEED_SEEN_PLAY_IDS: [], LIVE_FEED_TEAM_SCOPE: "both"}
    game = Game.new_game()
    dl = DriveLogger()

    apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=_snapshot(scoreboard=_scoreboard()),
        options=SyncOptions(),
    )
    assert session["live_feed_last_possession_team_id"] == LAR
    assert session["live_feed_last_current_drive_id"] == "4018726573"
    seen_after_first = list(session[LIVE_FEED_SEEN_PLAY_IDS])
    assert seen_after_first, "first sync should record ESPN play ids"
    rows_after_first = len(dl.results)

    sb2 = _scoreboard()
    sit2 = sb2["events"][1]["competitions"][0]["situation"]
    sit2["possession"] = SF
    sit2["possessionText"] = "SF 25"
    sm2 = _summary()
    sm2["drives"]["current"]["team"] = {"id": SF}
    for p in sm2["drives"]["current"]["plays"]:
        p["end"]["team"] = {"id": SF}

    res2 = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=_snapshot(sm2, scoreboard=sb2),
        options=SyncOptions(),
    )
    assert session["live_feed_last_possession_team_id"] == SF
    assert session["live_feed_last_current_drive_id"] == "4018726573"
    assert res2.current_drive_plays_merged == 0
    assert res2.drive_log_rows_after == rows_after_first
    assert session[LIVE_FEED_SEEN_PLAY_IDS] == seen_after_first


def test_scoreboard_possession_flip_does_not_remerge_same_current_drive() -> None:
    """Scoreboard possession can lead ``drives.current`` by one snap; that must not duplicate the log."""
    session: dict = {LIVE_FEED_SEEN_PLAY_IDS: [], LIVE_FEED_TEAM_SCOPE: "our"}
    game = Game.new_game()
    dl = DriveLogger()

    res1 = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=_snapshot(scoreboard=_scoreboard()),
        options=SyncOptions(),
    )
    assert res1.current_drive_plays_merged > 0
    rows_after_first = len(dl.results)
    ids_after_first = [p.external_play_id for p in dl.results]
    assert ids_after_first
    assert len(ids_after_first) == len(set(ids_after_first))

    sb2 = _scoreboard()
    sit2 = sb2["events"][1]["competitions"][0]["situation"]
    sit2["possession"] = SF
    sit2["possessionText"] = "SF 25"
    sm2 = _summary()
    assert sm2["drives"]["current"]["id"] == _summary()["drives"]["current"]["id"]
    assert sm2["drives"]["current"]["team"]["id"] == LAR

    res2 = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=_snapshot(sm2, scoreboard=sb2),
        options=SyncOptions(),
    )
    assert session["live_feed_last_possession_team_id"] == SF
    assert session[GAME_POSSESSION_SIDE] == "Opponent"
    assert res2.current_drive_plays_merged == 0
    assert len(dl.results) == rows_after_first
    ids_after_second = [p.external_play_id for p in dl.results]
    assert ids_after_second == ids_after_first
    assert len(ids_after_second) == len(set(ids_after_second))


def test_new_current_feed_drive_id_resets_seen_and_merges_new_plays_once() -> None:
    """A new coached-team ``drives.current.id`` clears seen ids so the new plays merge once."""
    session: dict = {LIVE_FEED_SEEN_PLAY_IDS: [], LIVE_FEED_TEAM_SCOPE: "our"}
    game = Game.new_game()
    dl = DriveLogger()

    apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=_snapshot(scoreboard=_scoreboard()),
        options=SyncOptions(),
    )
    first_ids = [p.external_play_id for p in dl.results]
    seen_after_first = set(session[LIVE_FEED_SEEN_PLAY_IDS])
    assert session["live_feed_last_current_drive_id"] == "4018726573"

    sm2 = _summary()
    sm2["drives"]["current"]["id"] = "40187265799"
    new_plays = copy.deepcopy(sm2["drives"]["current"]["plays"])
    for i, play in enumerate(new_plays, start=1):
        play["id"] = f"401872657new{i}"
    sm2["drives"]["current"]["plays"] = new_plays
    new_ids = [p["id"] for p in new_plays]

    res2 = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=_snapshot(sm2, scoreboard=_scoreboard()),
        options=SyncOptions(),
    )
    assert session["live_feed_last_current_drive_id"] == "40187265799"
    assert res2.current_drive_plays_merged == len(new_plays)
    log_ids = [p.external_play_id for p in dl.results]
    for pid in first_ids:
        assert log_ids.count(pid) == 1
    for pid in new_ids:
        assert log_ids.count(pid) == 1
    assert seen_after_first.isdisjoint(set(session[LIVE_FEED_SEEN_PLAY_IDS]))
    assert set(session[LIVE_FEED_SEEN_PLAY_IDS]) == set(new_ids)

    res3 = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=_snapshot(sm2, scoreboard=_scoreboard()),
        options=SyncOptions(),
    )
    assert res3.current_drive_plays_merged == 0
    log_ids_again = [p.external_play_id for p in dl.results]
    for pid in new_ids:
        assert log_ids_again.count(pid) == 1


# --------------------------------------------------------------------------- field position


def test_own_territory_from_scoreboard() -> None:
    _res, ss = _apply(_snapshot(scoreboard=_scoreboard()))
    assert (ss[GAME_TERRITORY], ss[GAME_YARDLINE]) == ("own", 34)


def test_opponent_territory_from_scoreboard() -> None:
    sb = _scoreboard()
    sb["events"][1]["competitions"][0]["situation"]["possessionText"] = "SF 34"
    snap = _snapshot(scoreboard=sb)
    assert snap.yards_to_endzone == 34
    _res, ss = _apply(snap)
    assert (ss[GAME_TERRITORY], ss[GAME_YARDLINE]) == ("opponents", 34)


def test_midfield_fifty_from_scoreboard() -> None:
    sb = _scoreboard()
    sb["events"][1]["competitions"][0]["situation"]["possessionText"] = "50"
    snap = _snapshot(scoreboard=sb)
    assert snap.yards_to_endzone == 50
    _res, ss = _apply(snap)
    assert ss[GAME_YARDLINE] == 50


def test_field_position_ignores_yard_line_key() -> None:
    """``yardLine`` has an inconsistent frame of reference; only ``possessionText`` is used."""
    sb = _scoreboard()
    sb["events"][1]["competitions"][0]["situation"]["yardLine"] = 91
    snap = _snapshot(scoreboard=sb)
    assert snap.yards_to_endzone == 66


def test_yards_to_endzone_out_of_range_is_skipped_not_clamped() -> None:
    sm = _summary()
    sm["drives"]["current"]["plays"][-1]["end"]["yardsToEndzone"] = 120
    snap = _snapshot(sm, scoreboard=None)
    assert snap.yards_to_endzone == 120
    assert snap.abs_yards_from_own_goal is None
    res, ss = _apply(snap)
    assert _skips(res)["field_position"] == SKIP_OUT_OF_RANGE
    assert GAME_YARDLINE not in ss


# --------------------------------------------------------------------------- timeouts


def test_timeouts_when_coached_team_is_home() -> None:
    sb = _scoreboard()
    sit = sb["events"][1]["competitions"][0]["situation"]
    sit["homeTimeouts"], sit["awayTimeouts"] = 1, 2
    _res, ss = _apply(_snapshot(scoreboard=sb, our_team_id=LAR))  # LAR is home
    assert (ss[GAME_OWN_TOS], ss[GAME_OPP_TOS]) == (1, 2)


def test_timeouts_when_coached_team_is_away() -> None:
    sb = _scoreboard()
    sit = sb["events"][1]["competitions"][0]["situation"]
    sit["homeTimeouts"], sit["awayTimeouts"] = 1, 2
    _res, ss = _apply(_snapshot(scoreboard=sb, our_team_id=SF))  # SF is away
    assert (ss[GAME_OWN_TOS], ss[GAME_OPP_TOS]) == (2, 1)


def test_timeouts_absent_on_last_play_end_fallback() -> None:
    res, ss = _apply(_snapshot(scoreboard=None))
    assert _skips(res)["own_timeouts"] == SKIP_ABSENT_IN_SOURCE
    assert _skips(res)["opp_timeouts"] == SKIP_ABSENT_IN_SOURCE
    assert GAME_OWN_TOS not in ss and GAME_OPP_TOS not in ss


def test_timeouts_unknown_coached_side_is_absent_not_guessed() -> None:
    snap = _snapshot(scoreboard=_scoreboard(), our_team_id="9999")
    assert snap.our_timeouts is None and snap.opponent_timeouts is None


def test_out_of_range_timeouts_skipped() -> None:
    sb = _scoreboard()
    sb["events"][1]["competitions"][0]["situation"]["homeTimeouts"] = 7
    res, ss = _apply(_snapshot(scoreboard=sb, our_team_id=LAR))
    assert _skips(res)["own_timeouts"] == SKIP_OUT_OF_RANGE
    assert GAME_OWN_TOS not in ss
    assert ss[GAME_OPP_TOS] == 3


# --------------------------------------------------------------------------- range policy


@pytest.mark.parametrize("bad_down", [0, 5, -1])
def test_kickoff_and_pat_down_values_are_skipped_not_clamped(bad_down) -> None:
    """ESPN uses ``down: 0`` on kickoffs and PATs; the old code clamped it to 1."""
    sb = _scoreboard()
    sb["events"][1]["competitions"][0]["situation"]["down"] = bad_down
    snap = _snapshot(scoreboard=sb)
    assert snap.down == bad_down
    res, ss = _apply(snap)
    assert _skips(res)["down"] == SKIP_OUT_OF_RANGE
    assert GAME_DOWN not in ss
    assert "down" not in res.applied_fields


def test_kickoff_start_down_zero_does_not_leak_via_end_object() -> None:
    """The fallback reads ``end``, which already holds the next snap's down."""
    sm = _summary()
    kickoff = sm["drives"]["current"]["plays"][0]
    assert kickoff["start"]["down"] == 0
    assert kickoff["end"]["down"] == 1


def test_distance_zero_is_skipped() -> None:
    sb = _scoreboard()
    sb["events"][1]["competitions"][0]["situation"]["distance"] = 0
    res, ss = _apply(_snapshot(scoreboard=sb))
    assert _skips(res)["distance"] == SKIP_OUT_OF_RANGE
    assert GAME_DISTANCE not in ss


def test_distance_eleven_applies_inside_number_input_domain() -> None:
    sb = _scoreboard()
    sb["events"][1]["competitions"][0]["situation"]["distance"] = 11
    snap = _snapshot(scoreboard=sb)
    assert snap.distance == 11
    res, ss = _apply(snap)
    assert "distance" not in _skips(res)
    assert ss[GAME_DISTANCE] == 11


def test_distance_outside_widget_domain_is_skipped_and_names_the_widget() -> None:
    """``ui_distance`` is a 1–99 number_input; values outside still skip rather than clamp."""
    sb = _scoreboard()
    sb["events"][1]["competitions"][0]["situation"]["distance"] = 100
    snap = _snapshot(scoreboard=sb)
    assert snap.distance == 100
    res, ss = _apply(snap)
    assert _skips(res)["distance"] == SKIP_OUT_OF_RANGE
    assert GAME_DISTANCE not in ss
    notes = (ss["live_feed_last_audit"] or {})["debug_notes"]
    assert any("ui_distance" in n and "100" in n for n in notes)


def test_large_distance_is_not_clamped_to_twenty_five() -> None:
    sb = _scoreboard()
    sb["events"][1]["competitions"][0]["situation"]["distance"] = 31
    snap = _snapshot(scoreboard=sb)
    assert snap.distance == 31
    res, ss = _apply(snap)
    assert ss[GAME_DISTANCE] == 31
    assert "distance" not in _skips(res)


def test_absent_down_reported_as_absent_in_source() -> None:
    sb = _scoreboard()
    sb["events"][1]["competitions"][0]["situation"].pop("down")
    res, _ss = _apply(_snapshot(scoreboard=sb))
    assert _skips(res)["down"] == SKIP_ABSENT_IN_SOURCE


# --------------------------------------------------------------------------- locks


def test_lock_situation_reports_locked_per_field() -> None:
    res, ss = _apply(
        _snapshot(scoreboard=_scoreboard()), options=SyncOptions(lock_situation=True)
    )
    sk = _skips(res)
    assert sk["down"] == sk["distance"] == sk["field_position"] == SKIP_LOCKED
    assert GAME_DOWN not in ss
    # Possession is not part of the situation lock.
    assert ss[GAME_POSSESSION_SIDE] == "Our team"


def test_lock_score_reports_locked_timeouts() -> None:
    res, ss = _apply(_snapshot(scoreboard=_scoreboard()), options=SyncOptions(lock_score=True))
    sk = _skips(res)
    assert sk["own_timeouts"] == sk["opp_timeouts"] == SKIP_LOCKED
    assert GAME_OWN_TOS not in ss
    assert "score/timeouts locked" in res.skipped_reasons


def test_every_situation_field_is_either_applied_or_skipped() -> None:
    """No situation field may disappear silently, under any source or lock combination."""
    scenarios = [
        (_summary(), _scoreboard(), SyncOptions()),
        (_summary(), None, SyncOptions()),
        (_summary(), _scoreboard(), SyncOptions(lock_situation=True, lock_score=True)),
    ]
    empty = _summary()
    empty["drives"]["current"]["plays"] = []
    scenarios.append((empty, None, SyncOptions()))

    for sm, sb, opts in scenarios:
        res, _ss = _apply(_snapshot(copy.deepcopy(sm), sb), options=opts)
        accounted = set(res.applied_fields) | set(_skips(res))
        assert set(SITUATION_FIELDS) <= accounted, (opts, accounted)


# --------------------------------------------------------------------------- counters


def test_completed_drive_plays_are_counted() -> None:
    session: dict = {LIVE_FEED_SEEN_PLAY_IDS: [], LIVE_FEED_TEAM_SCOPE: "both"}
    dl = DriveLogger()
    res, _ss = _apply(
        _snapshot(scoreboard=_scoreboard()), session=session, drive_log=dl
    )
    expected = sum(len(d.plays) for d in _snapshot(scoreboard=_scoreboard()).completed_feed_drives)
    assert res.drives_imported == 1
    assert res.completed_drive_plays_imported == expected > 0


def test_drive_log_row_accounting_matches_counters() -> None:
    session: dict = {LIVE_FEED_SEEN_PLAY_IDS: [], LIVE_FEED_TEAM_SCOPE: "both"}
    dl = DriveLogger()
    res, _ss = _apply(_snapshot(scoreboard=_scoreboard()), session=session, drive_log=dl)
    assert res.drive_log_rows_before == 0
    assert res.drive_log_rows_after == len(dl.results)
    assert (
        res.drive_log_rows_after - res.drive_log_rows_before
        == res.current_drive_plays_merged + res.plays_appended
    )


def test_situation_source_present_in_sync_detail() -> None:
    _res, ss = _apply(_snapshot(scoreboard=_scoreboard()))
    assert ss["live_feed_last_audit"]["situation_source"] == "scoreboard"
    _res2, ss2 = _apply(_snapshot(scoreboard=None))
    assert ss2["live_feed_last_audit"]["situation_source"] == "last_play_end"


def test_situation_timeouts_helper_rejects_unknown_side() -> None:
    sit = parse_scoreboard_situation(_scoreboard(), event_id=EVENT)
    assert situation_timeouts_for_coached_team(sit, coached_home_away="") == (None, None)
    assert situation_timeouts_for_coached_team(None, coached_home_away="home") == (None, None)

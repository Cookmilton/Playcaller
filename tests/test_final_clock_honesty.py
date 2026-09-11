"""C.7: Final-game period/clock parse, apply-or-skip, and HUD honesty."""

from __future__ import annotations

from playcaller.game import Game
from playcaller.live_data.espn_football import parse_espn_summary
from playcaller.live_data.espn_game_state import infer_espn_period, resolve_espn_clock_seconds
from playcaller.live_data.sync import SKIP_ABSENT_IN_SOURCE, SyncOptions, apply_snapshot
from playcaller.state import DriveLogger
from playcaller.streamlit_state.keys import GAME_PERIOD, GAME_QUARTER_CLOCK_MINS, GAME_QUARTER_CLOCK_SECS
from playcaller.ui.situation_honesty import NOT_SYNCED_TEXT, build_situation_honesty, clock_phrase_from_honesty


def _final_status(*, period=None, display_clock=None, completed=True) -> dict:
    status: dict = {"type": {"completed": completed, "detail": "Final", "name": "STATUS_FINAL"}}
    if period is not None:
        status["period"] = period
    if display_clock is not None:
        status["displayClock"] = display_clock
    return status


def test_infer_period_on_final_uses_status_period_not_q1_default() -> None:
    p, _ = infer_espn_period(_final_status(period=4, display_clock="0:00"))
    assert p == 4


def test_infer_period_on_final_without_period_is_none() -> None:
    """``Final`` in the detail blob is not a quarter — do not invent Q4 or Q1."""
    p, _ = infer_espn_period(_final_status(period=None, display_clock="0:00"))
    assert p is None


def test_final_clock_applies_zero_when_display_clock_present() -> None:
    sec, notes, src = resolve_espn_clock_seconds({}, _final_status(period=4, display_clock="0:00"), is_final=True)
    assert sec == 0
    assert src == "display_clock"
    assert not any("unknown on Final" in n for n in notes)


def test_final_clock_skips_play_text_when_display_clock_absent() -> None:
    payload = {
        "drives": {
            "current": {"plays": [{"text": "(7:05) M.Stafford pass incomplete."}]},
        }
    }
    sec, notes, src = resolve_espn_clock_seconds(payload, _final_status(period=4), is_final=True)
    assert sec is None
    assert src is None
    assert any("unknown on Final" in n for n in notes)


def test_apply_final_period_and_zero_clock() -> None:
    snap = parse_espn_summary(
        {
            "header": {
                "competitions": [
                    {
                        "id": "1",
                        "status": _final_status(period=4, display_clock="0:00"),
                        "competitors": [
                            {"id": "14", "score": "17", "homeAway": "home", "team": {"id": "14", "abbreviation": "LAR"}},
                            {"id": "25", "score": "20", "homeAway": "away", "team": {"id": "25", "abbreviation": "SF"}},
                        ],
                    }
                ]
            },
            "drives": {"current": {"id": "x", "plays": []}, "previous": []},
        },
        sport="nfl",
        our_team_id="25",
    )
    assert snap.is_final is True
    assert snap.quarter == 4
    assert snap.clock_seconds_in_period == 0
    session: dict = {}
    res = apply_snapshot(
        game=Game.new_game(), session=session, drive_log=DriveLogger(), snapshot=snap, options=SyncOptions()
    )
    assert "quarter" in res.applied_fields
    assert "clock" in res.applied_fields
    assert session[GAME_PERIOD] == 4
    assert session[GAME_QUARTER_CLOCK_MINS] == 0
    assert session[GAME_QUARTER_CLOCK_SECS] == 0


def test_apply_final_without_period_or_clock_skips_with_reason() -> None:
    snap = parse_espn_summary(
        {
            "header": {
                "competitions": [
                    {
                        "id": "1",
                        "status": _final_status(period=None),
                        "competitors": [
                            {"id": "14", "score": "17", "homeAway": "home", "team": {"id": "14"}},
                            {"id": "25", "score": "20", "homeAway": "away", "team": {"id": "25"}},
                        ],
                    }
                ]
            },
            "drives": {"current": {"id": "x", "plays": []}, "previous": []},
        },
        sport="nfl",
        our_team_id="25",
    )
    assert snap.quarter is None
    assert snap.clock_seconds_in_period is None
    session: dict = {}
    res = apply_snapshot(
        game=Game.new_game(), session=session, drive_log=DriveLogger(), snapshot=snap, options=SyncOptions()
    )
    skips = {e["field"]: e["reason"] for e in res.skipped_reasons if isinstance(e, dict)}
    assert skips["quarter"] == SKIP_ABSENT_IN_SOURCE
    assert skips["clock"] == SKIP_ABSENT_IN_SOURCE
    assert GAME_PERIOD not in session
    assert "quarter" not in res.applied_fields
    assert "clock" not in res.applied_fields


def test_honesty_marks_quarter_and_clock_not_synced() -> None:
    honesty = build_situation_honesty(
        origin="feed",
        situation_source="scoreboard",
        skipped={"quarter": "absent_in_source", "clock": "absent_in_source"},
        possession="offense",
        down=1,
        distance=10,
        territory="own",
        yardline=25,
        own_timeouts=3,
        opp_timeouts=3,
        period=1,
        seconds_in_quarter=15 * 60,
    )
    assert honesty.quarter.synced is False
    assert honesty.clock.synced is False
    assert honesty.quarter.text == NOT_SYNCED_TEXT
    phrase = clock_phrase_from_honesty(honesty)
    assert NOT_SYNCED_TEXT in phrase
    assert "Q1" not in phrase
    assert "15:00" not in phrase
    assert honesty.unsynced_board_warning is not None
    assert "Quarter" in honesty.unsynced_board_warning
    assert "Clock" in honesty.unsynced_board_warning

import json
from dataclasses import replace
from pathlib import Path

from playcaller.game import Game
from playcaller.live_data.espn_football import (
    fetch_event_teams,
    list_espn_scoreboard_games,
    parse_event_teams_from_summary,
    parse_espn_summary,
    scoreboard_url,
    summary_url,
)
from playcaller.live_data.http_util import JsonFetchResult, http_insecure_ssl_enabled
from playcaller.live_data.sync import SyncOptions, apply_snapshot
from playcaller.live_data.types import NormalizedGameSnapshot
from playcaller.state import DriveLogger
from playcaller.streamlit_state.keys import (
    GAME_DISTANCE,
    GAME_DOWN,
    GAME_PERIOD,
    GAME_QUARTER_CLOCK_MINS,
    GAME_QUARTER_CLOCK_SECS,
    GAME_SCORE_OURS,
    GAME_SCORE_THEIRS,
    GAME_TERRITORY,
    GAME_WIDGET_HYDRATE_PENDING,
    GAME_YARDLINE,
    LIVE_FEED_COACHED_TEAM_ESPN_ID,
    LIVE_FEED_LAST_AUDIT,
    LIVE_FEED_LAST_ORIGIN,
    LIVE_FEED_SEEN_PLAY_IDS,
    LIVE_FEED_TRUSTED_CLOCK,
)
from playcaller.streamlit_state.session import (
    clear_coached_team_espn_session_identity,
    clear_live_feed_session_keys,
    coached_team_espn_id_for_previous_drives,
)
from playcaller.streamlit_state.widget_backend_bridge import sync_widgets_from_backend


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "espn_summary_live_synthetic.json"


def _load_fixture() -> dict:
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def test_parse_event_teams_from_summary() -> None:
    data = _load_fixture()
    et = parse_event_teams_from_summary(data)
    assert et.home_team_id == "10"
    assert et.away_team_id == "14"
    assert "Giant" in et.home_name or "NYG" in et.home_name
    assert "Ram" in et.away_name or "LAR" in et.away_name
    assert et.event_id == "401test001"


def test_fetch_event_teams_uses_summary(monkeypatch) -> None:
    data = _load_fixture()

    def fake_fetch(url: str):
        assert "summary" in url
        return JsonFetchResult(data=data)

    monkeypatch.setattr("playcaller.live_data.espn_football.fetch_json", fake_fetch)
    et, _insecure = fetch_event_teams("nfl", "401test001")
    assert et.away_team_id == "14"


def test_http_insecure_ssl_env(monkeypatch) -> None:
    monkeypatch.delenv("PLAYCALLER_HTTP_INSECURE_SSL", raising=False)
    monkeypatch.delenv("PLAYCALLER_ESPN_INSECURE_SSL", raising=False)
    assert http_insecure_ssl_enabled() is False
    monkeypatch.setenv("PLAYCALLER_ESPN_INSECURE_SSL", "true")
    assert http_insecure_ssl_enabled() is True


def test_parse_espn_summary_fallback_clock_from_play_text() -> None:
    p = Path(__file__).resolve().parent / "fixtures" / "espn_summary_no_display_clock.json"
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    snap = parse_espn_summary(data, sport="nfl", our_team_id="14")
    assert snap.clock_seconds_in_period == 7 * 60 + 32
    assert snap.quarter == 3
    assert any("clock: fallback from play text" in n for n in snap.debug_notes)
    assert snap.clock_resolution == "play_text"


def test_parse_espn_summary_period_inferred_from_detail_when_missing_period_field() -> None:
    p = Path(__file__).resolve().parent / "fixtures" / "espn_summary_period_from_detail_only.json"
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    snap = parse_espn_summary(data, sport="nfl", our_team_id="14")
    assert snap.quarter == 2
    assert any("period: inferred" in n for n in snap.debug_notes)


def test_parse_espn_summary_maps_situation_and_scores() -> None:
    data = _load_fixture()
    snap = parse_espn_summary(data, sport="nfl", our_team_id="14")
    assert snap.external_game_id == "401test001"
    assert snap.quarter == 3
    assert snap.clock_seconds_in_period == 7 * 60 + 5
    assert snap.down == 2
    assert snap.distance == 7
    assert snap.abs_yards_from_own_goal == 100 - 42
    assert snap.possession_team_id == "14"
    assert snap.possession_is_our_team is True
    assert snap.our_score == 10
    assert snap.opponent_score == 14
    assert len(snap.new_plays) == 2
    assert snap.new_plays[0].event_id == "401test001p1"
    assert snap.clock_resolution == "display_clock"


def test_apply_snapshot_updates_session_and_game() -> None:
    data = _load_fixture()
    snap = parse_espn_summary(data, sport="nfl", our_team_id="14")
    game = Game.new_game()
    session: dict = {
        "ui_quarter": 1,
        "ui_clock_mins": 15,
        "ui_clock_secs": 0,
        "ui_down": 1,
        "ui_distance": 10,
        "ui_territory": "own",
        "ui_yardline": 25,
        "ui_possession_side": "Our team",
        "ui_own_tos": 3,
        "ui_opp_tos": 3,
        LIVE_FEED_SEEN_PLAY_IDS: [],
    }
    dl = DriveLogger()
    res = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=snap,
        options=SyncOptions(lock_situation=False, lock_score=False),
    )
    assert res.ok
    assert session[GAME_PERIOD] == 3
    assert session[GAME_QUARTER_CLOCK_MINS] == 7
    assert session[GAME_QUARTER_CLOCK_SECS] == 5
    assert session[GAME_SCORE_OURS] == 10
    assert session[GAME_SCORE_THEIRS] == 14
    assert session[GAME_DOWN] == 2
    assert session["ui_distance"] == 10
    assert session[GAME_DISTANCE] == 7
    assert session[GAME_TERRITORY] == "opponents"
    assert session[GAME_YARDLINE] == 42
    assert session[GAME_WIDGET_HYDRATE_PENDING] is True
    sync_widgets_from_backend(session)
    assert session["ui_game_period"] == 3
    assert session["ui_quarter_clock_mins"] == 7
    assert session["ui_quarter_clock_secs"] == 5
    assert session["ui_score_ours"] == 10
    assert session["ui_score_theirs"] == 14
    assert session["ui_down"] == 2
    assert session["ui_distance"] == 7
    assert session["ui_territory"] == "opponents"
    assert game.offense_points == 10
    assert game.defense_points == 14
    assert session[LIVE_FEED_LAST_ORIGIN] == "feed"
    aud0 = session.get(LIVE_FEED_LAST_AUDIT) or {}
    assert aud0.get("coached_team_id") == "14"
    assert aud0.get("feed_team_scope") == "our"
    assert session.get(LIVE_FEED_COACHED_TEAM_ESPN_ID) == "14"
    assert isinstance(session.get(LIVE_FEED_TRUSTED_CLOCK), dict)
    assert session[LIVE_FEED_TRUSTED_CLOCK].get("source") == "display_clock"


def test_apply_snapshot_retains_trusted_clock_when_displayclock_drops_briefly() -> None:
    data = _load_fixture()
    snap1 = parse_espn_summary(data, sport="nfl", our_team_id="14")
    game = Game.new_game()
    session: dict = {
        LIVE_FEED_SEEN_PLAY_IDS: [],
    }
    apply_snapshot(
        game=game,
        session=session,
        drive_log=DriveLogger(),
        snapshot=snap1,
        options=SyncOptions(lock_situation=False, lock_score=False),
    )
    assert session[GAME_QUARTER_CLOCK_MINS] == 7 and session[GAME_QUARTER_CLOCK_SECS] == 5
    unknown_note = (
        "clock: unknown — ESPN omitted displayClock and no (M:SS) prefix on scanned play texts; "
        "quarter clock not updated this sync."
    )
    snap2 = replace(
        snap1,
        clock_seconds_in_period=None,
        clock_resolution=None,
        debug_notes=(unknown_note,),
        fetched_at_epoch=snap1.fetched_at_epoch + 15.0,
    )
    apply_snapshot(
        game=game,
        session=session,
        drive_log=DriveLogger(),
        snapshot=snap2,
        options=SyncOptions(lock_situation=False, lock_score=False),
    )
    assert session[GAME_QUARTER_CLOCK_MINS] == 7 and session[GAME_QUARTER_CLOCK_SECS] == 5
    assert "clock_retained_trusted" in (session.get(LIVE_FEED_LAST_AUDIT) or {}).get("applied", [])


def test_feed_play_dedup() -> None:
    data = _load_fixture()
    snap = parse_espn_summary(data, sport="nfl", our_team_id="14")
    game = Game.new_game()
    session: dict = {
        "ui_quarter": 3,
        "ui_clock_mins": 7,
        "ui_clock_secs": 5,
        "ui_down": 2,
        "ui_distance": 7,
        "ui_territory": "opponents",
        "ui_yardline": 42,
        "ui_possession_side": "Our team",
        LIVE_FEED_SEEN_PLAY_IDS: ["401test001p1"],
    }
    dl = DriveLogger()
    apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=snap,
        options=SyncOptions(auto_append_feed_plays=True),
    )
    assert len(dl.results) == 1
    assert "[ESPN]" in dl.results[0].description
    assert dl.results[0].external_play_id == "401test001p2"
    apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=snap,
        options=SyncOptions(auto_append_feed_plays=True),
    )
    assert len(dl.results) == 1


def test_lock_situation_skips_field() -> None:
    data = _load_fixture()
    snap = parse_espn_summary(data, sport="nfl", our_team_id="14")
    session: dict = {
        "ui_quarter": 1,
        "ui_clock_mins": 15,
        "ui_clock_secs": 0,
        "ui_down": 1,
        "ui_distance": 10,
        "ui_territory": "own",
        "ui_yardline": 25,
        "ui_possession_side": "Our team",
        LIVE_FEED_SEEN_PLAY_IDS: [],
    }
    game = Game.new_game()
    apply_snapshot(
        game=game,
        session=session,
        drive_log=DriveLogger(),
        snapshot=snap,
        options=SyncOptions(lock_situation=True),
    )
    assert session["ui_down"] == 1
    assert session["ui_distance"] == 10
    assert session["ui_territory"] == "own"
    assert session["ui_yardline"] == 25


def test_territory_yardline_from_abs_round_trip() -> None:
    from playcaller.situation import territory_yardline_from_abs_yards, yards_from_own_goal

    for abs_y in (1, 25, 50, 75, 99):
        t, y = territory_yardline_from_abs_yards(abs_y)
        assert yards_from_own_goal(t, y) == abs_y


def test_list_scoreboard_returns_rows(monkeypatch) -> None:
    def fake_fetch(url: str):
        return JsonFetchResult(
            data={
                "events": [
                    {
                        "id": "999",
                        "name": "A at B",
                        "competitions": [
                            {
                                "status": {"type": {"detail": "In Progress"}},
                                "competitors": [
                                    {"homeAway": "home", "id": "1", "team": {"abbreviation": "HH", "id": "1"}},
                                    {"homeAway": "away", "id": "2", "team": {"abbreviation": "AW", "id": "2"}},
                                ],
                            }
                        ],
                    }
                ]
            }
        )

    monkeypatch.setattr("playcaller.live_data.espn_football.fetch_json", fake_fetch)
    rows, _insecure = list_espn_scoreboard_games("nfl")
    assert rows[0]["id"] == "999"
    assert rows[0]["home_id"] == "1"
    assert rows[0]["away_id"] == "2"


def test_ufl_uses_same_site_api_paths() -> None:
    assert "football/ufl/scoreboard" in scoreboard_url("ufl")
    assert "football/ufl/summary" in summary_url("ufl", "401857536")


def test_clear_live_feed_session_keys_preserves_coached_team_espn_id() -> None:
    ss: dict = {
        LIVE_FEED_COACHED_TEAM_ESPN_ID: "14",
        LIVE_FEED_LAST_AUDIT: {"coached_team_id": "14"},
        LIVE_FEED_LAST_ORIGIN: "feed",
        LIVE_FEED_SEEN_PLAY_IDS: ["a"],
    }
    clear_live_feed_session_keys(ss)
    assert ss.get(LIVE_FEED_COACHED_TEAM_ESPN_ID) == "14"
    assert LIVE_FEED_LAST_AUDIT not in ss


def test_coached_team_espn_id_for_previous_drives_prefers_session_over_audit() -> None:
    ss = {
        LIVE_FEED_COACHED_TEAM_ESPN_ID: "10",
        LIVE_FEED_LAST_AUDIT: {"coached_team_id": "14"},
    }
    assert coached_team_espn_id_for_previous_drives(ss) == "10"


def test_coached_team_espn_id_for_previous_drives_falls_back_to_audit() -> None:
    ss = {LIVE_FEED_LAST_AUDIT: {"coached_team_id": "14"}}
    assert coached_team_espn_id_for_previous_drives(ss) == "14"


def test_clear_coached_team_espn_session_identity() -> None:
    ss = {LIVE_FEED_COACHED_TEAM_ESPN_ID: "14"}
    clear_coached_team_espn_session_identity(ss)
    assert LIVE_FEED_COACHED_TEAM_ESPN_ID not in ss


def test_apply_snapshot_keeps_persistent_coached_team_when_snapshot_has_no_coached_id() -> None:
    session: dict = {
        LIVE_FEED_COACHED_TEAM_ESPN_ID: "14",
        LIVE_FEED_SEEN_PLAY_IDS: [],
    }
    snap = NormalizedGameSnapshot(
        provider="espn",
        external_game_id="x",
        sport="nfl",
        fetched_at_epoch=0.0,
        status_detail="in",
        quarter=2,
        clock_seconds_in_period=600,
        down=1,
        distance=10,
        abs_yards_from_own_goal=50,
        possession_team_id=None,
        possession_is_our_team=True,
        our_score=0,
        opponent_score=0,
        our_timeouts=3,
        opponent_timeouts=3,
        is_final=False,
        coached_team_id=None,
    )
    apply_snapshot(
        game=Game.new_game(),
        session=session,
        drive_log=DriveLogger(),
        snapshot=snap,
        options=SyncOptions(),
    )
    assert session.get(LIVE_FEED_COACHED_TEAM_ESPN_ID) == "14"
    assert (session.get(LIVE_FEED_LAST_AUDIT) or {}).get("coached_team_id") == ""


def test_fetch_snapshot_includes_raw_summary(monkeypatch) -> None:
    from playcaller.live_data.espn_football import EspnFootballProvider

    payload = json.loads(
        (Path(__file__).resolve().parent / "fixtures" / "espn_summary_live_synthetic.json").read_text(
            encoding="utf-8"
        )
    )

    def fake_fetch(_url: str):
        return JsonFetchResult(data=payload)

    monkeypatch.setattr("playcaller.live_data.espn_football.fetch_json", fake_fetch)
    prov = EspnFootballProvider("nfl")
    fr = prov.fetch_snapshot("401000001", our_team_id="14")
    assert fr.ok and fr.snapshot is not None
    assert fr.raw_summary == payload


def test_list_scoreboard_ufl_fetches_ufl_scoreboard(monkeypatch) -> None:
    urls: list[str] = []

    def fake_fetch(url: str):
        urls.append(url)
        return JsonFetchResult(data={"events": []})

    monkeypatch.setattr("playcaller.live_data.espn_football.fetch_json", fake_fetch)
    list_espn_scoreboard_games("ufl")
    assert urls and "football/ufl/scoreboard" in urls[0]

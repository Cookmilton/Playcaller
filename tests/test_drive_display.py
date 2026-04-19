"""Prior-drive headings and per-team sequence numbers."""

from playcaller.domain import ActualPlayResult
from playcaller.game import Drive, DriveResult, Game, complete_drive_from_plays

from playcaller.live_data.drive_display import (
    PREVIOUS_DRIVES_FILTER_BOTH,
    PREVIOUS_DRIVES_FILTER_OPPONENT,
    PREVIOUS_DRIVES_FILTER_OUR,
    chronological_team_drive_indices,
    classify_drive_team_side,
    drive_identity_key,
    filter_previous_drive_indices,
    prior_drive_heading,
    previous_drives_empty_filter_message,
)
from playcaller.streamlit_state.keys import LIVE_FEED_COACHED_TEAM_ESPN_ID, LIVE_FEED_LAST_AUDIT
from playcaller.streamlit_state.session import clear_live_feed_session_keys, coached_team_espn_id_for_previous_drives


def test_chronological_indices_per_team() -> None:
    g = Game.new_game()
    a = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=0, description="p")],
        possessing_team="offense",
        feed_team_espn_id="10",
        feed_team_abbr="NYG",
        feed_team_display_name="Giants",
    )
    b = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=0, description="p")],
        possessing_team="defense",
        feed_team_espn_id="14",
        feed_team_abbr="LAR",
        feed_team_display_name="Rams",
    )
    c = complete_drive_from_plays(
        [ActualPlayResult(yards_gained=0, description="p")],
        possessing_team="offense",
        feed_team_espn_id="10",
        feed_team_abbr="NYG",
        feed_team_display_name="Giants",
    )
    g.drives = [a, b, c]
    assert chronological_team_drive_indices(g) == [1, 1, 2]


def test_prior_drive_heading_uses_feed_names() -> None:
    dr = Drive(
        plays=[],
        possessing_team="offense",
        result=DriveResult(kind="punt", headline="Punt", detail_line="2 plays, 5 yards, 1:16"),
        feed_team_espn_id="10",
        feed_team_abbr="NYG",
        feed_team_display_name="New York Giants",
    )
    h = prior_drive_heading(dr, 2)
    assert "New York Giants" in h
    assert "NYG" in h
    assert "drive 2" in h
    assert "Punt" in h


def test_drive_identity_key_fallback_possession() -> None:
    dr = Drive(plays=[], possessing_team="defense")
    assert drive_identity_key(dr) == "pos:defense"


def test_classify_feed_team_requires_coached_id() -> None:
    dr = Drive(plays=[], feed_team_espn_id="10")
    assert classify_drive_team_side(dr, our_coached_espn_id="") is None
    assert classify_drive_team_side(dr, our_coached_espn_id="10") == "our"
    assert classify_drive_team_side(dr, our_coached_espn_id="14") == "opp"


def test_classify_manual_drive_uses_possession() -> None:
    o = Drive(plays=[], possessing_team="offense", feed_team_espn_id="")
    d = Drive(plays=[], possessing_team="defense", feed_team_espn_id="")
    assert classify_drive_team_side(o, our_coached_espn_id="") == "our"
    assert classify_drive_team_side(d, our_coached_espn_id="") == "opp"


def test_filter_indices_respects_mode_and_missing_metadata() -> None:
    g = Game.new_game()
    g.drives = [
        Drive(plays=[], possessing_team="offense", feed_team_espn_id="10"),
        Drive(plays=[], possessing_team="defense", feed_team_espn_id="14"),
        Drive(plays=[], possessing_team="offense", feed_team_espn_id=""),
    ]
    assert filter_previous_drive_indices(g, mode=PREVIOUS_DRIVES_FILTER_BOTH, our_coached_espn_id="10") == [0, 1, 2]
    assert filter_previous_drive_indices(g, mode=PREVIOUS_DRIVES_FILTER_OUR, our_coached_espn_id="10") == [0, 2]
    assert filter_previous_drive_indices(g, mode=PREVIOUS_DRIVES_FILTER_OPPONENT, our_coached_espn_id="10") == [1]
    # coached id unknown: feed drives are unclassified (hidden in single-team filters); manual still classified
    assert filter_previous_drive_indices(g, mode=PREVIOUS_DRIVES_FILTER_OUR, our_coached_espn_id="") == [2]
    assert filter_previous_drive_indices(g, mode=PREVIOUS_DRIVES_FILTER_OPPONENT, our_coached_espn_id="") == []
    g2 = Game.new_game()
    g2.drives = [
        Drive(plays=[], possessing_team="defense", feed_team_espn_id=""),
    ]
    assert filter_previous_drive_indices(g2, mode=PREVIOUS_DRIVES_FILTER_OPPONENT, our_coached_espn_id="") == [0]


def test_previous_drives_empty_filter_message_names_mode() -> None:
    s = previous_drives_empty_filter_message(PREVIOUS_DRIVES_FILTER_OUR)
    assert "Our team only" in s
    assert "Both teams" in s
    assert previous_drives_empty_filter_message(PREVIOUS_DRIVES_FILTER_OPPONENT)
    assert "Opponent only" in previous_drives_empty_filter_message(PREVIOUS_DRIVES_FILTER_OPPONENT)


def test_filter_stable_after_clear_live_feed_session_keys() -> None:
    """Persistent coached id survives feed cache clear so single-team filters stay consistent."""
    g = Game.new_game()
    g.drives = [
        Drive(plays=[], possessing_team="offense", feed_team_espn_id="10"),
        Drive(plays=[], possessing_team="defense", feed_team_espn_id="14"),
    ]
    ss = {
        LIVE_FEED_COACHED_TEAM_ESPN_ID: "10",
        LIVE_FEED_LAST_AUDIT: {"coached_team_id": "14"},
    }
    clear_live_feed_session_keys(ss)
    our_tid = coached_team_espn_id_for_previous_drives(ss)
    assert our_tid == "10"
    assert filter_previous_drive_indices(g, mode=PREVIOUS_DRIVES_FILTER_OUR, our_coached_espn_id=our_tid) == [0]
    assert filter_previous_drive_indices(g, mode=PREVIOUS_DRIVES_FILTER_OPPONENT, our_coached_espn_id=our_tid) == [1]

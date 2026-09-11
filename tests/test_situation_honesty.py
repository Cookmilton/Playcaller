"""Console honesty helpers: skipped fields, source chip, Generate block, local time."""

from playcaller.streamlit_state.keys import LIVE_FEED_LAST_AUDIT, LIVE_FEED_LAST_ORIGIN
from playcaller.streamlit_state.widget_backend_bridge import (
    GAME_DISTANCE_ALLOWED_VALUES,
    GAME_DISTANCE_MAX,
    GAME_DISTANCE_MIN,
    distance_in_widget_domain,
)
from playcaller.local_time import format_local_epoch_labeled, format_synced_hhmm
from playcaller.ui.situation_honesty import (
    GENERATE_OPPONENT_REASON,
    NOT_SYNCED_TEXT,
    SOURCE_CHIP_LAST_PLAY,
    SOURCE_CHIP_MANUAL,
    SOURCE_CHIP_NOT_SET,
    SOURCE_CHIP_PRESET,
    SOURCE_CHIP_SCOREBOARD,
    UNKNOWN_POSSESSION_TEXT,
    build_situation_honesty,
    defense_look_chip_label,
    generate_blocked_reason,
    honesty_from_session,
    leftover_feed_drive_caption,
    skipped_situation_reasons,
    situation_source_chip_label,
    unsynced_board_warning,
)
from playcaller.streamlit_state.possession import GENERATE_UNSET_POSSESSION_REASON


def test_distance_domain_is_one_to_ninety_nine() -> None:
    assert GAME_DISTANCE_MIN == 1
    assert GAME_DISTANCE_MAX == 99
    assert GAME_DISTANCE_ALLOWED_VALUES[0] == 1
    assert GAME_DISTANCE_ALLOWED_VALUES[-1] == 99
    assert 11 in GAME_DISTANCE_ALLOWED_VALUES
    assert distance_in_widget_domain(11)
    assert not distance_in_widget_domain(0)
    assert not distance_in_widget_domain(100)


def test_source_chip_labels() -> None:
    assert situation_source_chip_label(origin="feed", situation_source="scoreboard") == SOURCE_CHIP_SCOREBOARD
    assert situation_source_chip_label(origin="feed", situation_source="last_play_end") == SOURCE_CHIP_LAST_PLAY
    assert situation_source_chip_label(origin="manual", situation_source="scoreboard") == SOURCE_CHIP_MANUAL
    assert situation_source_chip_label(origin="feed", situation_source=None) == SOURCE_CHIP_NOT_SET
    assert situation_source_chip_label(origin="", situation_source=None) == SOURCE_CHIP_NOT_SET


def test_generate_blocked_on_opponent_and_unset() -> None:
    assert generate_blocked_reason(possession="defense") == GENERATE_OPPONENT_REASON
    assert generate_blocked_reason(possession=None) == GENERATE_UNSET_POSSESSION_REASON
    assert generate_blocked_reason(possession="offense") is None


def test_skipped_field_on_feed_renders_not_synced_not_our_ball() -> None:
    honesty = build_situation_honesty(
        origin="feed",
        situation_source="scoreboard",
        skipped={"possession": "absent_in_source", "distance": "out_of_range"},
        possession="offense",
        down=2,
        distance=10,
        territory="own",
        yardline=25,
        own_timeouts=3,
        opp_timeouts=3,
    )
    assert honesty.possession.text == NOT_SYNCED_TEXT
    assert honesty.possession.synced is False
    assert "Our ball" not in honesty.possession.text
    assert honesty.distance.synced is False
    assert honesty.down.synced is True
    assert honesty.unsynced_board_warning is not None
    assert "Distance" in honesty.unsynced_board_warning


def test_no_situation_source_marks_every_situation_field() -> None:
    honesty = build_situation_honesty(
        origin="feed",
        situation_source=None,
        skipped={},
        possession="offense",
        down=1,
        distance=10,
        territory="own",
        yardline=25,
        own_timeouts=3,
        opp_timeouts=3,
    )
    assert honesty.down.synced is False
    assert honesty.distance.synced is False
    assert honesty.field_position.synced is False
    assert honesty.possession.synced is False
    assert honesty.source_chip == SOURCE_CHIP_NOT_SET


def test_locked_skip_still_shows_operator_board() -> None:
    honesty = build_situation_honesty(
        origin="feed",
        situation_source="scoreboard",
        skipped={"down": "locked", "distance": "locked", "field_position": "locked"},
        possession="offense",
        down=3,
        distance=7,
        territory="opponents",
        yardline=12,
        own_timeouts=2,
        opp_timeouts=1,
    )
    assert honesty.down.synced is True
    assert honesty.down.text == "3"
    assert honesty.unsynced_board_warning is None


def test_manual_origin_shows_our_ball() -> None:
    honesty = build_situation_honesty(
        origin="manual",
        situation_source=None,
        skipped={"possession": "no_situation_source"},
        possession="offense",
        down=1,
        distance=10,
        territory="own",
        yardline=25,
        own_timeouts=3,
        opp_timeouts=3,
    )
    assert honesty.possession.synced is True
    assert honesty.possession.text == "Our ball"
    assert honesty.source_chip == SOURCE_CHIP_MANUAL


def test_fresh_board_chip_not_set_possession_unknown_generate_blocked() -> None:
    honesty = build_situation_honesty(
        origin="",
        situation_source=None,
        skipped={},
        possession=None,
        down=1,
        distance=10,
        territory="own",
        yardline=25,
        own_timeouts=3,
        opp_timeouts=3,
    )
    assert honesty.source_chip == SOURCE_CHIP_NOT_SET
    assert honesty.possession.text == UNKNOWN_POSSESSION_TEXT
    assert honesty.generate_blocked_reason == GENERATE_UNSET_POSSESSION_REASON


def test_honesty_from_session_reads_audit() -> None:
    ss = {
        LIVE_FEED_LAST_ORIGIN: "feed",
        LIVE_FEED_LAST_AUDIT: {
            "situation_source": "last_play_end",
            "skipped": [{"field": "distance", "reason": "out_of_range"}],
        },
    }
    honesty = honesty_from_session(
        ss,
        possession="offense",
        down=2,
        distance=10,
        territory="own",
        yardline=34,
        own_timeouts=3,
        opp_timeouts=3,
    )
    assert honesty.source_chip == SOURCE_CHIP_LAST_PLAY
    assert honesty.distance.synced is False
    reasons = skipped_situation_reasons(ss[LIVE_FEED_LAST_AUDIT])
    assert reasons["distance"] == "out_of_range"
    warn = unsynced_board_warning(
        origin="feed", situation_source="scoreboard", skipped=reasons
    )
    assert warn is not None and "Distance" in warn


def test_local_time_labels_include_timezone() -> None:
    stamp = format_local_epoch_labeled(1_700_000_000.0)
    hhmm = format_synced_hhmm(1_700_000_000.0)
    assert stamp.endswith("UTC")
    assert hhmm.endswith("UTC")
    assert ":" in hhmm
    assert "-" in stamp


def test_local_time_uses_named_zone_not_server_local() -> None:
    stamp = format_local_epoch_labeled(1_700_000_000.0, timezone_name="America/New_York")
    hhmm = format_synced_hhmm(1_700_000_000.0, timezone_name="America/New_York")
    assert not stamp.endswith("UTC")
    assert "2023-" in stamp
    assert ":" in hhmm


def test_streamlit_context_exposes_timezone() -> None:
    import streamlit as st

    assert hasattr(st, "context")
    assert hasattr(st.context, "timezone")


def test_defense_look_chip_is_preset_or_manual_never_espn() -> None:
    assert defense_look_chip_label(None) == SOURCE_CHIP_PRESET
    assert defense_look_chip_label("preset") == SOURCE_CHIP_PRESET
    assert defense_look_chip_label("manual") == SOURCE_CHIP_MANUAL
    assert defense_look_chip_label("feed") == SOURCE_CHIP_PRESET


def test_leftover_feed_drive_caption() -> None:
    assert leftover_feed_drive_caption({"skipped": ["previous feed drive still open in DriveLogger"]})
    assert "End drive" in leftover_feed_drive_caption(
        {"skipped": ["previous feed drive still open in DriveLogger"]}
    )
    assert leftover_feed_drive_caption({"skipped": []}) is None

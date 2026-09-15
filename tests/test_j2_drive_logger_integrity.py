"""J2 — DriveLogger integrity: leftover hold, coached-only live log, partial import, End drive."""

from __future__ import annotations

import json
from pathlib import Path

from playcaller.domain import ActualPlayResult
from playcaller.drive_audit_report import compute_drive_audit
from playcaller.game import DriveFeedAuditSnapshot, Game, complete_drive_from_plays
from playcaller.live_data.drive_boundaries import (
    PARTIAL_COMPLETED_DRIVE_SKIP_PREFIX,
    PREVIOUS_FEED_DRIVE_OPEN,
    drive_log_holds_previous_feed_drive,
)
from playcaller.live_data.espn_completed_drives import extract_completed_drives_from_espn_payload
from playcaller.live_data.espn_football import parse_espn_summary
from playcaller.live_data.espn_import_merge import merge_completed_espn_drives_into_game
from playcaller.live_data.sync import SyncOptions, apply_snapshot
from playcaller.possession import (
    END_DRIVE_MIXED_FEED_TEAMS_REASON,
    possessing_team_from_feed_plays,
)
from playcaller.reconciliation.drive_reconciler import (
    espn_outcome_bucket,
    inferred_outcome_bucket,
)
from playcaller.state import DriveLogger
from playcaller.streamlit_state.keys import (
    LIVE_FEED_MERGED_ESPN_DRIVE_KEYS,
    LIVE_FEED_SEEN_PLAY_IDS,
    LIVE_FEED_TEAM_SCOPE,
)
from playcaller.ui.situation_honesty import build_situation_honesty, honest_summary_line

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LIVE_SUMMARY = FIXTURES / "espn_summary_live_401872657.json"
LIVE_SCOREBOARD = FIXTURES / "espn_scoreboard_live_401872657.json"
MNF_SUMMARY = FIXTURES / "espn_summary_mnf_401872931.json"
LAR, SF = "14", "25"
DEN_ID = "7"
EVENT_LIVE = "401872657"
EVENT_MNF = "401872931"


def _live_summary() -> dict:
    return json.loads(LIVE_SUMMARY.read_text(encoding="utf-8"))


def _live_scoreboard() -> dict:
    return json.loads(LIVE_SCOREBOARD.read_text(encoding="utf-8"))


def _snap(summary: dict | None = None, scoreboard: dict | None = None, *, our_team_id: str = LAR):
    return parse_espn_summary(
        summary if summary is not None else _live_summary(),
        sport="nfl",
        our_team_id=our_team_id,
        scoreboard_payload=scoreboard if scoreboard is not None else _live_scoreboard(),
    )


def test_j2_shadow_mismatch_count_is_four() -> None:
    """J2.0 baseline: MNF 401872931 still surfaces exactly four ESPN≠model shadow mismatches."""
    from playcaller.drive_audit_report import _buckets_align
    from playcaller.game import OUTCOME_SOURCE_ESPN

    payload = json.loads(MNF_SUMMARY.read_text(encoding="utf-8"))
    feeds = extract_completed_drives_from_espn_payload(payload, event_id=EVENT_MNF)
    game = Game.new_game()
    n, _, _ = merge_completed_espn_drives_into_game(game, {}, feeds, coached_team_id=DEN_ID)
    assert n == 24
    mismatches = 0
    for dr in game.drives:
        assert dr.outcome_source == OUTCOME_SOURCE_ESPN
        espn_b = espn_outcome_bucket(dr.feed_audit)
        inf_b = inferred_outcome_bucket(dr)
        if espn_b and inf_b and not _buckets_align(espn_b, inf_b):
            mismatches += 1
    assert mismatches == 4


def test_scope_both_opponent_current_does_not_widen_logger() -> None:
    """Scope both + opponent current drive: coached logger unchanged; hold or coached-only skip."""
    session: dict = {LIVE_FEED_SEEN_PLAY_IDS: [], LIVE_FEED_TEAM_SCOPE: "both"}
    game = Game.new_game()
    dl = DriveLogger()
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=_snap(), options=SyncOptions())
    coached_ids = [p.external_play_id for p in dl.results]
    assert coached_ids
    rows = len(dl.results)

    sm = _live_summary()
    sb = _live_scoreboard()
    sb["events"][1]["competitions"][0]["situation"]["possession"] = SF
    sb["events"][1]["competitions"][0]["situation"]["possessionText"] = "SF 25"
    # New opponent drive id → leftover hold preferred when logger still holds coached plays.
    sm["drives"]["current"]["id"] = "401872657-opp"
    sm["drives"]["current"]["team"] = {"id": SF}
    for i, play in enumerate(sm["drives"]["current"]["plays"]):
        play["id"] = f"opp{i}"
        play["end"]["team"] = {"id": SF}

    res = apply_snapshot(
        game=game,
        session=session,
        drive_log=dl,
        snapshot=_snap(sm, sb),
        options=SyncOptions(),
    )
    assert [p.external_play_id for p in dl.results] == coached_ids
    assert len(dl.results) == rows
    assert res.current_drive_plays_merged == 0
    assert not any(str(p.external_play_id or "").startswith("opp") for p in dl.results)
    skipped = [str(s) for s in res.skipped_reasons]
    assert PREVIOUS_FEED_DRIVE_OPEN in skipped or any("coached-team only" in s for s in skipped)


def test_manual_only_logger_holds_on_feed_drive_id_change() -> None:
    dl = DriveLogger()
    dl.log(
        ActualPlayResult(
            family="inside_zone",
            concept_name="Manual",
            play_type="run",
            result_type="run",
            yards_gained=3,
            description="manual-only",
        )
    )
    assert drive_log_holds_previous_feed_drive(
        dl,
        [{"id": "new1"}],
        current_feed_drive_id="drive-b",
        last_feed_drive_id="drive-a",
    )
    # kwargs optional — empty current still uses play-id fallback (manual has no ESPN ids → False)
    assert drive_log_holds_previous_feed_drive(dl, []) is False

    session: dict = {LIVE_FEED_SEEN_PLAY_IDS: [], LIVE_FEED_TEAM_SCOPE: "our"}
    game = Game.new_game()
    apply_snapshot(game=game, session=session, drive_log=dl, snapshot=_snap(), options=SyncOptions())
    # After first sync last drive id is set; second sync with new id must hold.
    sm = _live_summary()
    sm["drives"]["current"]["id"] = "40187265799"
    sm["drives"]["current"]["plays"] = []
    # Fresh manual-only logger (no ESPN ids) after clearing feed rows:
    dl2 = DriveLogger()
    dl2.log(
        ActualPlayResult(
            family="inside_zone",
            concept_name="Manual",
            play_type="run",
            result_type="run",
            yards_gained=3,
            description="manual-only",
        )
    )
    session2: dict = {
        LIVE_FEED_SEEN_PLAY_IDS: [],
        LIVE_FEED_TEAM_SCOPE: "our",
        "live_feed_last_current_drive_id": "4018726573",
    }
    res = apply_snapshot(
        game=Game.new_game(),
        session=session2,
        drive_log=dl2,
        snapshot=_snap(sm),
        options=SyncOptions(),
    )
    assert PREVIOUS_FEED_DRIVE_OPEN in res.skipped_reasons
    assert any(p.description == "manual-only" for p in dl2.results)


def test_partial_completed_drive_skipped_then_imports_after_logger_clear() -> None:
    payload = _live_summary()
    feeds = extract_completed_drives_from_espn_payload(payload, event_id=EVENT_LIVE)
    fd = feeds[0]
    ids = [p.external_play_id for p in fd.plays if p.external_play_id]
    assert len(ids) >= 2
    occupied = {ids[0]}
    game = Game.new_game()
    ss: dict = {}
    n, batch, warns = merge_completed_espn_drives_into_game(
        game, ss, [fd], coached_team_id=LAR, occupied_play_ids=occupied
    )
    assert n == 0
    assert batch == ()
    assert len(warns) == 1
    assert PARTIAL_COMPLETED_DRIVE_SKIP_PREFIX in warns[0]
    assert f"id={fd.stable_key}" in warns[0]
    assert f"missing_plays={len(ids) - 1}" in warns[0]
    assert fd.stable_key not in (ss.get(LIVE_FEED_MERGED_ESPN_DRIVE_KEYS) or [])
    assert game.drives == []

    # End drive: archive logger fragment + clear → occupied empty so feed imports whole.
    n2, batch2, warns2 = merge_completed_espn_drives_into_game(
        game, ss, [fd], coached_team_id=LAR, occupied_play_ids=set()
    )
    assert n2 == 1
    assert warns2 == ()
    assert len(game.drives) == 1
    assert len(game.drives[0].plays or []) == len(fd.plays)
    assert fd.stable_key in ss[LIVE_FEED_MERGED_ESPN_DRIVE_KEYS]


def test_end_drive_possessing_team_from_feed_plays() -> None:
    plays_absent = [
        ActualPlayResult(
            family="inside_zone", play_type="run", result_type="run", yards_gained=4, description="m"
        )
    ]
    side, refuse = possessing_team_from_feed_plays(
        plays_absent, coached_team_id=LAR, fallback_possession="defense"
    )
    assert refuse is None
    assert side == "defense"

    plays_mixed = [
        ActualPlayResult(
            family="inside_zone",
            play_type="run",
            result_type="run",
            yards_gained=1,
            description="a",
            feed_possession_team_id=LAR,
        ),
        ActualPlayResult(
            family="inside_zone",
            play_type="run",
            result_type="run",
            yards_gained=2,
            description="b",
            feed_possession_team_id=SF,
        ),
    ]
    side2, refuse2 = possessing_team_from_feed_plays(
        plays_mixed, coached_team_id=LAR, fallback_possession="offense"
    )
    assert side2 is None
    assert refuse2 == END_DRIVE_MIXED_FEED_TEAMS_REASON

    plays_our = [
        ActualPlayResult(
            family="inside_zone",
            play_type="run",
            result_type="run",
            yards_gained=5,
            description="c",
            feed_possession_team_id=LAR,
        )
    ]
    side3, refuse3 = possessing_team_from_feed_plays(
        plays_our, coached_team_id=LAR, fallback_possession="defense"
    )
    assert refuse3 is None
    assert side3 == "offense"

    # Kickoff start.team is the kicker — must not refuse a coached drive that opens with a return.
    plays_ko = [
        ActualPlayResult(
            play_type="special",
            result_type="kickoff",
            yards_gained=25,
            description="ko",
            feed_possession_team_id=SF,
        ),
        ActualPlayResult(
            family="inside_zone",
            play_type="run",
            result_type="run",
            yards_gained=9,
            description="run",
            feed_possession_team_id=LAR,
        ),
    ]
    side4, refuse4 = possessing_team_from_feed_plays(
        plays_ko, coached_team_id=LAR, fallback_possession="defense"
    )
    assert refuse4 is None
    assert side4 == "offense"


def test_honest_summary_line_never_contains_none_string() -> None:
    honesty = build_situation_honesty(
        origin="feed",
        situation_source="scoreboard",
        skipped={"clock": "absent_in_source", "quarter": "absent_in_source"},
        possession="offense",
        down=2,
        distance=1,
        territory="own",
        yardline=34,
        own_timeouts=3,
        opp_timeouts=3,
        period=1,
        seconds_in_quarter=500,
    )
    line = honest_summary_line(our_score=7, their_score=3, honesty=honesty)
    assert "None" not in line
    honesty2 = build_situation_honesty(
        origin="feed",
        situation_source="scoreboard",
        skipped={},
        possession="offense",
        down=1,
        distance=10,
        territory="own",
        yardline=25,
        own_timeouts=3,
        opp_timeouts=3,
        period=2,
        seconds_in_quarter=60,
    )
    line2 = honest_summary_line(our_score=0, their_score=0, honesty=honesty2)
    assert "None" not in line2
    assert "2nd" in line2 or "Q2" in line2 or "2" in line2


def test_audit_flags_info_for_small_yards_delta_and_warn_above_two() -> None:
    def _flags(computed: int, espn: int) -> str:
        d = complete_drive_from_plays(
            [ActualPlayResult(yards_gained=computed, family="inside_zone", play_type="run")],
            feed_audit=DriveFeedAuditSnapshot(feed_yards=espn, feed_offensive_plays=1),
            possessing_team="offense",
        )
        g = Game.new_game()
        g.drives = [d]
        return " ".join(compute_drive_audit(g).rows[0].flags)

    blob1 = _flags(11, 10)
    assert "ℹ️ Computed yards=11 vs ESPN yards=10" in blob1
    blob2 = _flags(12, 10)
    assert "ℹ️ Computed yards=12 vs ESPN yards=10" in blob2
    blob3 = _flags(13, 10)
    assert "⚠️ Computed yards=13 vs ESPN yards=10" in blob3

    # J17 table rule: MNF fixture still fails the soft table only when |Δ|>2.
    payload = json.loads(MNF_SUMMARY.read_text(encoding="utf-8"))
    feeds = extract_completed_drives_from_espn_payload(payload, event_id=EVENT_MNF)
    game = Game.new_game()
    merge_completed_espn_drives_into_game(game, {}, feeds, coached_team_id=DEN_ID)
    flagged = []
    for i, dr in enumerate(game.drives, 1):
        espn = int(dr.feed_audit.feed_yards) if dr.feed_audit and dr.feed_audit.feed_yards is not None else None
        assert espn is not None and dr.computed_yards is not None
        delta = int(dr.computed_yards) - espn
        if abs(delta) > 2:
            flagged.append((i, espn, dr.computed_yards, delta))
    assert flagged == [], f"drives with |delta|>2: {flagged}"

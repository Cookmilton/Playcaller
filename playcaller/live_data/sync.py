from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, MutableMapping, Set, Tuple

from playcaller.streamlit_state.keys import (
    GAME_DISTANCE,
    GAME_DOWN,
    GAME_OPP_TOS,
    GAME_OWN_TOS,
    GAME_PERIOD,
    GAME_POSSESSION_SIDE,
    GAME_QUARTER_CLOCK_MINS,
    GAME_QUARTER_CLOCK_SECS,
    GAME_SCORE_OURS,
    GAME_SCORE_THEIRS,
    GAME_TERRITORY,
    GAME_YARDLINE,
    LIVE_FEED_COACHED_TEAM_ESPN_ID,
    LIVE_FEED_LAST_AUDIT,
    LIVE_FEED_LAST_ORIGIN,
    LIVE_FEED_LAST_POSSESSION_TEAM_ID,
    LIVE_FEED_LAST_SYNC_EPOCH,
    LIVE_FEED_MANUAL_NOTE,
    LIVE_FEED_TEAM_SCOPE,
)
from playcaller.streamlit_state.widget_backend_bridge import request_widget_hydrate_from_backend

from ..domain import ActualPlayResult
from ..evaluation.snap_review_lifecycle import (
    close_snap_review_row_with_logged_actual,
    trim_snap_review_opens_for_play_count,
)
from ..game import Game
from ..game_situation_input import clamp_quarter_clock_seconds, context_quarter_from_period
from ..situation import territory_yardline_from_abs_yards
from ..state import DriveLogger
from .espn_current_drive_merge import (
    merge_current_espn_plays_into_drive_log,
    maybe_reset_drive_log_after_completed_import,
    persist_seen_play_ids,
    prepare_seen_play_ids_for_feed,
)
from .espn_import_merge import merge_completed_espn_drives_into_game
from .feed_team_scope import current_feed_plays_merge_allowed, normalize_feed_team_scope
from .types import FeedCompletedDrive, FeedPlayEvent, NormalizedGameSnapshot, SyncResult


def _family_from_feed_event(ev: FeedPlayEvent) -> str:
    if ev.type_hint == "rush":
        return "inside_zone"
    if ev.type_hint == "pass":
        return "dropback_pass"
    return "dropback_pass"


@dataclass
class SyncOptions:
    """Hybrid mode: locks skip applying feed fields so manual entry wins."""

    lock_situation: bool = False
    lock_score: bool = False
    auto_append_feed_plays: bool = False
    only_append_when_our_possession: bool = True
    reset_seen_play_ids_on_possession_change: bool = True
    import_completed_feed_drives: bool = True
    # Full ``drives.current`` plays → ``DriveLogger`` (normalized); supersedes coarse auto-append for ESPN.
    import_current_feed_drive_plays: bool = True


def apply_snapshot(
    *,
    game: Game,
    session: MutableMapping[str, Any],
    drive_log: DriveLogger,
    snapshot: NormalizedGameSnapshot,
    options: SyncOptions,
) -> SyncResult:
    """
    Merge ``snapshot`` into ``game``, Streamlit widget keys on ``session``, and optionally ``drive_log``.

    Mutates ``session`` ``game_*`` backend keys (mirrored to ``ui_*`` on the next run before widgets),
    ``game`` fields, ``live_feed_*`` audit keys, and ``live_feed_seen_play_ids``.
    """
    applied: List[str] = []
    skipped: List[str] = []

    if snapshot.quarter is not None:
        q = max(1, min(5, int(snapshot.quarter)))
        session[GAME_PERIOD] = q
        game.quarter = context_quarter_from_period(q)
        applied.append("quarter")

    if snapshot.clock_seconds_in_period is not None:
        period = int(session.get(GAME_PERIOD, session.get("ui_game_period", 1)))
        sec = clamp_quarter_clock_seconds(period, int(snapshot.clock_seconds_in_period))
        session[GAME_QUARTER_CLOCK_MINS] = sec // 60
        session[GAME_QUARTER_CLOCK_SECS] = sec % 60
        game.clock_seconds_remaining = sec
        applied.append("clock")

    if not options.lock_score:
        if snapshot.our_score is not None:
            game.offense_points = int(snapshot.our_score)
            session[GAME_SCORE_OURS] = int(snapshot.our_score)
            applied.append("our_score→game.offense_points")
        if snapshot.opponent_score is not None:
            game.defense_points = int(snapshot.opponent_score)
            session[GAME_SCORE_THEIRS] = int(snapshot.opponent_score)
            applied.append("opponent_score→game.defense_points")
        if snapshot.our_timeouts is not None:
            session[GAME_OWN_TOS] = max(0, min(3, int(snapshot.our_timeouts)))
            applied.append("own_timeouts")
        if snapshot.opponent_timeouts is not None:
            session[GAME_OPP_TOS] = max(0, min(3, int(snapshot.opponent_timeouts)))
            applied.append("opp_timeouts")
    else:
        skipped.append("score/timeouts locked")

    if snapshot.possession_is_our_team is not None:
        session[GAME_POSSESSION_SIDE] = "Our team" if snapshot.possession_is_our_team else "Opponent"
        game.possession = "offense" if snapshot.possession_is_our_team else "defense"
        applied.append("possession")

    if not options.lock_situation:
        if snapshot.down is not None:
            session[GAME_DOWN] = max(1, min(4, int(snapshot.down)))
            applied.append("down")
        if snapshot.distance is not None:
            session[GAME_DISTANCE] = max(1, min(25, int(snapshot.distance)))
            applied.append("distance")
        if snapshot.abs_yards_from_own_goal is not None:
            terr, yl = territory_yardline_from_abs_yards(int(snapshot.abs_yards_from_own_goal))
            session[GAME_TERRITORY] = terr
            session[GAME_YARDLINE] = int(yl)
            applied.append("field_position")
    else:
        skipped.append("situation locked")

    feed_scope = normalize_feed_team_scope(str(session.get(LIVE_FEED_TEAM_SCOPE) or ""))

    drives_imported = 0
    imported_batch: Tuple[FeedCompletedDrive, ...] = ()
    if (
        snapshot.provider == "espn"
        and options.import_completed_feed_drives
        and snapshot.completed_feed_drives
        and snapshot.coached_team_id
    ):
        drives_imported, imported_batch = merge_completed_espn_drives_into_game(
            game,
            session,
            snapshot.completed_feed_drives,
            coached_team_id=str(snapshot.coached_team_id),
            feed_team_scope=feed_scope,
        )
        if drives_imported:
            applied.append(f"imported_completed_drives:{drives_imported}")

    if maybe_reset_drive_log_after_completed_import(drive_log, imported_batch, session):
        applied.append("drive_log_reset:completed_feed_match")

    last_p = session.get(LIVE_FEED_LAST_POSSESSION_TEAM_ID)
    seen: Set[str] = prepare_seen_play_ids_for_feed(
        session,
        possession_team_id=snapshot.possession_team_id,
        last_possession_team_id=last_p,
        reset_on_possession_change=options.reset_seen_play_ids_on_possession_change,
    )

    current_drive_merged = 0
    current_merge_debug: List[str] = []
    if (
        snapshot.provider == "espn"
        and options.import_current_feed_drive_plays
        and not options.lock_situation
        and snapshot.coached_team_id
        and snapshot.current_feed_drive_plays
    ):
        allow_cur, scope_msg = current_feed_plays_merge_allowed(
            scope=feed_scope,
            coached_team_id=str(snapshot.coached_team_id),
            current_drive_team_espn_id=snapshot.current_feed_drive_team_espn_id,
            possession_team_id=snapshot.possession_team_id,
        )
        if not allow_cur:
            if scope_msg:
                skipped.append(scope_msg)
        if allow_cur:
            current_drive_merged = merge_current_espn_plays_into_drive_log(
                drive_log=drive_log,
                seen_play_ids=seen,
                raw_plays=snapshot.current_feed_drive_plays,
                debug=current_merge_debug,
                snap_review_audit=game.recommendation_audit,
            )
            if current_drive_merged:
                applied.append(f"current_drive_plays_merged:{current_drive_merged}")

    plays_appended = 0
    if (
        options.auto_append_feed_plays
        and snapshot.new_plays
        and not options.import_current_feed_drive_plays
    ):
        allow = True
        if options.only_append_when_our_possession and snapshot.possession_is_our_team is False:
            allow = False
            skipped.append("feed plays skipped (opponent possession)")
        if allow:
            for ev in snapshot.new_plays:
                eid = str(ev.event_id)
                if eid in seen:
                    continue
                fam = _family_from_feed_event(ev)
                pt = "run" if fam in ("inside_zone", "outside_zone", "power", "draw") else "pass"
                actual = ActualPlayResult(
                    family=fam,
                    concept_name="Feed",
                    play_type=pt,
                    result_type="feed",
                    yards_gained=int(ev.yards_gained or 0),
                    description=f"[Feed] {ev.summary_text[:220]}",
                )
                drive_log.log(actual)
                close_snap_review_row_with_logged_actual(
                    game.recommendation_audit,
                    plays_after_log=len(drive_log.results),
                    actual=actual,
                )
                seen.add(eid)
                plays_appended += 1
    elif snapshot.new_plays and not options.import_current_feed_drive_plays:
        skipped.append("feed plays not auto-appended (toggle off)")

    persist_seen_play_ids(session, seen)

    if snapshot.completed_feed_drives and not options.import_completed_feed_drives:
        skipped.append("completed feed drives not imported (toggle off)")

    if snapshot.possession_team_id:
        session[LIVE_FEED_LAST_POSSESSION_TEAM_ID] = str(snapshot.possession_team_id)

    coached_audit = str(snapshot.coached_team_id).strip() if snapshot.coached_team_id else ""
    if coached_audit:
        session[LIVE_FEED_COACHED_TEAM_ESPN_ID] = coached_audit

    audit = {
        "provider": snapshot.provider,
        "game_id": snapshot.external_game_id,
        "status": snapshot.status_detail,
        "coached_team_id": coached_audit,
        "feed_team_scope": feed_scope,
        "current_feed_drive_team_espn_id": snapshot.current_feed_drive_team_espn_id,
        "sync_options": {
            "import_current_feed_drive_plays": options.import_current_feed_drive_plays,
            "import_completed_feed_drives": options.import_completed_feed_drives,
            "auto_append_feed_plays": options.auto_append_feed_plays,
            "lock_situation": options.lock_situation,
            "lock_score": options.lock_score,
        },
        "applied": applied,
        "skipped": skipped,
        "plays_appended": plays_appended,
        "drives_imported": drives_imported,
        "current_drive_plays_merged": current_drive_merged,
        "current_drive_merge_debug": list(current_merge_debug),
        "debug_notes": list(snapshot.debug_notes),
    }
    session[LIVE_FEED_LAST_AUDIT] = audit
    session[LIVE_FEED_LAST_SYNC_EPOCH] = snapshot.fetched_at_epoch
    session[LIVE_FEED_LAST_ORIGIN] = "feed"

    trim_snap_review_opens_for_play_count(
        game.recommendation_audit, plays_on_drive=len(drive_log.results)
    )

    if applied:
        request_widget_hydrate_from_backend(session)

    msg = f"Synced {snapshot.provider} ({snapshot.status_detail})" if applied else "Sync: no fields updated"
    return SyncResult(
        ok=True,
        applied_fields=applied,
        skipped_reasons=skipped,
        plays_appended=plays_appended,
        drives_imported=drives_imported,
        current_drive_plays_merged=current_drive_merged,
        message=msg,
    )


def session_mark_manual(session: MutableMapping[str, Any], *, note: str = "") -> None:
    """Call when the operator changes situation manually so the UI can show origin."""
    session[LIVE_FEED_LAST_ORIGIN] = "manual"
    if note:
        session[LIVE_FEED_MANUAL_NOTE] = note

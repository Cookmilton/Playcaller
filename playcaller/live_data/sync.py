from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, List, MutableMapping, Set, Tuple

logger = logging.getLogger(__name__)

# Retain last displayClock/numeric reading only within this wall-clock gap (seconds) and same period.
_TRUSTED_CLOCK_MAX_AGE_SEC = 45.0

# Situation fields reported individually in ``skipped`` when they do not reach the board.
SITUATION_FIELDS: Tuple[str, ...] = (
    "down",
    "distance",
    "field_position",
    "possession",
    "own_timeouts",
    "opp_timeouts",
)

# Reasons attached to a skipped situation field.
SKIP_LOCKED = "locked"
SKIP_NO_SITUATION_SOURCE = "no_situation_source"
SKIP_ABSENT_IN_SOURCE = "absent_in_source"
SKIP_OUT_OF_RANGE = "out_of_range"

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
    LIVE_FEED_LAST_CURRENT_DRIVE_ID,
    LIVE_FEED_LAST_POSSESSION_TEAM_ID,
    LIVE_FEED_LAST_SYNC_EPOCH,
    LIVE_FEED_MANUAL_NOTE,
    LIVE_FEED_TEAM_SCOPE,
    LIVE_FEED_TRUSTED_CLOCK,
)
from playcaller.streamlit_state.widget_backend_bridge import (
    GAME_DISTANCE_MAX,
    GAME_DISTANCE_MIN,
    GAME_DOWN_ALLOWED_VALUES,
    GAME_TIMEOUTS_ALLOWED_VALUES,
    distance_in_widget_domain,
    request_widget_hydrate_from_backend,
)

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


def _skip_field(skipped: List[Any], field: str, reason: str) -> None:
    """Record one situation field that did not reach the board, with why."""
    skipped.append({"field": field, "reason": reason})


def _family_from_feed_event(ev: FeedPlayEvent) -> str:
    if ev.type_hint == "rush":
        return "inside_zone"
    if ev.type_hint == "pass":
        return "dropback_pass"
    if ev.type_hint == "kickoff":
        return "special_teams"
    return "dropback_pass"


@dataclass
class SyncOptions:
    """Hybrid mode: locks skip applying feed fields so manual entry wins."""

    lock_situation: bool = False
    lock_score: bool = False
    auto_append_feed_plays: bool = False
    only_append_when_our_possession: bool = True
    # Name is historical; the reset keys on ``drives.current.id``, not board possession.
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
    # Strings for whole-section skips; ``{"field", "reason"}`` dicts for situation fields.
    skipped: List[Any] = []
    debug_notes_extra: List[str] = []
    drive_log_rows_before = len(drive_log.results)

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
        if snapshot.clock_resolution in ("display_clock", "numeric_status"):
            session[LIVE_FEED_TRUSTED_CLOCK] = {
                "period": period,
                "seconds": sec,
                "epoch": float(snapshot.fetched_at_epoch),
                "source": snapshot.clock_resolution,
            }
    elif not options.lock_situation and any("clock: unknown" in str(x) for x in (snapshot.debug_notes or ())):
        trusted = session.get(LIVE_FEED_TRUSTED_CLOCK)
        period_now = int(snapshot.quarter) if snapshot.quarter is not None else int(session.get(GAME_PERIOD, 1))
        used_trusted = False
        if isinstance(trusted, dict):
            try:
                t_period = int(trusted.get("period", -1))
                t_sec = int(trusted.get("seconds", -1))
                t_epoch = float(trusted.get("epoch", 0))
                t_src = str(trusted.get("source") or "")
            except (TypeError, ValueError):
                t_period, t_sec, t_epoch, t_src = -1, -1, 0.0, ""
            if (
                t_src in ("display_clock", "numeric_status")
                and t_period == period_now
                and t_sec >= 0
                and (float(snapshot.fetched_at_epoch) - t_epoch) <= _TRUSTED_CLOCK_MAX_AGE_SEC
            ):
                sec2 = clamp_quarter_clock_seconds(period_now, t_sec)
                session[GAME_QUARTER_CLOCK_MINS] = sec2 // 60
                session[GAME_QUARTER_CLOCK_SECS] = sec2 % 60
                game.clock_seconds_remaining = sec2
                applied.append("clock_retained_trusted")
                used_trusted = True
                debug_notes_extra.append(
                    "clock: retained from prior trusted ESPN displayClock/numeric reading "
                    f"(≤{_TRUSTED_CLOCK_MAX_AGE_SEC:.0f}s gap, same period) — confirm vs broadcast."
                )
                logger.info(
                    "Live feed sync: applied trusted clock fallback (%ss left in period, period %s).",
                    sec2,
                    period_now,
                )
        if not used_trusted:
            logger.warning(
                "Live feed sync: clock not updated (unknown in ESPN payload); UI quarter clock may stay at prior values."
            )

    has_situation = snapshot.situation_source is not None

    if not options.lock_score:
        if snapshot.our_score is not None:
            game.offense_points = int(snapshot.our_score)
            session[GAME_SCORE_OURS] = int(snapshot.our_score)
            applied.append("our_score→game.offense_points")
        if snapshot.opponent_score is not None:
            game.defense_points = int(snapshot.opponent_score)
            session[GAME_SCORE_THEIRS] = int(snapshot.opponent_score)
            applied.append("opponent_score→game.defense_points")
    else:
        skipped.append("score/timeouts locked")

    # Timeouts ride with the score lock (same operator toggle) but come from the situation block.
    for field, key, raw in (
        ("own_timeouts", GAME_OWN_TOS, snapshot.our_timeouts),
        ("opp_timeouts", GAME_OPP_TOS, snapshot.opponent_timeouts),
    ):
        if options.lock_score:
            _skip_field(skipped, field, SKIP_LOCKED)
        elif not has_situation:
            _skip_field(skipped, field, SKIP_NO_SITUATION_SOURCE)
        elif raw is None:
            _skip_field(skipped, field, SKIP_ABSENT_IN_SOURCE)
        elif int(raw) not in GAME_TIMEOUTS_ALLOWED_VALUES:
            _skip_field(skipped, field, SKIP_OUT_OF_RANGE)
            debug_notes_extra.append(
                f"{field}: ESPN reported {int(raw)}, outside {list(GAME_TIMEOUTS_ALLOWED_VALUES)} — not applied."
            )
        else:
            session[key] = int(raw)
            applied.append(field)

    # Possession is not covered by either lock (it decides which sideline the board shows).
    if not has_situation:
        _skip_field(skipped, "possession", SKIP_NO_SITUATION_SOURCE)
    elif snapshot.possession_is_our_team is None:
        _skip_field(skipped, "possession", SKIP_ABSENT_IN_SOURCE)
    else:
        session[GAME_POSSESSION_SIDE] = "Our team" if snapshot.possession_is_our_team else "Opponent"
        game.possession = "offense" if snapshot.possession_is_our_team else "defense"
        applied.append("possession")

    if options.lock_situation:
        for field in ("down", "distance", "field_position"):
            _skip_field(skipped, field, SKIP_LOCKED)
    elif not has_situation:
        for field in ("down", "distance", "field_position"):
            _skip_field(skipped, field, SKIP_NO_SITUATION_SOURCE)
    else:
        if snapshot.down is None:
            _skip_field(skipped, "down", SKIP_ABSENT_IN_SOURCE)
        elif int(snapshot.down) not in GAME_DOWN_ALLOWED_VALUES:
            _skip_field(skipped, "down", SKIP_OUT_OF_RANGE)
            debug_notes_extra.append(
                f"down: ESPN reported {int(snapshot.down)}, outside {list(GAME_DOWN_ALLOWED_VALUES)} "
                "(0 on kickoffs and PATs) — not applied."
            )
        else:
            session[GAME_DOWN] = int(snapshot.down)
            applied.append("down")

        if snapshot.distance is None:
            _skip_field(skipped, "distance", SKIP_ABSENT_IN_SOURCE)
        elif not distance_in_widget_domain(int(snapshot.distance)):
            _skip_field(skipped, "distance", SKIP_OUT_OF_RANGE)
            debug_notes_extra.append(
                f"distance: ESPN reported {int(snapshot.distance)}, which the `ui_distance` "
                f"number_input cannot hold (domain {GAME_DISTANCE_MIN}–{GAME_DISTANCE_MAX}) — not applied "
                "rather than silently shown as a different number."
            )
        else:
            session[GAME_DISTANCE] = int(snapshot.distance)
            applied.append("distance")

        if snapshot.yards_to_endzone is None:
            _skip_field(skipped, "field_position", SKIP_ABSENT_IN_SOURCE)
        elif snapshot.abs_yards_from_own_goal is None:
            _skip_field(skipped, "field_position", SKIP_OUT_OF_RANGE)
            debug_notes_extra.append(
                f"field_position: ESPN yards-to-endzone {int(snapshot.yards_to_endzone)} is outside "
                "1–99 — not applied."
            )
        else:
            terr, yl = territory_yardline_from_abs_yards(int(snapshot.abs_yards_from_own_goal))
            session[GAME_TERRITORY] = terr
            session[GAME_YARDLINE] = int(yl)
            applied.append("field_position")

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
    completed_drive_plays_imported = sum(len(fd.plays) for fd in imported_batch)

    if maybe_reset_drive_log_after_completed_import(drive_log, imported_batch, session):
        applied.append("drive_log_reset:completed_feed_match")

    last_drive_id = session.get(LIVE_FEED_LAST_CURRENT_DRIVE_ID)
    seen: Set[str] = prepare_seen_play_ids_for_feed(
        session,
        current_feed_drive_id=snapshot.current_feed_drive_id,
        last_feed_drive_id=last_drive_id,
        reset_on_drive_change=options.reset_seen_play_ids_on_possession_change,
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
                if ev.type_hint == "kickoff":
                    fam, pt, rt = "special_teams", "special", "kickoff"
                else:
                    fam = _family_from_feed_event(ev)
                    pt = "run" if fam in ("inside_zone", "outside_zone", "power", "draw") else "pass"
                    rt = "feed"
                actual = ActualPlayResult(
                    family=fam,
                    concept_name="Feed",
                    play_type=pt,
                    result_type=rt,
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
    if snapshot.current_feed_drive_id:
        session[LIVE_FEED_LAST_CURRENT_DRIVE_ID] = str(snapshot.current_feed_drive_id)

    coached_audit = str(snapshot.coached_team_id).strip() if snapshot.coached_team_id else ""
    if coached_audit:
        session[LIVE_FEED_COACHED_TEAM_ESPN_ID] = coached_audit

    audit = {
        "provider": snapshot.provider,
        "game_id": snapshot.external_game_id,
        "status": snapshot.status_detail,
        "coached_team_id": coached_audit,
        "feed_team_scope": feed_scope,
        "current_feed_drive_id": snapshot.current_feed_drive_id,
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
        "completed_drive_plays_imported": completed_drive_plays_imported,
        "current_drive_plays_merged": current_drive_merged,
        "current_drive_merge_debug": list(current_merge_debug),
        # Row accounting: any change here not explained by the counters above came from
        # outside this sync (manual logging, undo) or from a drive-log reset.
        "drive_log_rows_before": drive_log_rows_before,
        "drive_log_rows_after": len(drive_log.results),
        "clock_resolution": snapshot.clock_resolution,
        "situation_source": snapshot.situation_source,
        "debug_notes": list(snapshot.debug_notes) + debug_notes_extra,
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
        completed_drive_plays_imported=completed_drive_plays_imported,
        current_drive_plays_merged=current_drive_merged,
        drive_log_rows_before=drive_log_rows_before,
        drive_log_rows_after=len(drive_log.results),
        situation_source=snapshot.situation_source,
        message=msg,
    )


def session_mark_manual(session: MutableMapping[str, Any], *, note: str = "") -> None:
    """Call when the operator changes situation manually so the UI can show origin."""
    from playcaller.streamlit_state.possession import mark_board_origin_manual

    mark_board_origin_manual(session)
    if note:
        session[LIVE_FEED_MANUAL_NOTE] = note

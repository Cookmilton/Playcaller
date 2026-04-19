"""
ESPN summary :class:`~football_history_warehouse.parsers.espn_summary.models.EspnSummaryParseResult`
→ canonical :class:`~football_history_warehouse.normalization.bundle.CanonicalGameBundle`.

Connector-specific; keep generic orchestration in callers (CLI, ingest worker).
"""

from __future__ import annotations

from datetime import datetime, timezone

from football_history_warehouse.domain import Game, Play, PlayOutcome
from football_history_warehouse.domain.competition import Drive
from football_history_warehouse.domain.enums import DriveResultBucket, GameStatus, PlayResultCategory
from football_history_warehouse.domain.identifiers import DriveId, PlayId
from football_history_warehouse.domain.provenance import ProvenanceEntry, SourceMetadata
from football_history_warehouse.normalization.bundle import CanonicalGameBundle
from football_history_warehouse.normalization.context import GameNormalizationContext
from football_history_warehouse.normalization.exceptions import NormalizationError
from football_history_warehouse.normalization.notices import NormalizationNotice
from football_history_warehouse.parsers.espn_summary.models import EspnSummaryParseResult
from football_history_warehouse.normalization.espn.clock import clock_seconds_remaining_in_period_from_text
from football_history_warehouse.normalization.espn.play_mapping import infer_drive_result_bucket_from_last_play, infer_play_semantics
from football_history_warehouse.normalization.espn.situation import down_distance_from_description


def _game_status(parsed) -> GameStatus:
    b = parsed.broadcast
    if b is None:
        return GameStatus.UNKNOWN
    if b.completed is True:
        return GameStatus.FINAL
    if b.period is not None and b.period >= 1:
        return GameStatus.IN_PROGRESS
    return GameStatus.UNKNOWN


def _resolve_team(ctx: GameNormalizationContext, espn_team_id: str | None):
    if not espn_team_id:
        return None
    return ctx.resolve_team("espn", espn_team_id)


def _defense_for_offense(offense, home, away):
    if offense == home:
        return away
    if offense == away:
        return home
    raise NormalizationError("internal_team_pair", "Offense must match home or away team id.")


def _provenance_for_play(ctx: GameNormalizationContext, source_play_id: str) -> tuple[ProvenanceEntry, ...]:
    if ctx.import_job_id is None or ctx.observed_at is None:
        return ()
    sm = SourceMetadata(
        source_system=ctx.source_system,
        source_record_id=source_play_id,
        source_subresource=str(ctx.game_id),
        ingest_uri=ctx.source_uri,
        content_checksum=ctx.raw_content_checksum,
        observed_at=ctx.observed_at,
        source_payload_version=ctx.parser_version,
    )
    pe = ProvenanceEntry(
        import_job_id=ctx.import_job_id,
        source=sm,
        warehouse_written_at=datetime.now(timezone.utc),
    )
    return (pe,)


def _outcome_from_semantics(sem, description_text: str | None) -> PlayOutcome:
    desc_l = (description_text or "").lower()
    first_down = True if "first down" in desc_l else None
    score = None
    if sem.is_touchdown:
        score = True
    elif sem.result_category in (PlayResultCategory.FIELD_GOAL_GOOD, PlayResultCategory.FIELD_GOAL_NO_GOOD):
        score = sem.result_category == PlayResultCategory.FIELD_GOAL_GOOD
    return PlayOutcome(
        result_category=sem.result_category,
        is_first_down_gained=first_down,
        is_touchdown=sem.is_touchdown,
        is_turnover=sem.is_turnover,
        is_safety=None,
        is_score_on_play=score,
        chain_advanced=None,
        touchback=None,
        fair_catch=None,
        down_after_play=None,
        distance_after_play=None,
        notes=None,
    )


def normalize_espn_summary_parse_result(
    parse_result: EspnSummaryParseResult,
    ctx: GameNormalizationContext,
) -> CanonicalGameBundle:
    """
    Map a parsed ESPN summary into canonical models.

    Raises :class:`NormalizationError` when home/away teams cannot be resolved via
    ``ctx.team_id_by_external_ref``.
    """
    notices: list[NormalizationNotice] = []
    parsed = parse_result.game

    teams_list = list(parsed.teams)
    home_p = next((t for t in teams_list if t.home_away == "home"), None)
    away_p = next((t for t in teams_list if t.home_away == "away"), None)
    if home_p is None or away_p is None:
        raise NormalizationError("teams_home_away", "Parsed game must include home and away ParsedEspnTeam rows.")

    home_tid = _resolve_team(ctx, home_p.espn_team_id)
    away_tid = _resolve_team(ctx, away_p.espn_team_id)
    if home_tid is None or away_tid is None:
        raise NormalizationError(
            "unmapped_team",
            "Provide team_id_by_external_ref entries for espn:<espn_team_id> for both competitors.",
        )

    status = _game_status(parsed)
    game = Game(
        game_id=ctx.game_id,
        season_id=ctx.season_id,
        league_id=ctx.league_id,
        home_team_id=home_tid,
        away_team_id=away_tid,
        status=status,
        scheduled_start_utc=None,
        home_score_final=home_p.score,
        away_score_final=away_p.score,
        regulation_period_count=4,
        overtime_periods_played=None,
        venue_id=None,
        attendance=None,
        neutral_site=None,
        provenance=(),
        source_extensions={
            "espn.event_id": parsed.source_event_id,
            "espn.source_format": parsed.source_format,
            "espn.parser_notices": [n.code for n in parse_result.notices],
        },
    )

    if parsed.broadcast and parsed.broadcast.period is not None:
        notices.append(
            NormalizationNotice(
                code="period_snapshot_only",
                detail="Play periods use header/broadcast quarter only; per-play period may differ.",
                where="plays[].period",
            )
        )

    period_hint = parsed.broadcast.period if parsed.broadcast else None

    drives_out: list[Drive] = []
    plays_out: list[Play] = []
    seq_game = 0

    for drv in parsed.drives:
        off_espn = drv.offense_espn_team_id
        offense_tid = _resolve_team(ctx, off_espn)
        if offense_tid is None:
            notices.append(
                NormalizationNotice(
                    code="drive_skipped_no_offense",
                    detail=f"Drive {drv.source_drive_id!r} has no resolvable offense team id.",
                    where=f"drive:{drv.source_drive_id}",
                )
            )
            continue
        try:
            defense_tid = _defense_for_offense(offense_tid, home_tid, away_tid)
        except NormalizationError:
            notices.append(
                NormalizationNotice(
                    code="drive_skipped_offense_not_in_game",
                    detail=f"Drive {drv.source_drive_id!r} offense does not match home/away.",
                    where=f"drive:{drv.source_drive_id}",
                )
            )
            continue

        drive_id = DriveId(f"{ctx.game_id}:drive:{drv.source_drive_id}")
        net_yards = None
        yards_list = [p.stat_yardage for p in drv.plays if p.stat_yardage is not None]
        if yards_list:
            net_yards = sum(yards_list)

        last = drv.plays[-1] if drv.plays else None
        bucket: DriveResultBucket = (
            infer_drive_result_bucket_from_last_play(last.play_type_text, last.description_text)
            if last
            else DriveResultBucket.UNKNOWN
        )

        drive_row = Drive(
            drive_id=drive_id,
            game_id=ctx.game_id,
            offense_team_id=offense_tid,
            defense_team_id=defense_tid,
            drive_order=drv.drive_order,
            start_period=period_hint,
            end_period=period_hint,
            result_bucket=bucket,
            net_yards=net_yards,
            play_count_official=len(drv.plays),
            time_of_possession_seconds=None,
            start_score_offense=None,
            start_score_defense=None,
            provenance=(),
            source_extensions={"espn.drive_id": drv.source_drive_id},
        )
        drives_out.append(drive_row)

        for pp in drv.plays:
            sem = infer_play_semantics(pp.play_type_text, pp.description_text)
            outcome = _outcome_from_semantics(sem, pp.description_text)
            down, distance = down_distance_from_description(pp.description_text)
            clock = clock_seconds_remaining_in_period_from_text(pp.description_text)

            play = Play(
                play_id=PlayId(f"{ctx.game_id}:play:{pp.source_play_id}"),
                game_id=ctx.game_id,
                drive_id=drive_id,
                sequence_in_game=seq_game,
                sequence_in_drive=pp.sequence_in_drive,
                period=period_hint,
                clock_seconds_remaining_in_period=clock,
                down=down,
                distance=distance,
                yards_to_goal_line=None,
                field_side=None,
                offense_team_id=offense_tid,
                defense_team_id=defense_tid,
                offense_points_before_snap=None,
                defense_points_before_snap=None,
                score_differential_offense_perspective=None,
                play_family=sem.play_family,
                play_type_detail=pp.play_type_text,
                passer_player_id=None,
                qb_player_id=None,
                rusher_player_id=None,
                target_player_id=None,
                primary_ballcarrier_player_id=None,
                outcome=outcome,
                flag_penalty=sem.flag_penalty,
                penalty_accepted=None,
                penalty_yards=None,
                counts_toward_offense_stats=None if not sem.is_no_play_from_penalty else False,
                is_sack=sem.is_sack,
                is_scramble=sem.is_scramble,
                is_no_play_from_penalty=sem.is_no_play_from_penalty,
                is_spike=outcome.result_category == PlayResultCategory.SPIKE,
                is_kneel=outcome.result_category == PlayResultCategory.KNEEL,
                yards_gained=pp.stat_yardage,
                description_text=pp.description_text,
                provenance=_provenance_for_play(ctx, pp.source_play_id),
                source_extensions={
                    "espn.source_play_id": pp.source_play_id,
                    "espn.play_type_id": pp.play_type_id,
                    "espn.play_type_text": pp.play_type_text,
                },
            )
            plays_out.append(play)
            seq_game += 1

    return CanonicalGameBundle(
        game=game,
        drives=tuple(drives_out),
        plays=tuple(plays_out),
        notices=tuple(notices),
    )

"""Map ORM rows to canonical domain models (read path; provenance not loaded)."""

from __future__ import annotations

from football_history_warehouse.domain.competition import Drive, Game, Play, PlayOutcome
from football_history_warehouse.domain.enums import (
    DriveResultBucket,
    FieldSide,
    GameStatus,
    PlayFamily,
    PlayResultCategory,
)
from football_history_warehouse.domain.identifiers import (
    DriveId,
    GameId,
    LeagueId,
    PlayId,
    PlayerId,
    SeasonId,
    TeamId,
    VenueId,
)
from football_history_warehouse.storage.database.models import DriveRow, GameRow, PlayRow


def game_from_row(row: GameRow) -> Game:
    return Game(
        game_id=GameId(row.game_id),
        season_id=SeasonId(row.season_id),
        league_id=LeagueId(row.league_id),
        home_team_id=TeamId(row.home_team_id),
        away_team_id=TeamId(row.away_team_id),
        status=GameStatus(row.status),
        scheduled_start_utc=row.scheduled_start_utc,
        home_score_final=row.home_score_final,
        away_score_final=row.away_score_final,
        regulation_period_count=row.regulation_period_count,
        overtime_periods_played=row.overtime_periods_played,
        venue_id=VenueId(row.venue_id) if row.venue_id else None,
        attendance=row.attendance,
        neutral_site=row.neutral_site,
        provenance=(),
        source_extensions=dict(row.source_extensions or {}),
    )


def drive_from_row(row: DriveRow) -> Drive:
    return Drive(
        drive_id=DriveId(row.drive_id),
        game_id=GameId(row.game_id),
        offense_team_id=TeamId(row.offense_team_id),
        defense_team_id=TeamId(row.defense_team_id),
        drive_order=row.drive_order,
        start_period=row.start_period,
        end_period=row.end_period,
        result_bucket=DriveResultBucket(row.result_bucket) if row.result_bucket else None,
        net_yards=row.net_yards,
        play_count_official=row.play_count_official,
        time_of_possession_seconds=row.time_of_possession_seconds,
        start_score_offense=row.start_score_offense,
        start_score_defense=row.start_score_defense,
        provenance=(),
        source_extensions=dict(row.source_extensions or {}),
    )


def play_from_row(row: PlayRow) -> Play:
    outcome = PlayOutcome(
        result_category=PlayResultCategory(row.result_category),
        is_first_down_gained=row.is_first_down_gained,
        is_touchdown=row.is_touchdown,
        is_turnover=row.is_turnover,
        is_safety=row.is_safety,
        is_score_on_play=row.is_score_on_play,
        chain_advanced=row.chain_advanced,
        touchback=row.touchback,
        fair_catch=row.fair_catch,
        down_after_play=row.down_after_play,
        distance_after_play=row.distance_after_play,
        notes=row.outcome_notes,
    )
    return Play(
        play_id=PlayId(row.play_id),
        game_id=GameId(row.game_id),
        drive_id=DriveId(row.drive_id) if row.drive_id else None,
        sequence_in_game=row.sequence_in_game,
        sequence_in_drive=row.sequence_in_drive,
        period=row.period,
        clock_seconds_remaining_in_period=row.clock_seconds_remaining_in_period,
        down=row.down,
        distance=row.distance,
        yards_to_goal_line=row.yards_to_goal_line,
        field_side=FieldSide(row.field_side) if row.field_side else None,
        offense_team_id=TeamId(row.offense_team_id),
        defense_team_id=TeamId(row.defense_team_id),
        offense_points_before_snap=row.offense_points_before_snap,
        defense_points_before_snap=row.defense_points_before_snap,
        score_differential_offense_perspective=row.score_differential_offense_perspective,
        play_family=PlayFamily(row.play_family),
        play_type_detail=row.play_type_detail,
        passer_player_id=PlayerId(row.passer_player_id) if row.passer_player_id else None,
        qb_player_id=PlayerId(row.qb_player_id) if row.qb_player_id else None,
        rusher_player_id=PlayerId(row.rusher_player_id) if row.rusher_player_id else None,
        target_player_id=PlayerId(row.target_player_id) if row.target_player_id else None,
        primary_ballcarrier_player_id=(
            PlayerId(row.primary_ballcarrier_player_id) if row.primary_ballcarrier_player_id else None
        ),
        outcome=outcome,
        flag_penalty=row.flag_penalty,
        penalty_accepted=row.penalty_accepted,
        penalty_yards=row.penalty_yards,
        counts_toward_offense_stats=row.counts_toward_offense_stats,
        is_sack=row.is_sack,
        is_scramble=row.is_scramble,
        is_no_play_from_penalty=row.is_no_play_from_penalty,
        is_spike=row.is_spike,
        is_kneel=row.is_kneel,
        yards_gained=row.yards_gained,
        description_text=row.description_text,
        provenance=(),
        source_extensions=dict(row.source_extensions or {}),
    )

"""
Minimal repository helpers for unit-of-work inserts (bootstrap for ingest).

Maps canonical IDs and enum string values onto ORM rows in FK-safe order.
Full domain↔row mappers can wrap these later without changing table shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from football_history_warehouse.domain.enums import (
    CompetitionTier,
    GameStatus,
    ImportJobStatus,
    LeagueFamily,
    PlayFamily,
    PlayResultCategory,
)
from football_history_warehouse.storage.database.models import (
    DriveRow,
    GameRow,
    ImportJobRow,
    LeagueRow,
    PlayRow,
    ProvenanceRecordRow,
    SeasonRow,
    TeamRow,
)


def allocate_sqlite_provenance_ids(session: Session, count: int) -> list[int] | None:
    """
    Pre-allocate primary keys for ``provenance_records`` on SQLite.

    Alembic renders BIGINT PK on SQLite without AUTOINCREMENT; inserts must supply
    ``id`` explicitly. On PostgreSQL, return ``None`` and rely on autoincrement.
    """
    if count <= 0:
        return None
    dialect = session.get_bind().dialect.name
    if dialect != "sqlite":
        return None
    m = session.scalar(select(func.coalesce(func.max(ProvenanceRecordRow.id), 0)))
    start = int(m) + 1
    return list(range(start, start + count))


@dataclass(frozen=True, slots=True)
class WarehouseChainIds:
    """Primary keys produced by :func:`insert_minimal_warehouse_chain`."""

    job_id: str
    league_id: str
    season_id: str
    home_team_id: str
    away_team_id: str
    game_id: str
    drive_id: str
    play_id: str


def insert_minimal_warehouse_chain(
    session: Session,
    *,
    job_id: str,
    league_id: str,
    season_id: str,
    home_team_id: str,
    away_team_id: str,
    game_id: str,
    drive_id: str,
    play_id: str,
    source_label: str = "integration_test",
    source_system: str = "test",
    season_year_label: str = "2024",
    league_name: str = "Test League",
    home_full_name: str = "Home Town Hawks",
    away_full_name: str = "Away City Wolves",
    extra_provenance_entities: tuple[tuple[str, str], ...] = (),
) -> WarehouseChainIds:
    """
    Insert one import job → league → season → two teams → game → drive → play,
    plus provenance rows for the play (and optional extra entity pairs).

    Call inside an open transaction (e.g. :func:`~football_history_warehouse.storage.database.session_scope`).
    """
    now = datetime.now(timezone.utc)

    prov_count = 1 + len(extra_provenance_entities)
    prov_ids = allocate_sqlite_provenance_ids(session, prov_count)

    job = ImportJobRow(
        job_id=job_id,
        status=ImportJobStatus.RUNNING.value,
        started_at=now,
        completed_at=None,
        source_label=source_label,
        trigger="test",
        records_attempted=None,
        records_succeeded=None,
        records_failed=None,
        error_summary=None,
        config_snapshot={},
    )
    session.add(job)

    league = LeagueRow(
        league_id=league_id,
        family=LeagueFamily.NFL.value,
        name=league_name,
        short_code="TL",
        competition_tier_default=CompetitionTier.REGULAR.value,
        rules_profile_key=None,
    )
    session.add(league)

    season = SeasonRow(
        season_id=season_id,
        league_id=league_id,
        year_label=season_year_label,
        starts_on=None,
        ends_on=None,
    )
    session.add(season)

    home = TeamRow(
        team_id=home_team_id,
        league_id=league_id,
        full_name=home_full_name,
        abbreviation="HAW",
        nickname=None,
        city=None,
        conference_id=None,
        division_id=None,
    )
    away = TeamRow(
        team_id=away_team_id,
        league_id=league_id,
        full_name=away_full_name,
        abbreviation="WOL",
        nickname=None,
        city=None,
        conference_id=None,
        division_id=None,
    )
    session.add_all([home, away])

    game = GameRow(
        game_id=game_id,
        season_id=season_id,
        league_id=league_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        status=GameStatus.SCHEDULED.value,
        scheduled_start_utc=None,
        home_score_final=None,
        away_score_final=None,
        regulation_period_count=4,
        overtime_periods_played=None,
        venue_id=None,
        attendance=None,
        neutral_site=None,
        source_extensions={},
    )
    session.add(game)

    drive = DriveRow(
        drive_id=drive_id,
        game_id=game_id,
        offense_team_id=home_team_id,
        defense_team_id=away_team_id,
        drive_order=1,
        start_period=1,
        end_period=None,
        result_bucket=None,
        net_yards=None,
        play_count_official=None,
        time_of_possession_seconds=None,
        start_score_offense=None,
        start_score_defense=None,
        source_extensions={},
    )
    session.add(drive)

    play = PlayRow(
        play_id=play_id,
        game_id=game_id,
        season_id=season_id,
        league_id=league_id,
        drive_id=drive_id,
        sequence_in_game=1,
        sequence_in_drive=1,
        period=1,
        clock_seconds_remaining_in_period=900,
        down=1,
        distance=10,
        yards_to_goal_line=75,
        field_side=None,
        offense_team_id=home_team_id,
        defense_team_id=away_team_id,
        offense_points_before_snap=0,
        defense_points_before_snap=0,
        score_differential_offense_perspective=0,
        play_family=PlayFamily.RUN.value,
        play_type_detail=None,
        passer_player_id=None,
        qb_player_id=None,
        rusher_player_id=None,
        target_player_id=None,
        primary_ballcarrier_player_id=None,
        result_category=PlayResultCategory.UNKNOWN.value,
        is_first_down_gained=None,
        is_touchdown=None,
        is_turnover=None,
        is_safety=None,
        is_score_on_play=None,
        chain_advanced=None,
        touchback=None,
        fair_catch=None,
        down_after_play=None,
        distance_after_play=None,
        outcome_notes=None,
        flag_penalty=False,
        penalty_accepted=None,
        penalty_yards=None,
        counts_toward_offense_stats=None,
        is_sack=False,
        is_scramble=False,
        is_no_play_from_penalty=False,
        is_spike=False,
        is_kneel=False,
        yards_gained=4,
        description_text=None,
        source_extensions={},
    )
    session.add(play)

    prov_play_fields = dict(
        entity_type="play",
        entity_id=play_id,
        import_job_id=job_id,
        source_system=source_system,
        source_record_id="feed-play-1",
        source_subresource=None,
        ingest_uri=None,
        content_checksum=None,
        observed_at=now,
        source_payload_version="1",
        warehouse_written_at=now,
        superseded_by_job_id=None,
    )
    if prov_ids is not None:
        prov_play_fields["id"] = prov_ids[0]
    session.add(ProvenanceRecordRow(**prov_play_fields))

    for idx, (entity_type, entity_id) in enumerate(extra_provenance_entities, start=1):
        extra_fields = dict(
            entity_type=entity_type,
            entity_id=entity_id,
            import_job_id=job_id,
            source_system=source_system,
            source_record_id=None,
            source_subresource=None,
            ingest_uri=None,
            content_checksum=None,
            observed_at=now,
            source_payload_version=None,
            warehouse_written_at=now,
            superseded_by_job_id=None,
        )
        if prov_ids is not None:
            extra_fields["id"] = prov_ids[idx]
        session.add(ProvenanceRecordRow(**extra_fields))

    session.flush()

    return WarehouseChainIds(
        job_id=job_id,
        league_id=league_id,
        season_id=season_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        game_id=game_id,
        drive_id=drive_id,
        play_id=play_id,
    )

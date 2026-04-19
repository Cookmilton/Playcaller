"""
Persist :class:`~football_history_warehouse.normalization.bundle.CanonicalGameBundle`
to ORM rows in one session (import job → org → game → drives → plays → provenance).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from football_history_warehouse.domain import Game, Play
from football_history_warehouse.domain.competition import Drive
from football_history_warehouse.domain.enums import CompetitionTier, ImportJobStatus, LeagueFamily
from football_history_warehouse.domain.provenance import ProvenanceEntry
from football_history_warehouse.normalization.bundle import CanonicalGameBundle
from football_history_warehouse.validation.issues import (
    CanonicalBundleValidationResult,
    ValidationFailedError,
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
from football_history_warehouse.storage.repositories.transactional import allocate_sqlite_provenance_ids


@dataclass(frozen=True, slots=True)
class PersistCanonicalBundleParams:
    """
    Controls optional row creation for FK targets not already present.

    When ``ensure_*`` is true, missing rows are inserted with conservative defaults.
    Team display strings default to ``("Team {team_id}", None)`` when omitted.
    """

    import_job_id: str
    ensure_import_job: bool = True
    import_job_source_label: str = "canonical_persist"
    import_job_trigger: str | None = "persist_canonical_game_bundle"

    ensure_league_season_teams: bool = True
    league_family: LeagueFamily = LeagueFamily.NFL
    league_name: str | None = None
    league_short_code: str | None = "LG"
    season_year_label: str | None = None  # default: str(game.season_id)

    team_row_labels: dict[str, tuple[str, str | None]] | None = None
    """Map ``team_id`` -> (full_name, abbreviation) for new ``teams`` rows."""

    validation_result: CanonicalBundleValidationResult | None = None
    """
    When set, persistence is blocked unless :attr:`~CanonicalBundleValidationResult.ok_to_persist`
    is True (raises :class:`~football_history_warehouse.validation.issues.ValidationFailedError`).
    Pass the output of :func:`~football_history_warehouse.validation.validate_canonical_game_bundle`
    to enforce validate-then-persist without silently writing bad graphs.
    """


@dataclass(frozen=True, slots=True)
class PersistedCanonicalBundleIds:
    """Primary keys written by :func:`persist_canonical_game_bundle`."""

    import_job_id: str
    league_id: str
    season_id: str
    home_team_id: str
    away_team_id: str
    game_id: str
    drive_ids: tuple[str, ...]
    play_ids: tuple[str, ...]
    provenance_rows_written: int


def _validate_provenance_job(bundle: CanonicalGameBundle, import_job_id: str) -> None:
    for entry in _iter_provenance_entries(bundle):
        if str(entry.import_job_id) != import_job_id:
            msg = (
                f"Provenance import_job_id {entry.import_job_id!r} does not match "
                f"expected {import_job_id!r}"
            )
            raise ValueError(msg)


def _iter_provenance_entries(bundle: CanonicalGameBundle) -> Iterator[ProvenanceEntry]:
    for p in bundle.game.provenance:
        yield p
    for d in bundle.drives:
        for p in d.provenance:
            yield p
    for pl in bundle.plays:
        for p in pl.provenance:
            yield p


def _count_provenance_entries(bundle: CanonicalGameBundle) -> int:
    n = len(bundle.game.provenance)
    n += sum(len(d.provenance) for d in bundle.drives)
    n += sum(len(p.provenance) for p in bundle.plays)
    return n


def _ensure_import_job(session: Session, job_id: str, *, source_label: str, trigger: str | None) -> None:
    if session.get(ImportJobRow, job_id) is not None:
        return
    now = datetime.now(timezone.utc)
    session.add(
        ImportJobRow(
            job_id=job_id,
            status=ImportJobStatus.RUNNING.value,
            started_at=now,
            completed_at=None,
            source_label=source_label,
            trigger=trigger,
            records_attempted=None,
            records_succeeded=None,
            records_failed=None,
            error_summary=None,
            config_snapshot={},
        )
    )


def _ensure_league(
    session: Session,
    *,
    league_id: str,
    family: LeagueFamily,
    name: str,
    short_code: str | None,
) -> None:
    if session.get(LeagueRow, league_id) is not None:
        return
    session.add(
        LeagueRow(
            league_id=league_id,
            family=family.value,
            name=name,
            short_code=short_code,
            competition_tier_default=CompetitionTier.REGULAR.value,
            rules_profile_key=None,
        )
    )


def _ensure_season(session: Session, *, season_id: str, league_id: str, year_label: str) -> None:
    if session.get(SeasonRow, season_id) is not None:
        return
    session.add(
        SeasonRow(
            season_id=season_id,
            league_id=league_id,
            year_label=year_label,
            starts_on=None,
            ends_on=None,
        )
    )


def _ensure_team(
    session: Session,
    *,
    team_id: str,
    league_id: str,
    full_name: str,
    abbreviation: str | None,
) -> None:
    if session.get(TeamRow, team_id) is not None:
        return
    session.add(
        TeamRow(
            team_id=team_id,
            league_id=league_id,
            full_name=full_name,
            abbreviation=abbreviation,
            nickname=None,
            city=None,
            conference_id=None,
            division_id=None,
        )
    )


def _team_label(team_id: str, labels: dict[str, tuple[str, str | None]] | None) -> tuple[str, str | None]:
    if labels and team_id in labels:
        return labels[team_id]
    return (f"Team {team_id}", None)


def _game_row(g: Game) -> GameRow:
    return GameRow(
        game_id=str(g.game_id),
        season_id=str(g.season_id),
        league_id=str(g.league_id),
        home_team_id=str(g.home_team_id),
        away_team_id=str(g.away_team_id),
        status=g.status.value,
        scheduled_start_utc=g.scheduled_start_utc,
        home_score_final=g.home_score_final,
        away_score_final=g.away_score_final,
        regulation_period_count=g.regulation_period_count,
        overtime_periods_played=g.overtime_periods_played,
        venue_id=str(g.venue_id) if g.venue_id is not None else None,
        attendance=g.attendance,
        neutral_site=g.neutral_site,
        source_extensions=dict(g.source_extensions),
    )


def _drive_row(d: Drive) -> DriveRow:
    return DriveRow(
        drive_id=str(d.drive_id),
        game_id=str(d.game_id),
        offense_team_id=str(d.offense_team_id),
        defense_team_id=str(d.defense_team_id),
        drive_order=d.drive_order,
        start_period=d.start_period,
        end_period=d.end_period,
        result_bucket=d.result_bucket.value if d.result_bucket is not None else None,
        net_yards=d.net_yards,
        play_count_official=d.play_count_official,
        time_of_possession_seconds=d.time_of_possession_seconds,
        start_score_offense=d.start_score_offense,
        start_score_defense=d.start_score_defense,
        source_extensions=dict(d.source_extensions),
    )


def _play_row(p: Play, *, league_id: str, season_id: str) -> PlayRow:
    o = p.outcome
    return PlayRow(
        play_id=str(p.play_id),
        game_id=str(p.game_id),
        season_id=season_id,
        league_id=league_id,
        drive_id=str(p.drive_id) if p.drive_id is not None else None,
        sequence_in_game=p.sequence_in_game,
        sequence_in_drive=p.sequence_in_drive,
        period=p.period,
        clock_seconds_remaining_in_period=p.clock_seconds_remaining_in_period,
        down=p.down,
        distance=p.distance,
        yards_to_goal_line=p.yards_to_goal_line,
        field_side=p.field_side.value if p.field_side is not None else None,
        offense_team_id=str(p.offense_team_id),
        defense_team_id=str(p.defense_team_id),
        offense_points_before_snap=p.offense_points_before_snap,
        defense_points_before_snap=p.defense_points_before_snap,
        score_differential_offense_perspective=p.score_differential_offense_perspective,
        play_family=p.play_family.value,
        play_type_detail=p.play_type_detail,
        passer_player_id=str(p.passer_player_id) if p.passer_player_id is not None else None,
        qb_player_id=str(p.qb_player_id) if p.qb_player_id is not None else None,
        rusher_player_id=str(p.rusher_player_id) if p.rusher_player_id is not None else None,
        target_player_id=str(p.target_player_id) if p.target_player_id is not None else None,
        primary_ballcarrier_player_id=(
            str(p.primary_ballcarrier_player_id) if p.primary_ballcarrier_player_id is not None else None
        ),
        result_category=o.result_category.value,
        is_first_down_gained=o.is_first_down_gained,
        is_touchdown=o.is_touchdown,
        is_turnover=o.is_turnover,
        is_safety=o.is_safety,
        is_score_on_play=o.is_score_on_play,
        chain_advanced=o.chain_advanced,
        touchback=o.touchback,
        fair_catch=o.fair_catch,
        down_after_play=o.down_after_play,
        distance_after_play=o.distance_after_play,
        outcome_notes=o.notes,
        flag_penalty=p.flag_penalty,
        penalty_accepted=p.penalty_accepted,
        penalty_yards=p.penalty_yards,
        counts_toward_offense_stats=p.counts_toward_offense_stats,
        is_sack=p.is_sack,
        is_scramble=p.is_scramble,
        is_no_play_from_penalty=p.is_no_play_from_penalty,
        is_spike=p.is_spike,
        is_kneel=p.is_kneel,
        yards_gained=p.yards_gained,
        description_text=p.description_text,
        source_extensions=dict(p.source_extensions),
    )


def _provenance_row(
    *,
    entity_type: str,
    entity_id: str,
    entry: ProvenanceEntry,
    prov_id: int | None,
) -> ProvenanceRecordRow:
    fields: dict[str, Any] = dict(
        entity_type=entity_type,
        entity_id=entity_id,
        import_job_id=str(entry.import_job_id),
        source_system=entry.source.source_system,
        source_record_id=entry.source.source_record_id,
        source_subresource=entry.source.source_subresource,
        ingest_uri=entry.source.ingest_uri,
        content_checksum=entry.source.content_checksum,
        observed_at=entry.source.observed_at,
        source_payload_version=entry.source.source_payload_version,
        warehouse_written_at=entry.warehouse_written_at,
        superseded_by_job_id=str(entry.superseded_by_job_id) if entry.superseded_by_job_id else None,
    )
    if prov_id is not None:
        fields["id"] = prov_id
    return ProvenanceRecordRow(**fields)


def persist_canonical_game_bundle(
    session: Session,
    bundle: CanonicalGameBundle,
    params: PersistCanonicalBundleParams,
) -> PersistedCanonicalBundleIds:
    """
    Insert ``games`` / ``drives`` / ``plays`` and provenance rows in FK-safe order.

    Call inside an open transaction (e.g. :func:`~football_history_warehouse.storage.database.session_scope`).
    """
    g = bundle.game
    import_job_id = params.import_job_id
    if params.validation_result is not None and not params.validation_result.ok_to_persist:
        raise ValidationFailedError(params.validation_result)
    _validate_provenance_job(bundle, import_job_id)

    league_id = str(g.league_id)
    season_id = str(g.season_id)
    home_id = str(g.home_team_id)
    away_id = str(g.away_team_id)

    if params.ensure_import_job:
        _ensure_import_job(
            session,
            import_job_id,
            source_label=params.import_job_source_label,
            trigger=params.import_job_trigger,
        )

    labels = params.team_row_labels
    season_year = params.season_year_label or season_id
    league_name = params.league_name or f"League {league_id}"

    if params.ensure_league_season_teams:
        _ensure_league(
            session,
            league_id=league_id,
            family=params.league_family,
            name=league_name,
            short_code=params.league_short_code,
        )
        _ensure_season(session, season_id=season_id, league_id=league_id, year_label=season_year)
        hf, ha = _team_label(home_id, labels)
        af, aa = _team_label(away_id, labels)
        _ensure_team(session, team_id=home_id, league_id=league_id, full_name=hf, abbreviation=ha)
        _ensure_team(session, team_id=away_id, league_id=league_id, full_name=af, abbreviation=aa)

    session.add(_game_row(g))
    for d in bundle.drives:
        session.add(_drive_row(d))
    for p in bundle.plays:
        session.add(_play_row(p, league_id=league_id, season_id=season_id))

    n_prov = _count_provenance_entries(bundle)
    prov_ids = allocate_sqlite_provenance_ids(session, n_prov)
    prov_idx = 0

    def _next_id() -> int | None:
        nonlocal prov_idx
        if prov_ids is None:
            return None
        pid = prov_ids[prov_idx]
        prov_idx += 1
        return pid

    for entry in bundle.game.provenance:
        session.add(_provenance_row(entity_type="game", entity_id=str(g.game_id), entry=entry, prov_id=_next_id()))
    for d in bundle.drives:
        for entry in d.provenance:
            session.add(
                _provenance_row(
                    entity_type="drive",
                    entity_id=str(d.drive_id),
                    entry=entry,
                    prov_id=_next_id(),
                )
            )
    for p in bundle.plays:
        for entry in p.provenance:
            session.add(
                _provenance_row(
                    entity_type="play",
                    entity_id=str(p.play_id),
                    entry=entry,
                    prov_id=_next_id(),
                )
            )

    session.flush()

    return PersistedCanonicalBundleIds(
        import_job_id=import_job_id,
        league_id=league_id,
        season_id=season_id,
        home_team_id=home_id,
        away_team_id=away_id,
        game_id=str(g.game_id),
        drive_ids=tuple(str(d.drive_id) for d in bundle.drives),
        play_ids=tuple(str(p.play_id) for p in bundle.plays),
        provenance_rows_written=n_prov,
    )

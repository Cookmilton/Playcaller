"""
Aggregated game inventory for operators (counts, import hints).

Used only through :class:`~football_history_warehouse.consumer.client.FootballWarehouseClient`;
playcalling apps should not import this module directly.
"""

from __future__ import annotations

from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from football_history_warehouse.consumer.dtos import WarehouseGameInventoryItem
from football_history_warehouse.consumer.inventory_filters import GameInventoryFilters
from football_history_warehouse.query.pagination import PageParams
from football_history_warehouse.storage.database.models import (
    DriveRow,
    GameRow,
    LeagueRow,
    PlayRow,
    ProvenanceRecordRow,
    SeasonRow,
    SourceArtifactRow,
    TeamRow,
)


def _latest_game_provenance_subquery():
    """One row per game entity: latest provenance row by ``id`` (monotonic per import)."""
    inner = (
        select(
            ProvenanceRecordRow.entity_id.label("game_id"),
            func.max(ProvenanceRecordRow.id).label("max_id"),
        )
        .where(ProvenanceRecordRow.entity_type == "game")
        .group_by(ProvenanceRecordRow.entity_id)
    ).subquery()
    return (
        select(
            ProvenanceRecordRow.entity_id.label("game_id"),
            ProvenanceRecordRow.import_job_id,
            ProvenanceRecordRow.warehouse_written_at,
            ProvenanceRecordRow.ingest_uri,
        )
        .join(
            inner,
            and_(
                ProvenanceRecordRow.entity_id == inner.c.game_id,
                ProvenanceRecordRow.id == inner.c.max_id,
                ProvenanceRecordRow.entity_type == "game",
            ),
        )
    ).subquery()


def _latest_play_provenance_per_game_subquery():
    """When no ``entity_type=game`` row exists, fall back to the latest play provenance in the game."""
    inner = (
        select(
            PlayRow.game_id.label("game_id"),
            func.max(ProvenanceRecordRow.id).label("max_id"),
        )
        .select_from(ProvenanceRecordRow)
        .join(
            PlayRow,
            and_(ProvenanceRecordRow.entity_type == "play", ProvenanceRecordRow.entity_id == PlayRow.play_id),
        )
        .group_by(PlayRow.game_id)
    ).subquery()
    return (
        select(
            inner.c.game_id,
            ProvenanceRecordRow.import_job_id,
            ProvenanceRecordRow.warehouse_written_at,
            ProvenanceRecordRow.ingest_uri,
        )
        .select_from(inner)
        .join(
            ProvenanceRecordRow,
            and_(
                ProvenanceRecordRow.id == inner.c.max_id,
                ProvenanceRecordRow.entity_type == "play",
            ),
        )
    ).subquery()


def _game_inventory_order_by():
    """
    Order games for inventory listing: ascending by schedule, unknown schedules last.

    Implemented without ``NULLS LAST`` so SQLite versions before 3.30 work; same ordering
    as Postgres ``ASC NULLS LAST`` for a datetime column.
    """
    sched_null_group = case((GameRow.scheduled_start_utc.is_(None), 1), else_=0)
    return sched_null_group.asc(), GameRow.scheduled_start_utc.asc(), GameRow.game_id.asc()


def _first_artifact_per_job_subquery():
    pick = (
        select(
            SourceArtifactRow.import_job_id.label("job_id"),
            func.min(SourceArtifactRow.id).label("min_id"),
        )
        .group_by(SourceArtifactRow.import_job_id)
    ).subquery()
    return (
        select(
            SourceArtifactRow.import_job_id.label("job_id"),
            SourceArtifactRow.logical_name,
            SourceArtifactRow.uri,
        )
        .join(
            pick,
            and_(
                SourceArtifactRow.import_job_id == pick.c.job_id,
                SourceArtifactRow.id == pick.c.min_id,
            ),
        )
    ).subquery()


class WarehouseInventoryService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_game_inventory_page(
        self,
        filters: GameInventoryFilters,
        page: PageParams,
    ) -> tuple[tuple[WarehouseGameInventoryItem, ...], bool]:
        drive_counts = (
            select(DriveRow.game_id.label("gid"), func.count().label("drive_count")).group_by(DriveRow.game_id)
        ).subquery()
        play_counts = (
            select(PlayRow.game_id.label("gid"), func.count().label("play_count")).group_by(PlayRow.game_id)
        ).subquery()
        prov_game_sq = _latest_game_provenance_subquery()
        prov_play_sq = _latest_play_provenance_per_game_subquery()
        art_sq = _first_artifact_per_job_subquery()
        ht = aliased(TeamRow)
        at = aliased(TeamRow)
        job_id_expr = func.coalesce(prov_game_sq.c.import_job_id, prov_play_sq.c.import_job_id)
        imported_expr = func.coalesce(prov_game_sq.c.warehouse_written_at, prov_play_sq.c.warehouse_written_at)
        ingest_uri_expr = func.coalesce(prov_game_sq.c.ingest_uri, prov_play_sq.c.ingest_uri)

        stmt = (
            select(
                GameRow,
                SeasonRow.year_label,
                LeagueRow.name.label("league_name"),
                ht.full_name.label("home_team_name"),
                at.full_name.label("away_team_name"),
                func.coalesce(drive_counts.c.drive_count, 0).label("drive_count"),
                func.coalesce(play_counts.c.play_count, 0).label("play_count"),
                job_id_expr.label("import_job_id"),
                imported_expr.label("imported_at"),
                ingest_uri_expr.label("provenance_ingest_uri"),
                art_sq.c.logical_name.label("artifact_logical_name"),
                art_sq.c.uri.label("artifact_uri"),
            )
            .select_from(GameRow)
            .join(SeasonRow, GameRow.season_id == SeasonRow.season_id)
            .join(LeagueRow, GameRow.league_id == LeagueRow.league_id)
            .join(ht, GameRow.home_team_id == ht.team_id)
            .join(at, GameRow.away_team_id == at.team_id)
            .outerjoin(drive_counts, GameRow.game_id == drive_counts.c.gid)
            .outerjoin(play_counts, GameRow.game_id == play_counts.c.gid)
            .outerjoin(prov_game_sq, GameRow.game_id == prov_game_sq.c.game_id)
            .outerjoin(prov_play_sq, GameRow.game_id == prov_play_sq.c.game_id)
            .outerjoin(art_sq, job_id_expr == art_sq.c.job_id)
        )

        if filters.league_id:
            stmt = stmt.where(GameRow.league_id == filters.league_id)
        if filters.season_id:
            stmt = stmt.where(GameRow.season_id == filters.season_id)
        if filters.team_id:
            tid = filters.team_id
            stmt = stmt.where(or_(GameRow.home_team_id == tid, GameRow.away_team_id == tid))
        if filters.import_job_id:
            jid = filters.import_job_id
            stmt = stmt.where(
                or_(
                    exists(
                        select(ProvenanceRecordRow.id).where(
                            ProvenanceRecordRow.entity_type == "game",
                            ProvenanceRecordRow.entity_id == GameRow.game_id,
                            ProvenanceRecordRow.import_job_id == jid,
                        )
                    ),
                    exists(
                        select(ProvenanceRecordRow.id)
                        .select_from(ProvenanceRecordRow)
                        .join(
                            PlayRow,
                            and_(
                                ProvenanceRecordRow.entity_type == "play",
                                ProvenanceRecordRow.entity_id == PlayRow.play_id,
                            ),
                        )
                        .where(
                            PlayRow.game_id == GameRow.game_id,
                            ProvenanceRecordRow.import_job_id == jid,
                        )
                    ),
                )
            )

        stmt = stmt.order_by(*_game_inventory_order_by()).limit(page.limit + 1).offset(page.offset)
        rows = self._session.execute(stmt).all()
        has_more = len(rows) > page.limit
        rows = rows[: page.limit]

        items: list[WarehouseGameInventoryItem] = []
        for row in rows:
            g: GameRow = row[0]
            year_label = str(row.year_label)
            league_name = str(row.league_name)
            home_name = str(row.home_team_name)
            away_name = str(row.away_team_name)
            d_count = int(row.drive_count)
            p_count = int(row.play_count)
            job_id = row.import_job_id
            imported_at = row.imported_at
            art_name = row.artifact_logical_name
            art_uri = row.artifact_uri
            prov_uri = row.provenance_ingest_uri
            hint = None
            if art_name:
                hint = str(art_name)
            elif art_uri:
                hint = str(art_uri)
            elif prov_uri:
                hint = str(prov_uri)

            items.append(
                WarehouseGameInventoryItem(
                    game_id=g.game_id,
                    league_id=g.league_id,
                    league_name=league_name,
                    season_id=g.season_id,
                    season_year_label=year_label,
                    scheduled_start_utc=g.scheduled_start_utc,
                    status=g.status,
                    home_team_id=g.home_team_id,
                    away_team_id=g.away_team_id,
                    home_team_name=home_name,
                    away_team_name=away_name,
                    home_score_final=g.home_score_final,
                    away_score_final=g.away_score_final,
                    drive_count=d_count,
                    play_count=p_count,
                    import_job_id=job_id,
                    imported_at=imported_at,
                    source_artifact_hint=hint,
                )
            )
        return tuple(items), has_more

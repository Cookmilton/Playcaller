"""
Load JSON from disk → normalize → persist (minimal league/season/team/game only).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import func, select

from football_history_warehouse.config.database import DatabaseConfig, get_database_url
from football_history_warehouse.ingest.normalize import normalize_espn_summary
from football_history_warehouse.ingest.writer import IngestResult, ingest_game_bundle
from football_history_warehouse.storage.bootstrap import ensure_schema_exists
from football_history_warehouse.storage.database import create_warehouse_engine
from football_history_warehouse.storage.database.models import GameRow, LeagueRow, SeasonRow, TeamRow
from football_history_warehouse.storage.database.session import session_scope


def ingest_from_json_file(
    path: Path,
    *,
    database_url: str | None = None,
    league: str | None = None,
    season: int | None = None,
) -> IngestResult:
    """
    Read ESPN summary JSON from ``path``, ensure schema, ingest one game in one transaction.

    Uses ``FOOTBALL_WAREHOUSE_DATABASE_URL`` when ``database_url`` is omitted (raises if unset
    and no dev fallback in config layer — set env explicitly for scripts).
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    bundle = normalize_espn_summary(
        raw,
        league_code=league,
        season_year_override=season,
    )

    url = database_url or get_database_url(required=True)
    assert url is not None
    engine = create_warehouse_engine(DatabaseConfig(database_url=url))
    try:
        ensure_schema_exists(engine)
        with session_scope(engine) as session:
            result = ingest_game_bundle(session, bundle)
    finally:
        engine.dispose()

    return result


def league_code_and_display_for_espn_sport(sport: str) -> tuple[str, str | None]:
    """
    Map Play Caller ESPN sport keys (``EspnFootballProvider``) to warehouse league codes.

    Display names are only needed where :func:`normalize_espn_summary` defaults would be terse.
    """
    s = str(sport or "").strip().lower()
    if s == "college-football":
        return "NCAAF", "NCAA Football"
    if s == "ufl":
        return "UFL", "United Football League"
    if s == "nfl":
        return "NFL", None
    return "NFL", None


def ingest_espn_summary_payload(
    raw: Mapping[str, Any],
    *,
    database_url: str | None = None,
    league: str | None = None,
    season: int | None = None,
    league_display_name: str | None = None,
) -> IngestResult | None:
    """
    Normalize and persist one game from an in-memory ESPN summary dict (same shape as on-disk JSON).

    When ``database_url`` is omitted, uses :func:`get_database_url` with ``required=False``:
    returns ``None`` if no warehouse URL is configured (no dev fallback unless ``PLAYCALLER_DEV_MODE``).
    """
    url = database_url or get_database_url(required=False)
    if not url:
        return None
    payload = dict(raw)
    bundle = normalize_espn_summary(
        payload,
        league_code=league,
        season_year_override=season,
        league_display_name=league_display_name,
    )
    engine = create_warehouse_engine(DatabaseConfig(database_url=url))
    try:
        ensure_schema_exists(engine)
        with session_scope(engine) as session:
            result = ingest_game_bundle(session, bundle)
    finally:
        engine.dispose()
    return result


def ingest_espn_summary_after_live_fetch(
    raw: Mapping[str, Any],
    *,
    sport: str,
    database_url: str | None = None,
    season: int | None = None,
) -> IngestResult | None:
    """
    Convenience for the live ESPN sync path: maps ``sport`` → league metadata, then :func:`ingest_espn_summary_payload`.

    Returns ``None`` when the warehouse is not configured or ingest is a no-op at the DB layer.
    """
    lc, ldisp = league_code_and_display_for_espn_sport(sport)
    return ingest_espn_summary_payload(
        raw,
        database_url=database_url,
        league=lc,
        season=season,
        league_display_name=ldisp,
    )


def verify_ingested_game(database_url: str, game_id: str) -> str:
    """Return a one-line human summary of the game row for CLI confirmation."""
    engine = create_warehouse_engine(DatabaseConfig(database_url=database_url))
    try:
        with session_scope(engine) as session:
            g = session.get(GameRow, game_id)
            if g is None:
                return f"(game {game_id!r} not found)"
            ht = session.get(TeamRow, g.home_team_id)
            at = session.get(TeamRow, g.away_team_id)
            hn = ht.full_name if ht else g.home_team_id
            an = at.full_name if at else g.away_team_id
            return (
                f"external_id={g.game_id.removeprefix('espn:')}, "
                f"home={hn} {g.home_score_final}, away={an} {g.away_score_final}, status={g.status}"
            )
    finally:
        engine.dispose()


def table_row_counts(database_url: str) -> dict[str, int]:
    """Best-effort counts for operator logs (minimal ingest tables)."""
    engine = create_warehouse_engine(DatabaseConfig(database_url=database_url))
    try:
        with session_scope(engine) as session:
            return {
                "leagues": int(session.scalar(select(func.count()).select_from(LeagueRow)) or 0),
                "seasons": int(session.scalar(select(func.count()).select_from(SeasonRow)) or 0),
                "teams": int(session.scalar(select(func.count()).select_from(TeamRow)) or 0),
                "games": int(session.scalar(select(func.count()).select_from(GameRow)) or 0),
            }
    finally:
        engine.dispose()

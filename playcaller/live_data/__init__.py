"""
Near-real-time game data ingestion (provider-agnostic).

UI and predictors consume normalized snapshots via ``sync.apply_snapshot``; providers
translate vendor JSON into :class:`NormalizedGameSnapshot`.
"""

from .espn_football import (
    EspnEventTeams,
    EspnFootballProvider,
    fetch_event_teams,
    list_espn_scoreboard_games,
    parse_event_teams_from_summary,
)
from .http_util import JsonFetchResult, fetch_json, http_insecure_ssl_enabled, ssl_insecure_fallback_permitted
from .sync import SyncOptions, SyncResult, apply_snapshot, session_mark_manual
from .types import FetchResult, NormalizedGameSnapshot

__all__ = [
    "EspnEventTeams",
    "EspnFootballProvider",
    "FetchResult",
    "NormalizedGameSnapshot",
    "SyncOptions",
    "SyncResult",
    "apply_snapshot",
    "fetch_event_teams",
    "JsonFetchResult",
    "fetch_json",
    "http_insecure_ssl_enabled",
    "ssl_insecure_fallback_permitted",
    "list_espn_scoreboard_games",
    "parse_event_teams_from_summary",
    "session_mark_manual",
]

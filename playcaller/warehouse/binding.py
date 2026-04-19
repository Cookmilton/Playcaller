"""
Resolve canonical warehouse scope from session metadata, env, and live ESPN event id.

Session metadata (optional keys on ``Game.session_metadata``)::

    warehouse_league_id
    warehouse_season_id
    warehouse_game_id
    warehouse_coached_team_id   # canonical team id for **our** sideline
    warehouse_opponent_team_id  # optional canonical id for opponent

Environment fallbacks (dev / CI)::

    PLAYCALLER_WAREHOUSE_LEAGUE_ID
    PLAYCALLER_WAREHOUSE_SEASON_ID
    PLAYCALLER_WAREHOUSE_GAME_ID
    PLAYCALLER_WAREHOUSE_COACHED_TEAM_ID
    PLAYCALLER_WAREHOUSE_OPPONENT_TEAM_ID

Live manual Event ID: ``401…`` → warehouse game id ``espn-<id>`` when ``warehouse_game_id`` is not set.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True, slots=True)
class WarehouseBinding:
    """Canonical ids for warehouse queries (opaque strings from imports)."""

    league_id: str | None = None
    season_id: str | None = None
    game_id: str | None = None
    coached_team_id: str | None = None
    opponent_team_id: str | None = None

    def has_query_scope(self) -> bool:
        return bool(self.game_id or (self.league_id and self.season_id) or self.league_id or self.season_id)


def _strip(s: Optional[str]) -> str | None:
    if s is None:
        return None
    t = str(s).strip()
    return t or None


def _meta_str(meta: Optional[Mapping[str, Any]], key: str) -> str | None:
    if not meta:
        return None
    return _strip(meta.get(key))


def _event_id_to_game_id(raw: str) -> str | None:
    """``401220123`` → ``espn-401220123``."""
    s = re.sub(r"\D", "", str(raw).strip())
    if len(s) < 9:
        return None
    return f"espn-{s}"


def build_warehouse_binding(
    session_metadata: Optional[Mapping[str, Any]],
    *,
    live_event_id: str | None = None,
) -> WarehouseBinding:
    """Merge metadata, environment, and optional ESPN event id into one binding."""
    league = _meta_str(session_metadata, "warehouse_league_id") or _strip(
        os.environ.get("PLAYCALLER_WAREHOUSE_LEAGUE_ID")
    )
    season = _meta_str(session_metadata, "warehouse_season_id") or _strip(
        os.environ.get("PLAYCALLER_WAREHOUSE_SEASON_ID")
    )
    game = _meta_str(session_metadata, "warehouse_game_id") or _strip(os.environ.get("PLAYCALLER_WAREHOUSE_GAME_ID"))
    if game is None and live_event_id:
        game = _event_id_to_game_id(live_event_id)

    coached = _meta_str(session_metadata, "warehouse_coached_team_id") or _strip(
        os.environ.get("PLAYCALLER_WAREHOUSE_COACHED_TEAM_ID")
    )
    opponent = _meta_str(session_metadata, "warehouse_opponent_team_id") or _strip(
        os.environ.get("PLAYCALLER_WAREHOUSE_OPPONENT_TEAM_ID")
    )
    return WarehouseBinding(
        league_id=league,
        season_id=season,
        game_id=game,
        coached_team_id=coached,
        opponent_team_id=opponent,
    )


def offense_team_id_on_field(*, possession: str, binding: WarehouseBinding) -> str | None:
    """Warehouse ``TeamId`` for the offense currently on the field."""
    if possession == "offense":
        return binding.coached_team_id
    if possession == "defense":
        return binding.opponent_team_id
    return binding.coached_team_id

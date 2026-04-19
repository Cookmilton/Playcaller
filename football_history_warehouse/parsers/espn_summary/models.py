"""
Intermediate representation for ESPN ``game summary`` JSON — not canonical warehouse rows.

Normalization maps this bundle into :mod:`football_history_warehouse.domain` models
with league rules and ID assignment. This layer only describes what the feed contained.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


SOURCE_FORMAT_ESPN_GAME_SUMMARY_V1 = "espn_game_summary_json_v1"


@dataclass(frozen=True, slots=True)
class ParseNotice:
    """Non-fatal issue: missing optional fields, ambiguity, or mild shape drift."""

    severity: Literal["warning", "info"]
    code: str
    detail: str
    where: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedEspnParticipant:
    role: str | None
    display_name: str | None
    jersey: str | None


@dataclass(frozen=True, slots=True)
class ParsedEspnPlay:
    """One play row as represented in the feed (plus raw snapshot for audit)."""

    source_play_id: str
    sequence_in_drive: int
    play_type_text: str | None
    play_type_id: str | None
    description_text: str | None
    stat_yardage: int | None
    participants: tuple[ParsedEspnParticipant, ...]
    raw_play: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ParsedEspnDrive:
    source_drive_id: str
    drive_order: int
    offense_espn_team_id: str | None
    plays: tuple[ParsedEspnPlay, ...]
    raw_drive: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ParsedEspnBroadcastStatus:
    """In-progress or final-ish snapshot from ``header`` when present."""

    period: int | None
    display_clock: str | None
    completed: bool | None
    type_detail: str | None


@dataclass(frozen=True, slots=True)
class ParsedEspnTeam:
    espn_team_id: str
    home_away: Literal["home", "away"]
    abbreviation: str | None
    display_name: str | None
    short_display_name: str | None
    score: int | None


@dataclass(frozen=True, slots=True)
class ParsedEspnGame:
    """
    Game-level view extracted from ``header`` + ``drives``.

    ``source_event_id`` is the ESPN competition/game id when present.
    """

    source_format: str
    source_event_id: str
    teams: tuple[ParsedEspnTeam, ...]
    broadcast: ParsedEspnBroadcastStatus | None
    drives: tuple[ParsedEspnDrive, ...]
    raw_header_competition: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EspnSummaryParseResult:
    """Return type for :func:`parse_espn_game_summary`."""

    game: ParsedEspnGame
    notices: tuple[ParseNotice, ...]

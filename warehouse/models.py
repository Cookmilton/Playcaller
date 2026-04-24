from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Optional

from warehouse.taxonomy import PlayResult, PlayType


class GameStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINAL = "FINAL"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"


class GameType(StrEnum):
    PRE = "PRE"
    REG = "REG"
    POST = "POST"


class DataSource(StrEnum):
    NFLVERSE = "NFLVERSE"
    MANUAL = "MANUAL"
    OTHER = "OTHER"


@dataclass(kw_only=True, slots=True)
class Game:
    id: str
    source: DataSource
    external_game_id: str
    season: int
    week: int
    game_type: GameType
    home_team: str
    away_team: str
    game_date: date
    status: GameStatus
    final_home_score: Optional[int] = None
    final_away_score: Optional[int] = None


@dataclass(kw_only=True, slots=True)
class RawGamePayload:
    id: str
    game_id: str
    source: DataSource
    fetched_at: datetime
    payload_json: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "game_id": self.game_id,
            "source": self.source.value,
            "fetched_at": self.fetched_at.isoformat(),
            "payload_json": self.payload_json,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RawGamePayload:
        raw_fetched = data["fetched_at"]
        if isinstance(raw_fetched, datetime):
            fetched_at = raw_fetched
        elif isinstance(raw_fetched, str):
            fetched_at = datetime.fromisoformat(raw_fetched)
        else:
            msg = f"fetched_at must be datetime or ISO str, got {type(raw_fetched).__name__}"
            raise TypeError(msg)

        raw_source = data["source"]
        if isinstance(raw_source, DataSource):
            source = raw_source
        else:
            source = DataSource(str(raw_source))

        return cls(
            id=str(data["id"]),
            game_id=str(data["game_id"]),
            source=source,
            fetched_at=fetched_at,
            payload_json=str(data["payload_json"]),
        )


@dataclass(kw_only=True, slots=True)
class Play:
    # Required fields first (dataclass rule); optional situational fields follow.
    id: str
    game_id: str
    external_play_id: str
    play_sequence: int
    quarter: int
    score_offense: int
    score_defense: int
    play_type: PlayType
    play_result: PlayResult
    first_down: bool
    touchdown: bool
    turnover: bool
    raw_description: str
    clock_seconds: Optional[int] = None
    possession_team: Optional[str] = None
    defense_team: Optional[str] = None
    down: Optional[int] = None
    distance: Optional[int] = None
    yardline_100: Optional[int] = None
    yards_gained: Optional[int] = None
    epa: Optional[float] = None
    wpa: Optional[float] = None
    success: Optional[bool] = None
    shotgun: Optional[bool] = None
    no_huddle: Optional[bool] = None
    qb_dropback: Optional[bool] = None
    defenders_in_box: Optional[int] = None
    offense_personnel: Optional[str] = None
    air_yards: Optional[float] = None
    yards_after_catch: Optional[float] = None
    xpass: Optional[float] = None
    passer_player_name: Optional[str] = None
    receiver_player_name: Optional[str] = None
    rusher_player_name: Optional[str] = None
    pass_length: Optional[str] = None
    pass_location: Optional[str] = None
    run_location: Optional[str] = None
    run_gap: Optional[str] = None

    def __post_init__(self) -> None:
        if self.quarter not in (1, 2, 3, 4, 5):
            raise ValueError(f"quarter must be in 1..5, got {self.quarter}")
        if self.yardline_100 is not None and not (0 <= self.yardline_100 <= 100):
            raise ValueError(
                f"yardline_100 must be in 0..100 when set, got {self.yardline_100}"
            )
        if self.down is not None and self.down not in (1, 2, 3, 4):
            raise ValueError(f"down must be in 1..4 when set, got {self.down}")


@dataclass(kw_only=True, slots=True)
class DerivedPlayFeatures:
    play_id: str
    red_zone: bool
    goal_to_go: bool
    four_down_territory: bool
    two_minute: bool
    score_diff: int
    score_diff_bucket: str
    field_zone: str
    distance_bucket: str
    game_script: str
    previous_play_type: Optional[str] = None
    drive_number: int

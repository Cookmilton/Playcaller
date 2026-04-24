"""Dataclasses for review coaching insights (analytics layer)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class PlayMistake:
    """Ranked coaching mistake with traceable drive/play coordinates (film room)."""

    play_id: str
    drive_number: int  # 1-based display (Drive N)
    play_number: int  # 1-based play index on drive
    severity: int  # 0–100 aggregate
    context_summary: str
    actual_summary: str
    model_top: str
    why_it_matters: str
    when_label: str  # compact clock / quarter for headers
    drive_id: int  # 0-based into ``Game.drives`` (focus / navigation)


@dataclass(frozen=True)
class CallQualityLabel:
    """Deterministic per-snap coaching signal (auditable rubric in ``call_quality``)."""

    symbol: str  # "✅" | "⚠️" | "❌" | "—"
    category: str  # "good" | "questionable" | "poor" | "n/a"
    reason: str


@dataclass(frozen=True)
class Pattern:
    """One surfaced cross-drive tendency line (traceable to offense snapshot indices)."""

    category: str  # "run_pass" | "third_down" | "red_zone" | ...
    title: str
    summary: str
    support_plays: Tuple[int, ...]
    significance: int


@dataclass(frozen=True)
class SituationAggregate:
    """Filtered situational rollup for Review Session chips."""

    situation_key: str
    situation_label: str
    play_count: int
    success_count: int
    success_rate: Optional[float]
    avg_yards: Optional[float]
    run_count: int
    pass_count: int
    most_common_result: Optional[str]
    play_indices: Tuple[int, ...]


@dataclass(frozen=True)
class GameStoryBullet:
    """One ranked game-level insight with traceable drive indices."""

    text: str
    category: str
    significance: int
    related_drive_indices: Tuple[int, ...]  # 0-based into ``Game.drives``


@dataclass(frozen=True)
class DriveGrade:
    """Letter grade with transparent component breakdown."""

    letter: str  # "A" | "B" | "C" | "D" | "F" | "—"
    total_score: int | None  # None when letter "—"
    outcome_component: int | None
    efficiency_component: int | None
    situational_component: int | None
    model_component: int | None
    failure_explanations: Tuple[str, ...] = ()

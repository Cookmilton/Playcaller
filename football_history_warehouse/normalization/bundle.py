"""In-memory canonical graph produced by normalization (not yet persisted)."""

from __future__ import annotations

from dataclasses import dataclass

from football_history_warehouse.domain import Drive, Game, Play
from football_history_warehouse.normalization.notices import NormalizationNotice


@dataclass(frozen=True, slots=True)
class CanonicalGameBundle:
    """One game with ordered drives and plays (``sequence_in_game`` is global order)."""

    game: Game
    drives: tuple[Drive, ...]
    plays: tuple[Play, ...]
    notices: tuple[NormalizationNotice, ...]

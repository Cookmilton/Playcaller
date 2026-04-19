"""
Normalization: transform parsed vendor shapes into canonical domain records.

Uses ``rules`` for league-aware interpretation later; v1 ESPN summary mapping
lives under ``normalization.espn``. Output is in-memory
:class:`~football_history_warehouse.normalization.bundle.CanonicalGameBundle`
until persistence. No ML or playcalling logic belongs here.
"""

from football_history_warehouse.normalization.bundle import CanonicalGameBundle
from football_history_warehouse.normalization.context import GameNormalizationContext
from football_history_warehouse.normalization.espn import normalize_espn_summary_parse_result
from football_history_warehouse.normalization.exceptions import NormalizationError
from football_history_warehouse.normalization.notices import NormalizationNotice

__all__ = [
    "CanonicalGameBundle",
    "GameNormalizationContext",
    "NormalizationError",
    "NormalizationNotice",
    "normalize_espn_summary_parse_result",
]

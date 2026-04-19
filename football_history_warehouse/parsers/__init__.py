"""
Vendor parsers producing intermediate representations for normalization.

v1: :mod:`football_history_warehouse.parsers.espn_summary` (ESPN game summary JSON).
"""

from football_history_warehouse.parsers.espn_summary import (
    EspnSummaryParseResult,
    EspnSummaryParserError,
    parse_espn_game_summary,
    parse_espn_game_summary_json_file,
)

__all__ = [
    "EspnSummaryParseResult",
    "EspnSummaryParserError",
    "parse_espn_game_summary",
    "parse_espn_game_summary_json_file",
]

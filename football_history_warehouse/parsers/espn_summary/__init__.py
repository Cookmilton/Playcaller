"""
ESPN game summary JSON → structured intermediate representation (v1).

Use this package for historical imports saved as ESPN **summary** JSON. Parser
logic is independent of canonical normalization and the playcalling application.
"""

from football_history_warehouse.parsers.espn_summary.exceptions import EspnSummaryParserError
from football_history_warehouse.parsers.espn_summary.models import (
    SOURCE_FORMAT_ESPN_GAME_SUMMARY_V1,
    EspnSummaryParseResult,
    ParseNotice,
    ParsedEspnDrive,
    ParsedEspnGame,
    ParsedEspnParticipant,
    ParsedEspnPlay,
    ParsedEspnTeam,
    ParsedEspnBroadcastStatus,
)
from football_history_warehouse.parsers.espn_summary.parse import (
    parse_espn_game_summary,
    parse_espn_game_summary_json_bytes,
    parse_espn_game_summary_json_file,
)

__all__ = [
    "SOURCE_FORMAT_ESPN_GAME_SUMMARY_V1",
    "EspnSummaryParseResult",
    "EspnSummaryParserError",
    "ParseNotice",
    "ParsedEspnBroadcastStatus",
    "ParsedEspnDrive",
    "ParsedEspnGame",
    "ParsedEspnParticipant",
    "ParsedEspnPlay",
    "ParsedEspnTeam",
    "parse_espn_game_summary",
    "parse_espn_game_summary_json_bytes",
    "parse_espn_game_summary_json_file",
]

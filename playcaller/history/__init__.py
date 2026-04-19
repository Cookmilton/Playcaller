"""
Historical game JSON corpus (offline).

**Parse:** ``json.loads`` → ``game_from_dict`` (same as the main app).

**Normalize:** ``build_normalized_plays`` joins ``drives[].plays`` with closed audit rows.

Does **not** use live session state or change recommendation scoring.
"""

from .buckets import (
    FIELD_ZONE_NEIGHBORS,
    DISTANCE_BUCKET_NEIGHBORS,
    SituationSignature,
    situation_signature_from_context,
    situation_signature_from_normalized_row,
)
from .influence import (
    HistoricalInfluenceConfig,
    apply_historical_family_adjustments,
    resolve_historical_plays_for_call,
)
from .recommendation_metadata import build_historical_metadata_for_recommendation
from .ingest import IngestReport, ingest_directory, ingest_file_bytes, ingest_zip_bytes, iter_json_from_zip
from .loader import load_game_json_path, load_history_directory, parse_game_dict
from .repository_corpus import game_record_by_id, history_corpus_from_repository, load_repository_plays
from .repository_manifest import list_game_records, read_manifest, update_game_record_fields, write_manifest
from .repository_paths import ensure_repository_layout, resolve_history_repository_root
from .repository_settings import (
    HistoryRepositorySettings,
    build_historical_influence_config,
    load_history_repository_settings,
)
from .normalize import build_normalized_plays, linked_actual_matches_play
from .outcome_aggregates import (
    HistoricalOutcomeSummary,
    OutcomeTotals,
    aggregate_matched_play_outcomes,
    outcome_summary_to_dict,
)
from .query import (
    SimilarSituationAggregates,
    SimilarSituationResult,
    attach_outcome_summary,
    query_similar_plays,
    query_similar_plays_from_context,
    query_similar_plays_from_corpus,
    query_similar_plays_from_corpus_context,
    result_to_debug_dict,
)
from .records import (
    GameJsonLoadError,
    HistoricalGameSnapshot,
    HistoryCorpus,
    NormalizedHistoricalPlay,
    normalized_historical_play_from_json_dict,
    normalized_historical_play_to_json_dict,
)

__all__ = [
    "HistoricalInfluenceConfig",
    "HistoryRepositorySettings",
    "IngestReport",
    "apply_historical_family_adjustments",
    "build_historical_influence_config",
    "build_historical_metadata_for_recommendation",
    "load_history_repository_settings",
    "ensure_repository_layout",
    "game_record_by_id",
    "history_corpus_from_repository",
    "ingest_directory",
    "ingest_file_bytes",
    "ingest_zip_bytes",
    "iter_json_from_zip",
    "list_game_records",
    "load_repository_plays",
    "normalized_historical_play_from_json_dict",
    "normalized_historical_play_to_json_dict",
    "read_manifest",
    "resolve_history_repository_root",
    "resolve_historical_plays_for_call",
    "DISTANCE_BUCKET_NEIGHBORS",
    "FIELD_ZONE_NEIGHBORS",
    "GameJsonLoadError",
    "HistoricalGameSnapshot",
    "HistoricalOutcomeSummary",
    "HistoryCorpus",
    "NormalizedHistoricalPlay",
    "OutcomeTotals",
    "SimilarSituationAggregates",
    "SimilarSituationResult",
    "SituationSignature",
    "aggregate_matched_play_outcomes",
    "attach_outcome_summary",
    "build_normalized_plays",
    "linked_actual_matches_play",
    "load_game_json_path",
    "load_history_directory",
    "parse_game_dict",
    "query_similar_plays",
    "query_similar_plays_from_context",
    "query_similar_plays_from_corpus",
    "query_similar_plays_from_corpus_context",
    "outcome_summary_to_dict",
    "result_to_debug_dict",
    "situation_signature_from_context",
    "situation_signature_from_normalized_row",
    "update_game_record_fields",
    "write_manifest",
]

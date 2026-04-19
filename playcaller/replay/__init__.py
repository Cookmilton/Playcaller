"""Retroactive model replay helpers (not stored historical recommendations)."""

from .analysis_types import (
    ActualVsReplayComparisonRow,
    ModelReplayStructuredResult,
    PreSnapContextRecord,
    comparison_table_to_dicts,
)
from .comparison import (
    actual_run_pass_bucket,
    family_match_actual_vs_replay,
    model_replay_one_line,
    model_replay_structured_from_recommend,
    pre_snap_record_from_context,
)
from .previous_drive_replay import (
    best_presnap_chain_for_drive_plays,
    cached_comparison_rows_for_archived_drive,
    comparison_rows_cache_key,
    comparison_rows_for_archived_drive,
    map_recommendation_to_run_pass,
    presnap_chain_for_drive_plays,
    replay_rows_for_archived_drive,
    score_diff_for_archived_possession,
)
from .replay_taxonomy import (
    actual_play_summary_bucket,
    coarse_bucket_alignment,
    replay_summary_bucket_from_recommend,
)

__all__ = [
    "ActualVsReplayComparisonRow",
    "ModelReplayStructuredResult",
    "PreSnapContextRecord",
    "actual_play_summary_bucket",
    "coarse_bucket_alignment",
    "replay_summary_bucket_from_recommend",
    "actual_run_pass_bucket",
    "best_presnap_chain_for_drive_plays",
    "cached_comparison_rows_for_archived_drive",
    "comparison_rows_cache_key",
    "comparison_rows_for_archived_drive",
    "comparison_table_to_dicts",
    "family_match_actual_vs_replay",
    "map_recommendation_to_run_pass",
    "model_replay_one_line",
    "model_replay_structured_from_recommend",
    "pre_snap_record_from_context",
    "presnap_chain_for_drive_plays",
    "replay_rows_for_archived_drive",
    "score_diff_for_archived_possession",
]

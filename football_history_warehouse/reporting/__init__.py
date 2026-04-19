"""
Import and data-quality reporting.

Tracks ingest/normalization outcomes: counts, failures, deduplication,
and reconciliation gaps. Distinct from application user analytics.
"""

from football_history_warehouse.reporting.pipeline_report import (
    ImportJobPipelineReport,
    PersistenceAttemptReport,
    PipelineOutcome,
    SkippedRecordReport,
    build_import_pipeline_report,
    validation_result_to_dict,
)

__all__ = [
    "ImportJobPipelineReport",
    "PersistenceAttemptReport",
    "PipelineOutcome",
    "SkippedRecordReport",
    "build_import_pipeline_report",
    "validation_result_to_dict",
]

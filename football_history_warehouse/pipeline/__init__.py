"""
Orchestrated ingest pipelines (raw → parse → normalize → validate → persist).

See :mod:`football_history_warehouse.pipeline.espn_summary_import`.
"""

from football_history_warehouse.pipeline.dedupe import canonical_game_exists, raw_payload_already_registered
from football_history_warehouse.pipeline.espn_summary_import import (
    EspnGameImportResult,
    EspnSummaryImportSpec,
    import_espn_summary_game_file,
    load_manifest,
    spec_from_manifest_entry,
)

__all__ = [
    "EspnGameImportResult",
    "EspnSummaryImportSpec",
    "canonical_game_exists",
    "import_espn_summary_game_file",
    "load_manifest",
    "raw_payload_already_registered",
    "spec_from_manifest_entry",
]

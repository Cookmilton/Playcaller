"""
Ingest: pull raw history from external sources into the warehouse boundary.

Raw registration (``ingest.raw``) persists source artifacts and import jobs before
normalization. Vendor parsers and canonical mapping live downstream.
"""

from football_history_warehouse.ingest.exceptions import IngestValidationError, RawIngestError
from football_history_warehouse.ingest.from_json import (
    ingest_espn_summary_after_live_fetch,
    ingest_espn_summary_payload,
    ingest_from_json_file,
    league_code_and_display_for_espn_sport,
)
from football_history_warehouse.ingest.normalize import NormalizedGameBundle, normalize_espn_summary
from football_history_warehouse.ingest.raw import (
    RawIngestService,
    RegisterRawGameFileRequest,
    create_raw_import_job,
)
from football_history_warehouse.ingest.writer import IngestResult

__all__ = [
    "IngestResult",
    "IngestValidationError",
    "NormalizedGameBundle",
    "RawIngestError",
    "RawIngestService",
    "RegisterRawGameFileRequest",
    "create_raw_import_job",
    "ingest_espn_summary_after_live_fetch",
    "ingest_espn_summary_payload",
    "ingest_from_json_file",
    "league_code_and_display_for_espn_sport",
    "normalize_espn_summary",
]

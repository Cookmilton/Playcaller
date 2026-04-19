"""
Ingest: pull raw history from external sources into the warehouse boundary.

Raw registration (``ingest.raw``) persists source artifacts and import jobs before
normalization. Vendor parsers and canonical mapping live downstream.
"""

from football_history_warehouse.ingest.exceptions import RawIngestError
from football_history_warehouse.ingest.raw import (
    RawIngestService,
    RegisterRawGameFileRequest,
    create_raw_import_job,
)

__all__ = [
    "RawIngestError",
    "RawIngestService",
    "RegisterRawGameFileRequest",
    "create_raw_import_job",
]

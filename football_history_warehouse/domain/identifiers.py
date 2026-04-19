"""
Strongly labeled identifier aliases for canonical entities.

These are plain ``str`` at runtime (``NewType``) so they serialize like
strings but static type checkers catch accidental mixing. Internal IDs
should be opaque UUIDs or stable warehouse-generated keys; external IDs
belong in ``SourceMetadata`` / ``source_extensions``.
"""

from __future__ import annotations

from typing import NewType

# Warehouse-native primary keys (opaque strings, e.g. UUIDs)
LeagueId = NewType("LeagueId", str)
SeasonId = NewType("SeasonId", str)
TeamId = NewType("TeamId", str)
GameId = NewType("GameId", str)
DriveId = NewType("DriveId", str)
PlayId = NewType("PlayId", str)
PlayerId = NewType("PlayerId", str)
VenueId = NewType("VenueId", str)
ImportJobId = NewType("ImportJobId", str)

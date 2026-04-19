"""
Repositories — persistence access.

Thin units of work over :class:`~football_history_warehouse.storage.database.base.Base`
rows and :class:`~sqlalchemy.orm.Session`. Business rules stay in ``normalization``
or ``domain``.
"""

from football_history_warehouse.storage.repositories.canonical_bundle import (
    PersistCanonicalBundleParams,
    PersistedCanonicalBundleIds,
    persist_canonical_game_bundle,
)
from football_history_warehouse.storage.repositories.transactional import (
    WarehouseChainIds,
    allocate_sqlite_provenance_ids,
    insert_minimal_warehouse_chain,
)

__all__ = [
    "PersistCanonicalBundleParams",
    "PersistedCanonicalBundleIds",
    "WarehouseChainIds",
    "allocate_sqlite_provenance_ids",
    "insert_minimal_warehouse_chain",
    "persist_canonical_game_bundle",
]

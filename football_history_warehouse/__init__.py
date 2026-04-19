"""
Football history warehouse — normalized ingest, storage, and query.

This package is the intended long-term source of truth for historical
football data (NFL, college, UFL, and future leagues). It must stay free
of UI frameworks and of play-prediction logic; consumers (e.g. a
playcalling application) integrate only through explicit query/reporting
surfaces.

Layers (dependency direction: ingest → normalization → validation → storage → query/reporting):
  config — runtime settings (paths, credentials), not league rules.
  domain       — core types and identifiers for normalized history.
  rules        — league- and competition-specific football rules metadata.
  ingest       — bring raw feeds into the warehouse boundary.
  normalization — map raw records to domain shapes (implementations TBD).
  validation — pre-persistence checks on canonical bundles (no silent fixes).
  storage      — persistence adapters (database layer TBD).
  query        — stable read API for downstream applications.
  reporting    — import runs, data quality, and operator-facing summaries.
"""

__all__: list[str] = []

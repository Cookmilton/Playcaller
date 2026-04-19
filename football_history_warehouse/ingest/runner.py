"""
Ingest job orchestration.

Raw registration: :mod:`football_history_warehouse.ingest.raw`.

End-to-end ESPN summary loads (raw → persist): :mod:`football_history_warehouse.pipeline.espn_summary_import`
and ``python -m football_history_warehouse.cli.import_espn``.
"""

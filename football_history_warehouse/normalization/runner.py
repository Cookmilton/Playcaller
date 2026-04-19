"""
Normalization orchestration.

Use :func:`~football_history_warehouse.normalization.espn.pipeline.normalize_espn_summary_parse_result`
for ESPN summary JSON. After normalization, run
:func:`~football_history_warehouse.validation.validate_canonical_game_bundle` and
:class:`~football_history_warehouse.reporting.pipeline_report.ImportJobPipelineReport`
before persistence (see ``PersistCanonicalBundleParams.validation_result``).
"""

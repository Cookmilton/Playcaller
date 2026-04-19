"""ESPN-specific normalization (parsed summary → canonical models)."""

from football_history_warehouse.normalization.espn.pipeline import normalize_espn_summary_parse_result

__all__ = ["normalize_espn_summary_parse_result"]

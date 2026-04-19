"""Smoke imports for the football history warehouse package layout."""

from __future__ import annotations

import football_history_warehouse
from football_history_warehouse.domain.enums import CompetitionTier, LeagueFamily
from football_history_warehouse.reporting.import_report import ImportRunSummary
from football_history_warehouse.reporting.pipeline_report import PipelineOutcome
from football_history_warehouse.rules.registry import supported_league_families
from football_history_warehouse.validation import validate_canonical_game_bundle


def test_package_docstring_present() -> None:
    assert "source of truth" in (football_history_warehouse.__doc__ or "").lower()


def test_enum_members_stable() -> None:
    assert LeagueFamily.NFL.value == "nfl"
    assert CompetitionTier.UNKNOWN.value == "unknown"


def test_supported_families_includes_planned_leagues() -> None:
    fams = supported_league_families()
    assert LeagueFamily.UFL in fams
    assert LeagueFamily.NCAA_FBS in fams


def test_import_run_summary_frozen() -> None:
    r = ImportRunSummary(run_id="a", source_label="b")
    assert r.run_id == "a"


def test_validation_and_reporting_imports() -> None:
    assert PipelineOutcome.VALIDATION_FAILED.value == "validation_failed"
    assert callable(validate_canonical_game_bundle)

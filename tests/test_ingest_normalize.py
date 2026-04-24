"""Tests for football_history_warehouse.ingest.normalize (pure ESPN summary parsing)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from football_history_warehouse.ingest.exceptions import IngestValidationError
from football_history_warehouse.ingest.normalize import normalize_espn_summary

FIXTURE_PACKERS = Path(__file__).resolve().parent / "fixtures" / "espn_summary_packers_lions_401772891.json"


def test_normalize_packers_lions_fixture() -> None:
    raw = json.loads(FIXTURE_PACKERS.read_text(encoding="utf-8"))
    b = normalize_espn_summary(raw)
    assert b.game.external_id == "401772891"
    assert b.league.code == "NFL"
    assert b.season.year == 2025
    assert b.home_team.external_id == "8"
    assert b.away_team.external_id == "9"
    assert b.home_team.abbreviation == "DET"
    assert b.away_team.abbreviation == "GB"
    assert b.game.home_score == 24
    assert b.game.away_score == 31
    assert b.game.status == "final"


def test_normalize_pure_idempotent() -> None:
    raw = json.loads(FIXTURE_PACKERS.read_text(encoding="utf-8"))
    a = normalize_espn_summary(raw)
    b = normalize_espn_summary(raw)
    assert a == b


def test_normalize_missing_header() -> None:
    with pytest.raises(IngestValidationError, match="header"):
        normalize_espn_summary({})


def test_normalize_missing_competitions() -> None:
    with pytest.raises(IngestValidationError, match="competitions"):
        normalize_espn_summary({"header": {}})

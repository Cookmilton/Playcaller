from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

import warehouse.bulk as wb
from warehouse.bulk import _log_week_v2_null_rates, _null_rates_from_plays


def test_null_rates_percentages() -> None:
    plays = [
        {"epa": None, "success": True},
        {"epa": 0.1, "success": None},
    ]
    r = _null_rates_from_plays(plays)
    assert r["epa"] == pytest.approx(50.0)
    assert r["success"] == pytest.approx(50.0)


def test_null_rates_all_missing_field_counts_as_null() -> None:
    plays = [{"epa": 1.0}]
    r = _null_rates_from_plays(plays)
    assert r["success"] == pytest.approx(100.0)


def test_log_warns_when_rate_above_95(caplog: pytest.LogCaptureFixture) -> None:
    rates = {f: 96.0 for f in wb._V2_PLAY_FIELDS}
    with caplog.at_level(logging.WARNING, logger="warehouse.bulk"), patch(
        "warehouse.bulk._null_rates_for_processed_paths_written", return_value=rates
    ):
        _log_week_v2_null_rates(("p.json",))
    assert any("WARN" in r.getMessage() and "95" in r.getMessage() for r in caplog.records)

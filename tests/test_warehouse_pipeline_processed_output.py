"""Processed JSON output path for ``warehouse.pipeline`` (Review Session disk source)."""

from __future__ import annotations

import math

import pytest

import warehouse.pipeline as pipeline_mod
import warehouse.storage as storage_mod
from warehouse.storage import _make_game_id


def _minimal_game_payload() -> dict:
    return {
        "meta": {
            "external_game_id": "2025_01_AA_BB",
            "season": 2025,
            "week": 1,
            "game_type": "REG",
            "home_team": "KC",
            "away_team": "BUF",
            "game_date": "2025-09-05",
        },
        "plays": [
            {
                "play_id": 1.0,
                "qtr": 1,
                "quarter_seconds_remaining": 900,
                "posteam": "BUF",
                "defteam": "KC",
                "down": 1.0,
                "ydstogo": 10,
                "yardline_100": 75,
                "posteam_score": 0,
                "defteam_score": 0,
                "play_type": "pass",
                "yards_gained": 12,
                "first_down_pass": 1.0,
                "touchdown": 0.0,
                "interception": 0.0,
                "fumble_lost": 0.0,
                "desc": "(15:00) (Shotgun) J.Allen pass short right for 12 yards",
                "home_score": 0,
                "away_score": 0,
                "result": math.nan,
            },
        ],
    }


def test_run_week_ingestion_writes_processed_json_to_expected_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    fake_root = tmp_path / "repo"
    fake_root.mkdir()
    monkeypatch.setattr(storage_mod, "REPO_ROOT", fake_root)

    payload = _minimal_game_payload()
    monkeypatch.setattr(pipeline_mod, "load_week_games", lambda _s, _w: [payload])

    result = pipeline_mod.run_week_ingestion(2025, 1, force_refresh=True)

    game_id = _make_game_id(payload["meta"])
    expected = fake_root / "data" / "processed" / "2025" / "week_01" / f"{game_id}.json"
    assert expected.is_file()
    text = expected.read_text(encoding="utf-8")
    assert '"schema_version": "2.0"' in text
    assert '"game"' in text and '"plays"' in text and '"features"' in text
    assert result.processed_paths_written == (str(expected.resolve()),)

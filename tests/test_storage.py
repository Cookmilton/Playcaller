from __future__ import annotations

from pathlib import Path

import pytest

from warehouse.models import DataSource
from warehouse.storage import list_raw_games, load_raw_game, store_raw_games


def test_store_raw_games_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("warehouse.storage.REPO_ROOT", tmp_path)
    fake = {
        "meta": {
            "external_game_id": "2025_01_KC_BUF",
            "season": 2025,
            "week": 3,
            "game_type": "REG",
            "home_team": "KC",
            "away_team": "BUF",
            "game_date": "2025-09-21",
        },
        "plays": [{"play_id": "1", "desc": "kickoff"}],
    }
    stored = store_raw_games([fake], source=DataSource.NFLVERSE)
    assert len(stored) == 1
    payload = stored[0]

    loaded = load_raw_game(payload.game_id)
    assert loaded is not None
    assert loaded == payload


def test_load_raw_game_missing_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("warehouse.storage.REPO_ROOT", tmp_path)
    assert load_raw_game("does_not_exist") is None


def test_skip_existing_without_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("warehouse.storage.REPO_ROOT", tmp_path)
    fake = {
        "meta": {
            "external_game_id": "x",
            "season": 2024,
            "week": 1,
            "game_type": "REG",
            "home_team": "A",
            "away_team": "B",
            "game_date": "2024-09-05",
        },
        "plays": [],
    }
    first = store_raw_games([fake], overwrite=False)
    second = store_raw_games([fake], overwrite=False)
    assert first[0] == second[0]


def test_list_raw_games(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("warehouse.storage.REPO_ROOT", tmp_path)
    fake = {
        "meta": {
            "external_game_id": "x",
            "season": 2024,
            "week": 2,
            "game_type": "REG",
            "home_team": "KC",
            "away_team": "BUF",
            "game_date": "2024-09-15",
        },
        "plays": [],
    }
    store_raw_games([fake])
    ids = list_raw_games(2024, week=2)
    assert len(ids) == 1
    assert list_raw_games(2024) == ids

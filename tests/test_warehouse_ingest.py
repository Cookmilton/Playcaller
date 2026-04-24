from __future__ import annotations

import json
from typing import Any

import pandas as pd

import warehouse.storage as storage_mod
from warehouse.ingest import load_week_games, load_week_games_from_raw_cache


def test_load_week_games_groups_by_game_id(monkeypatch: Any) -> None:
    df = pd.DataFrame(
        [
            {
                "game_id": "2025_01_BUF_KC",
                "season": 2025,
                "week": 1,
                "season_type": "REG",
                "home_team": "KC",
                "away_team": "BUF",
                "game_date": "2025-09-05",
                "play_id": "40",
                "desc": "kickoff",
            },
            {
                "game_id": "2025_01_BUF_KC",
                "season": 2025,
                "week": 1,
                "season_type": "REG",
                "home_team": "KC",
                "away_team": "BUF",
                "game_date": "2025-09-05",
                "play_id": "80",
                "desc": "run",
            },
            {
                "game_id": "2025_01_GB_DET",
                "season": 2025,
                "week": 1,
                "season_type": "REG",
                "home_team": "DET",
                "away_team": "GB",
                "game_date": "2025-09-07",
                "play_id": "12",
                "desc": "other",
            },
        ]
    )

    def fake_import(_years: list[int], **kwargs: Any) -> pd.DataFrame:
        return df

    monkeypatch.setattr(
        "warehouse.ingest.nfl.import_pbp_data",
        fake_import,
    )

    out = load_week_games(2025, 1, game_type="REG")
    assert len(out) == 2
    by_gid = {g["meta"]["external_game_id"]: g for g in out}
    assert len(by_gid["2025_01_BUF_KC"]["plays"]) == 2
    assert by_gid["2025_01_BUF_KC"]["plays"][0]["play_id"] == "40"
    assert by_gid["2025_01_BUF_KC"]["meta"]["home_team"] == "KC"
    assert len(by_gid["2025_01_GB_DET"]["plays"]) == 1


def test_load_week_games_from_raw_cache_reads_store_shape(
    monkeypatch: Any,
    tmp_path,
) -> None:
    fake_repo = tmp_path / "repo"
    week_dir = fake_repo / "data" / "raw" / "2025" / "week_01"
    week_dir.mkdir(parents=True)
    wrapped = {
        "game": {
            "meta": {
                "external_game_id": "2025_01_X_Y",
                "season": 2025,
                "week": 1,
                "game_type": "REG",
                "home_team": "KC",
                "away_team": "BUF",
                "game_date": "2025-09-05",
            },
            "plays": [{"play_id": 1.0, "play_type": "run", "desc": "rush"}],
        }
    }
    (week_dir / "abc.json").write_text(json.dumps(wrapped), encoding="utf-8")
    monkeypatch.setattr(storage_mod, "REPO_ROOT", fake_repo)

    games = load_week_games_from_raw_cache(2025, 1)
    assert len(games) == 1
    assert games[0]["meta"]["home_team"] == "KC"
    assert len(games[0]["plays"]) == 1

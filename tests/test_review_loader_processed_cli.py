"""CLI smoke helper for processed JSON inventory (``warehouse.review_loader``)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

import warehouse.storage as storage_mod
from warehouse.review_loader import list_available_processed_games, print_processed_inventory_summary


def test_list_available_processed_games_default_uses_repo_root_not_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    elsewhere = tmp_path / "other_cwd"
    elsewhere.mkdir()
    monkeypatch.setattr(storage_mod, "REPO_ROOT", fake_repo)
    monkeypatch.chdir(elsewhere)

    week_dir = fake_repo / "data" / "processed" / "2025" / "week_01"
    week_dir.mkdir(parents=True)
    payload = {
        "game": {
            "id": "x1",
            "season": 2025,
            "week": 1,
            "home_team": "KC",
            "away_team": "BUF",
        }
    }
    json_path = week_dir / "x1.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    entries = list_available_processed_games()
    assert len(entries) == 1
    assert entries[0].matchup_label == "BUF @ KC — 2025 W1"
    assert entries[0].path == json_path.resolve()


def test_print_processed_inventory_summary_finds_indexed_game(tmp_path: Path) -> None:
    root = tmp_path / "processed"
    out = root / "2025" / "week_01"
    out.mkdir(parents=True)
    payload = {
        "game": {
            "id": "demo1",
            "season": 2025,
            "week": 1,
            "home_team": "KC",
            "away_team": "BUF",
        }
    }
    json_path = out / "demo1.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    buf = io.StringIO()
    n = print_processed_inventory_summary(root, file=buf)
    text = buf.getvalue()

    assert n == 1
    assert "Found 1 game(s)" in text
    assert "BUF @ KC — 2025 W1" in text
    assert str(json_path.resolve()) in text

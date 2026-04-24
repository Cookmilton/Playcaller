"""``list_available_processed_games`` uses a bounded read (no full-file JSON parse)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from warehouse import review_loader


def test_index_entry_from_huge_plays_array_uses_prefix_only(tmp_path: Path) -> None:
    """Game metadata sits before plays; plays may be megabytes without affecting indexing."""
    root = tmp_path / "processed" / "2025" / "week_01"
    root.mkdir(parents=True)
    head = {
        "game": {
            "id": "g-huge",
            "season": 2025,
            "week": 1,
            "home_team": "LA",
            "away_team": "HOU",
        },
        "plays": [],
    }
    # One giant string field so ``json.dumps`` stays valid and the file is >> prefix.
    head["plays"] = [{"pad": "x" * 500_000}]
    path = root / "g-huge.json"
    path.write_text(json.dumps(head), encoding="utf-8")

    assert path.stat().st_size > review_loader._INDEX_PREFIX_CHARS
    entries = review_loader.list_available_processed_games(tmp_path / "processed")

    assert len(entries) == 1
    assert entries[0].game_id == "g-huge"
    assert entries[0].matchup_label == "HOU @ LA — 2025 W1"


def test_index_fails_when_game_not_within_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(review_loader, "_INDEX_PREFIX_CHARS", 32)
    root = tmp_path / "processed" / "2025" / "week_01"
    root.mkdir(parents=True)
    payload = {
        "game": {
            "id": "late",
            "season": 2025,
            "week": 2,
            "home_team": "KC",
            "away_team": "BUF",
        }
    }
    path = root / "late.json"
    path.write_text(" " * 2000 + json.dumps(payload), encoding="utf-8")

    assert review_loader.list_available_processed_games(tmp_path / "processed") == []

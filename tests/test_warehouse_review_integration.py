"""Warehouse processed JSON on disk → Review rows (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from playcaller.review.unified_review import ReviewMode, compute_review_summary_metrics, group_unified_rows_by_drive

from warehouse.review_loader import (
    ProcessedGameIndexEntry,
    _WAREHOUSE_COMPARISON_DEFAULT,
    _WAREHOUSE_MODEL_HEADLINE_DEFAULT,
    _WAREHOUSE_MODEL_STRUCTURED_DEFAULT,
    _WAREHOUSE_MODEL_SUBLINE_DEFAULT,
    list_available_processed_games,
    parse_processed_payload,
    warehouse_bundle_from_processed_path,
    warehouse_game_to_review_rows,
)


def _demo_payload() -> dict:
    return {
        "schema_version": "2.0",
        "game": {
            "id": "demo-g1",
            "source": "NFLVERSE",
            "external_game_id": "demo-ext-1",
            "season": 2025,
            "week": 1,
            "game_type": "REG",
            "home_team": "KC",
            "away_team": "BUF",
            "game_date": "2025-09-05",
            "status": "FINAL",
            "final_home_score": 24,
            "final_away_score": 27,
        },
        "plays": [
            {
                "id": "p1",
                "game_id": "demo-g1",
                "external_play_id": "101",
                "play_sequence": 1,
                "quarter": 1,
                "score_offense": 0,
                "score_defense": 0,
                "play_type": "RUN",
                "play_result": "RUSH_GAIN",
                "first_down": True,
                "touchdown": False,
                "turnover": False,
                "raw_description": "Run left for 4 yards.",
                "clock_seconds": 900,
                "possession_team": None,
                "defense_team": None,
                "down": 1,
                "distance": 10,
                "yardline_100": 65,
                "yards_gained": 4,
            },
            {
                "id": "p2",
                "game_id": "demo-g1",
                "external_play_id": "102",
                "play_sequence": 2,
                "quarter": 1,
                "score_offense": 0,
                "score_defense": 0,
                "play_type": "PASS",
                "play_result": "COMPLETE",
                "first_down": True,
                "touchdown": False,
                "turnover": False,
                "raw_description": "Pass complete for 12 yards.",
                "clock_seconds": 860,
                "possession_team": None,
                "defense_team": None,
                "down": 2,
                "distance": 6,
                "yardline_100": 61,
                "yards_gained": 12,
            },
            {
                "id": "p3",
                "game_id": "demo-g1",
                "external_play_id": "103",
                "play_sequence": 3,
                "quarter": 1,
                "score_offense": 0,
                "score_defense": 0,
                "play_type": "PASS",
                "play_result": "TOUCHDOWN_PASS",
                "first_down": False,
                "touchdown": True,
                "turnover": False,
                "raw_description": "Touchdown pass 20 yards.",
                "clock_seconds": 820,
                "possession_team": None,
                "defense_team": None,
                "down": 1,
                "distance": 10,
                "yardline_100": 20,
                "yards_gained": 20,
            },
        ],
        "features": [
            {
                "play_id": "p1",
                "red_zone": False,
                "goal_to_go": False,
                "four_down_territory": False,
                "two_minute": False,
                "score_diff": -3,
                "score_diff_bucket": "trailing_small",
                "field_zone": "mid",
                "distance_bucket": "medium",
                "game_script": "neutral",
                "previous_play_type": None,
                "drive_number": 1,
            },
            {
                "play_id": "p2",
                "red_zone": False,
                "goal_to_go": False,
                "four_down_territory": False,
                "two_minute": False,
                "score_diff": -3,
                "score_diff_bucket": "trailing_small",
                "field_zone": "mid",
                "distance_bucket": "short",
                "game_script": "neutral",
                "previous_play_type": "RUN",
                "drive_number": 1,
            },
            {
                "play_id": "p3",
                "red_zone": True,
                "goal_to_go": False,
                "four_down_territory": False,
                "two_minute": False,
                "score_diff": -3,
                "score_diff_bucket": "trailing_small",
                "field_zone": "opp",
                "distance_bucket": "medium",
                "game_script": "neutral",
                "previous_play_type": "PASS",
                "drive_number": 1,
            },
        ],
    }


def test_warehouse_path_produces_valid_review_rows(tmp_path: Path) -> None:
    payload = _demo_payload()
    out_dir = tmp_path / "data" / "processed" / "2025" / "week_01"
    out_dir.mkdir(parents=True)
    json_path = out_dir / "KC_BUF_demo.json"
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    root = tmp_path / "data" / "processed"
    entries = list_available_processed_games(root)
    assert len(entries) == 1
    ent = entries[0]
    assert isinstance(ent, ProcessedGameIndexEntry)
    assert ent.season == 2025
    assert ent.week == 1
    assert ent.matchup_label == "BUF @ KC — 2025 W1"

    rows = warehouse_game_to_review_rows(ent.path)
    assert len(rows) == 3
    assert [r.actual_headline for r in rows] == [
        "Run left for 4 yards.",
        "Pass complete for 12 yards.",
        "Touchdown pass 20 yards.",
    ]

    for r in rows:
        assert r.review_mode is ReviewMode.WAREHOUSE_HISTORICAL
        assert r.actual_structured.get("play_type")
        assert r.actual_structured.get("result_type")
        assert r.model_headline == _WAREHOUSE_MODEL_HEADLINE_DEFAULT
        assert r.model_subline == _WAREHOUSE_MODEL_SUBLINE_DEFAULT
        assert r.model_structured == _WAREHOUSE_MODEL_STRUCTURED_DEFAULT
        assert r.comparison == _WAREHOUSE_COMPARISON_DEFAULT
        assert r.confidence is None

    game, rows2 = warehouse_bundle_from_processed_path(ent.path)
    assert rows2 == rows
    compute_review_summary_metrics(rows)
    group_unified_rows_by_drive(rows)
    assert len(game.drives) >= 1


def test_parse_processed_payload_plays_features_length_mismatch() -> None:
    payload = _demo_payload()
    payload["features"] = payload["features"][:2]
    with pytest.raises(ValueError, match=r"plays/features length mismatch: 3 plays vs 2 features"):
        parse_processed_payload(payload)


def test_list_available_missing_root_returns_empty() -> None:
    assert list_available_processed_games(Path("/nonexistent/processed/root")) == []


def test_bundle_from_path_missing_file() -> None:
    p = Path("/nonexistent/no_file.json")
    with pytest.raises(FileNotFoundError):
        warehouse_bundle_from_processed_path(p)

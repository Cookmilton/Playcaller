from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import warehouse.bulk as wb
from warehouse.pipeline import IngestionResult


def test_prune_removes_untracked_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    proc = tmp_path / "data" / "processed"
    week_dir = proc / "2025" / "week_01"
    week_dir.mkdir(parents=True)
    for gid in ("aa", "bb", "cc"):
        (week_dir / f"{gid}.json").write_text(
            '{"schema_version":"2.0","game":{"id":"' + gid + '"},"plays":[],"features":[]}'
        )
    (week_dir / "orphan.json").write_text("{}")
    monkeypatch.setattr(wb, "processed_data_dir", lambda: proc)
    wb._prune_orphans_week(2025, 1, {"aa", "bb", "cc"})
    assert not (week_dir / "orphan.json").is_file()
    assert (week_dir / "aa.json").is_file()


def test_prune_skips_when_valid_ids_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    proc = tmp_path / "data" / "processed"
    week_dir = proc / "2025" / "week_01"
    week_dir.mkdir(parents=True)
    (week_dir / "only.json").write_text("{}")
    monkeypatch.setattr(wb, "processed_data_dir", lambda: proc)
    wb._prune_orphans_week(2025, 1, set())
    assert (week_dir / "only.json").is_file()


def test_run_bulk_prune_false_leaves_orphan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    proc = tmp_path / "data" / "processed" / "2025" / "week_99"
    proc.mkdir(parents=True)
    (proc / "keep.json").write_text("{}")
    monkeypatch.setattr(wb, "processed_data_dir", lambda: tmp_path / "data" / "processed")
    mock_run = MagicMock(
        return_value=IngestionResult(
            season=2025,
            week=99,
            games_loaded=0,
            games_failed=0,
            plays_normalized=0,
            validation_issues={},
            quality_issues={},
            failed_game_ids=[],
            elapsed_seconds=0.0,
            processed_paths_written=(),
        )
    )
    monkeypatch.setattr(wb, "run_week_ingestion", mock_run)
    monkeypatch.setattr(wb, "_load_checkpoint", lambda s: None)
    monkeypatch.setattr(wb, "_save_checkpoint", lambda *a, **k: None)
    wb.run_bulk_ingestion(2025, [99], resume=False, force_refresh=True, prune_orphans=False)
    assert (proc / "keep.json").exists()


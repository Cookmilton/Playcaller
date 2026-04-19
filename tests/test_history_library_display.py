"""Tests for History library display helpers (titles, rows, filters)."""

from playcaller.history.ingest import IngestReport
from playcaller.history.library_display import (
    aggregate_ingest_reports,
    build_library_table_row,
    duplicate_hint_for_new_imports,
    filter_game_records,
    human_readable_game_title,
    import_batches_by_id,
    session_game_id_duplicate_repo_ids,
    sort_games_for_library,
)


def test_human_readable_title_team_opponent_date() -> None:
    rec = {
        "team": "Chiefs",
        "opponent": "Chargers",
        "game_date": "2025-09-14T12:00:00",
        "source_filename": "foo.json",
    }
    assert human_readable_game_title(rec) == "2025-09-14 · Chiefs vs Chargers"


def test_human_readable_title_prefers_team_over_filename() -> None:
    rec = {
        "team": "A",
        "opponent": "B",
        "game_date": "",
        "source_filename": "raw_export.json",
    }
    assert human_readable_game_title(rec) == "A vs B"


def test_duplicate_session_ids() -> None:
    games = [
        {"repo_game_id": "1", "session_game_id": "sid"},
        {"repo_game_id": "2", "session_game_id": "sid"},
        {"repo_game_id": "3", "session_game_id": "other"},
    ]
    d = session_game_id_duplicate_repo_ids(games)
    assert d == {"1", "2"}


def test_filter_search() -> None:
    games = [
        {"repo_game_id": "a", "team": "Giants", "opponent": "Rams", "validation_status": "ok"},
        {"repo_game_id": "b", "team": "Bears", "opponent": "Vikings", "validation_status": "warnings"},
    ]
    out = filter_game_records(games, search="giants")
    assert len(out) == 1 and out[0]["repo_game_id"] == "a"
    out2 = filter_game_records(games, validation="warnings")
    assert len(out2) == 1 and out2[0]["repo_game_id"] == "b"


def test_build_library_row() -> None:
    batches = import_batches_by_id(
        {
            "imports": [
                {
                    "import_id": "imp1",
                    "created_at_iso": "2025-01-02T15:04:05+00:00",
                    "source_kind": "upload",
                }
            ]
        }
    )
    rec = {
        "repo_game_id": "full-uuid-here",
        "import_id": "imp1",
        "team": "X",
        "opponent": "Y",
        "game_date": "2025-09-01",
        "season": "2025",
        "roster_id": "v1",
        "play_count": 40,
        "drive_count": 9,
        "offense_points": 21,
        "defense_points": 17,
        "validation_status": "ok",
        "session_is_simulated": False,
        "tags": ["a", "b"],
        "source_filename": "game.json",
        "session_game_id": "dup",
    }
    row = build_library_table_row(rec, batches=batches, duplicate_repo_ids=set())
    assert row["Title"] == "2025-09-01 · X vs Y"
    assert row["Score"] == "21–17"
    assert row["Imported"].startswith("2025-01-02")
    assert row["Batch"].startswith("2025-01-02")


def test_duplicate_hint_for_new_imports() -> None:
    games = [
        {"repo_game_id": "old", "session_game_id": "s1"},
        {"repo_game_id": "new", "session_game_id": "s1"},
    ]
    hint = duplicate_hint_for_new_imports(games, {"new"})
    assert hint and "session id" in hint.lower()


def test_aggregate_ingest_reports() -> None:
    r1 = IngestReport(
        import_id="a",
        created_at_iso="t",
        source_kind="upload",
        label="",
        files_found=2,
        files_imported=2,
        files_rejected=0,
        game_repo_ids=["g1"],
    )
    r2 = IngestReport(
        import_id="b",
        created_at_iso="t",
        source_kind="upload",
        label="",
        files_found=1,
        files_imported=0,
        files_rejected=1,
        rejected=[],
        game_repo_ids=[],
    )
    agg = aggregate_ingest_reports([r1, r2])
    assert agg["files_found"] == 3
    assert agg["files_imported"] == 2
    assert agg["files_rejected"] == 1
    assert agg["game_repo_ids"] == ["g1"]


def test_sort_games_by_title() -> None:
    batches = {}
    games = [
        {"repo_game_id": "1", "team": "B", "opponent": "C", "import_id": ""},
        {"repo_game_id": "2", "team": "A", "opponent": "C", "import_id": ""},
    ]
    s = sort_games_for_library(games, batches=batches, sort_mode="title_asc")
    assert [g["repo_game_id"] for g in s] == ["2", "1"]

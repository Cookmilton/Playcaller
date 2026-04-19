"""History Import tab: last-ingest summary is UI-only session state (dismiss pops key)."""

from __future__ import annotations

from playcaller.history.ingest import IngestReport
from playcaller.history.repository_paths import ensure_repository_layout
from playcaller.ui.history_validation import _SESSION_LAST_INGEST, _store_ingest_summary


def test_last_ingest_summary_store_then_pop_matches_dismiss_contract(tmp_path) -> None:
    root = tmp_path / "repo"
    ensure_repository_layout(root)
    rep = IngestReport(
        import_id="imp-1",
        created_at_iso="2026-01-01T00:00:00+00:00",
        source_kind="upload",
        label="",
        files_found=2,
        files_imported=1,
        files_rejected=1,
        rejected=[],
        warnings=["note"],
        game_repo_ids=["g1"],
    )
    ss: dict = {}
    _store_ingest_summary(ss, [rep], root)
    assert _SESSION_LAST_INGEST in ss
    assert ss[_SESSION_LAST_INGEST]["files_imported"] == 1
    ss.pop(_SESSION_LAST_INGEST, None)
    assert _SESSION_LAST_INGEST not in ss

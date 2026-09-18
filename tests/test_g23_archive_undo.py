"""G2.3 undo stack for manual End-drive and G2.2 auto-close archives.

Derived payloads come from ``tests/fixtures/espn_summary_mnf_401872931.json``
(same DEN INT drive ``4018729311`` as ``tests/test_g22_auto_close.py``).
"""

from __future__ import annotations

from playcaller.domain import ActualPlayResult
from playcaller.live_data.drive_boundaries import PREVIOUS_FEED_DRIVE_OPEN
from playcaller.services.drive_archive import (
    ARCHIVE_KIND_MANUAL,
    archive_open_drive,
    restore_last_drive_archive,
)
from playcaller.streamlit_state.keys import (
    DRIVE_ARCHIVE_UNDO_STACK,
    LIVE_FEED_AUTO_CLOSE_SUPPRESS_KEYS,
    LIVE_FEED_MERGED_ESPN_DRIVE_KEYS,
)
from tests.test_g22_auto_close import (
    DEN_STABLE_KEY,
    _apply,
    _derived_den_completed_new_current,
    _derived_open_den_current,
    _session,
)


def _logger_ids(ss: dict) -> list[str]:
    return [str(p.external_play_id) for p in ss["drive_log"].results if p.external_play_id]


def test_g23_auto_archive_undo_does_not_rearchive_on_next_sync() -> None:
    ss = _session()
    _apply(ss, _derived_open_den_current())
    _apply(ss, _derived_den_completed_new_current())
    assert ss["game"].drives
    assert ss["drive_log"].results == []
    assert restore_last_drive_archive(ss) is True
    assert ss["drive_log"].results
    assert ss["game"].drives == []
    assert DEN_STABLE_KEY in (ss.get(LIVE_FEED_AUTO_CLOSE_SUPPRESS_KEYS) or [])
    assert DEN_STABLE_KEY not in (ss.get(LIVE_FEED_MERGED_ESPN_DRIVE_KEYS) or [])
    r = _apply(ss, _derived_den_completed_new_current())
    assert "auto_closed_leftover_drive" not in r.applied_fields
    assert PREVIOUS_FEED_DRIVE_OPEN in r.skipped_reasons
    assert ss["drive_log"].results
    assert ss["game"].drives == []


def test_g23_manual_archive_undo_restores_logger_exactly() -> None:
    ss = _session()
    _apply(ss, _derived_open_den_current())
    before = list(ss["drive_log"].results)
    before_ids = _logger_ids(ss)
    epoch = int(ss.get("eval_drive_epoch", 0))
    seen = list(ss.get("live_feed_seen_play_ids") or [])
    res = archive_open_drive(ss, kind=ARCHIVE_KIND_MANUAL, update_board=True)
    assert res.archived is not None
    assert ss["drive_log"].results == []
    assert restore_last_drive_archive(ss) is True
    assert _logger_ids(ss) == before_ids
    assert len(ss["drive_log"].results) == len(before)
    assert ss["game"].drives == []
    assert int(ss.get("eval_drive_epoch", 0)) == epoch
    assert list(ss.get("live_feed_seen_play_ids") or []) == seen


def test_g23_stack_mixes_auto_and_manual() -> None:
    ss = _session()
    _apply(ss, _derived_open_den_current())
    auto_ids = _logger_ids(ss)
    _apply(ss, _derived_den_completed_new_current())
    kinds = [e["kind"] for e in (ss.get(DRIVE_ARCHIVE_UNDO_STACK) or [])]
    assert kinds == ["auto"]
    ss["drive_log"].log(
        ActualPlayResult(
            family="inside_zone",
            concept_name="Manual",
            play_type="run",
            result_type="run",
            yards_gained=4,
            description="manual-after-auto",
        )
    )
    archive_open_drive(ss, kind=ARCHIVE_KIND_MANUAL, update_board=True)
    kinds = [e["kind"] for e in (ss.get(DRIVE_ARCHIVE_UNDO_STACK) or [])]
    assert kinds == ["auto", "manual"]
    assert restore_last_drive_archive(ss) is True
    assert [p.description for p in ss["drive_log"].results] == ["manual-after-auto"]
    assert restore_last_drive_archive(ss) is True
    assert _logger_ids(ss) == auto_ids
    assert (ss.get(DRIVE_ARCHIVE_UNDO_STACK) or []) == []

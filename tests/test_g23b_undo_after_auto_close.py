"""Phase 1: undo after auto-close must not lose N+1 plays to stale seen ids.

Derived from ``tests/fixtures/espn_summary_mnf_401872931.json``:
drive N = ``drives.previous[0]`` (DEN INT ``4018729311``);
drive N+1 = ``drives.previous[2]`` (DEN TD ``4018729313``), re-labelled as ``drives.current``.
"""

from __future__ import annotations

import copy
from collections import Counter

from playcaller.live_data.drive_boundaries import PREVIOUS_FEED_DRIVE_OPEN
from playcaller.live_data.espn_play_normalize import espn_play_to_actual, should_skip_espn_play
from playcaller.services.drive_archive import ARCHIVE_KIND_MANUAL, archive_open_drive, restore_last_drive_archive
from playcaller.streamlit_state.keys import (
    LIVE_FEED_AUTO_CLOSE_SUPPRESS_KEYS,
    LIVE_FEED_SEEN_PLAY_IDS,
)
from tests.test_g22_auto_close import (
    DEN_DRIVE_ID,
    DEN_STABLE_KEY,
    _apply,
    _derived_open_den_current,
    _mnf,
    _session,
)

# Source: espn_summary_mnf_401872931.json drives.previous[2]
DEN_N1_DRIVE_ID = "4018729313"


def _mergeable_play_ids(drive: dict) -> list[str]:
    ids: list[str] = []
    for play in drive.get("plays") or []:
        if not isinstance(play, dict) or should_skip_espn_play(play):
            continue
        if espn_play_to_actual(play) is None:
            continue
        pid = str(play.get("id") or "").strip()
        if pid:
            ids.append(pid)
    return ids


def _derived_n_completed_n1_current() -> dict:
    """*_derived_*: N (DEN INT) is completed; N+1 (DEN TD) is ``drives.current``."""
    raw = _mnf()
    den_n = copy.deepcopy(raw["drives"]["previous"][0])
    den_n1 = copy.deepcopy(raw["drives"]["previous"][2])
    out = copy.deepcopy(raw)
    out["drives"]["previous"] = [den_n]
    out["drives"]["current"] = den_n1
    return out


def _all_espn_ids(ss: dict) -> list[str]:
    ids = [str(p.external_play_id) for p in ss["drive_log"].results if p.external_play_id]
    for drive in ss["game"].drives:
        for play in drive.plays or []:
            if play.external_play_id:
                ids.append(str(play.external_play_id))
    return ids


def test_g23b_undo_after_auto_close_then_end_drive_keeps_n1_plays() -> None:
    n_payload = _derived_open_den_current()
    n1_payload = _derived_n_completed_n1_current()
    n_ids = _mergeable_play_ids(n_payload["drives"]["current"])
    n1_ids = _mergeable_play_ids(n1_payload["drives"]["current"])
    assert n_ids
    assert n1_ids
    assert DEN_DRIVE_ID == str(n_payload["drives"]["current"]["id"])
    assert DEN_N1_DRIVE_ID == str(n1_payload["drives"]["current"]["id"])

    ss = _session()

    # 1. Sync A: logger holds drive N.
    _apply(ss, n_payload)
    logger_n = list(ss["drive_log"].results)
    logger_n_ids = [str(p.external_play_id) for p in logger_n if p.external_play_id]
    assert logger_n_ids == n_ids
    assert ss["game"].drives == []

    # 2. Sync B: current = N+1. Auto-close archives N; N+1 merges into the logger.
    r_b = _apply(ss, n1_payload)
    assert "auto_closed_leftover_drive" in r_b.applied_fields, r_b.applied_fields
    assert PREVIOUS_FEED_DRIVE_OPEN not in r_b.skipped_reasons
    assert len(ss["game"].drives) == 1
    archived_n_ids = [str(p.external_play_id) for p in ss["game"].drives[0].plays if p.external_play_id]
    assert archived_n_ids == n_ids
    logger_n1_ids = [str(p.external_play_id) for p in ss["drive_log"].results if p.external_play_id]
    assert logger_n1_ids == n1_ids, (logger_n1_ids, n1_ids, r_b.applied_fields)

    # 3. Undo.
    assert restore_last_drive_archive(ss) is True
    assert ss["game"].drives == []
    undone_ids = [str(p.external_play_id) for p in ss["drive_log"].results if p.external_play_id]
    assert undone_ids == n_ids
    assert len(ss["drive_log"].results) == len(logger_n)
    assert DEN_STABLE_KEY in (ss.get(LIVE_FEED_AUTO_CLOSE_SUPPRESS_KEYS) or [])

    # 4. Sync B again: no re-archive of N; leftover hold.
    r_b2 = _apply(ss, n1_payload)
    assert "auto_closed_leftover_drive" not in r_b2.applied_fields
    assert PREVIOUS_FEED_DRIVE_OPEN in r_b2.skipped_reasons
    assert ss["game"].drives == []
    assert [str(p.external_play_id) for p in ss["drive_log"].results if p.external_play_id] == n_ids

    # 5. Operator End-drive on N.
    res = archive_open_drive(ss, kind=ARCHIVE_KIND_MANUAL, update_board=True)
    assert res.archived is not None
    assert ss["drive_log"].results == []
    assert len(ss["game"].drives) == 1

    # 6. Sync B again.
    r_b3 = _apply(ss, n1_payload)
    logger_final = [str(p.external_play_id) for p in ss["drive_log"].results if p.external_play_id]
    assert logger_final == n1_ids, (
        logger_final,
        n1_ids,
        r_b3.applied_fields,
        ss.get(LIVE_FEED_SEEN_PLAY_IDS),
    )
    all_ids = _all_espn_ids(ss)
    dup = {k: v for k, v in Counter(all_ids).items() if v > 1}
    assert not dup, dup
    n_count = sum(
        1 for d in ss["game"].drives if any(str(p.external_play_id) in n_ids for p in (d.plays or []))
    )
    assert n_count == 1

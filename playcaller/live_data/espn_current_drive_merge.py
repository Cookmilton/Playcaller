"""
Merge ESPN ``drives.current.plays`` into :class:`~playcaller.state.DriveLogger`.

Completed possessions use :mod:`playcaller.live_data.espn_import_merge`; this module
handles the in-progress drive only. Dedup is keyed by ``external_play_id`` (ESPN play id)
plus :data:`~playcaller.streamlit_state.keys.LIVE_FEED_SEEN_PLAY_IDS`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

from playcaller.domain import ActualPlayResult
from playcaller.evaluation.snap_review_lifecycle import close_snap_review_row_with_logged_actual
from playcaller.state import DriveLogger
from playcaller.streamlit_state.keys import LIVE_FEED_SEEN_PLAY_IDS

from .espn_play_normalize import espn_play_to_actual, should_skip_espn_play, validate_actual_for_engine
from .types import FeedCompletedDrive


def _plays_compatible(manual: ActualPlayResult, espn_norm: ActualPlayResult) -> bool:
    """Conservative match for linking a manual row to an ESPN play (no silent overwrites)."""
    if manual.play_type != espn_norm.play_type:
        return False
    if int(manual.yards_gained) != int(espn_norm.yards_gained):
        return False
    if (manual.result_type or "") and (espn_norm.result_type or ""):
        if manual.result_type != espn_norm.result_type:
            return False
    return True


def _normalize_current_row(play: Mapping[str, object]) -> Tuple[str, ActualPlayResult] | None:
    if not isinstance(play, dict):
        return None
    if should_skip_espn_play(play):
        return None
    ap = espn_play_to_actual(play)
    if ap is None:
        return None
    ap = validate_actual_for_engine(ap)
    pid = str(play.get("id") or "").strip()
    if not pid:
        return None
    return pid, replace(ap, external_play_id=pid)


def merge_current_espn_plays_into_drive_log(
    *,
    drive_log: DriveLogger,
    seen_play_ids: Set[str],
    raw_plays: Sequence[Mapping[str, object]],
    debug: List[str],
    snap_review_audit: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """
    Append or link normalized ESPN rows into ``drive_log``.

    - Rows with ESPN ids already in ``seen_play_ids`` are skipped (idempotent re-sync).
    - If the next unmatched manual row (no ``external_play_id``) is compatible with the ESPN
      row, we only set ``external_play_id`` — description / concept stay operator-facing.
    - Otherwise we :meth:`~playcaller.state.DriveLogger.log` the ESPN-normalized row.

    When ``snap_review_audit`` is the game's review list, each **appended** row runs
    :func:`~playcaller.evaluation.snap_review_lifecycle.close_snap_review_row_with_logged_actual` so a prior **Generate**
    open row for this snap closes against the feed actual (same rule as manual logging).

    Returns the number of rows newly linked or appended.
    """
    esp_order: List[Tuple[str, ActualPlayResult]] = []
    for play in raw_plays:
        row = _normalize_current_row(play)
        if row:
            esp_order.append(row)

    if not esp_order:
        return 0

    start_from = 0
    n_ops = 0
    for pid, espn_actual in esp_order:
        if pid in seen_play_ids:
            continue
        linked = False
        for idx in range(start_from, len(drive_log.results)):
            cur = drive_log.results[idx]
            if cur.external_play_id:
                continue
            if _plays_compatible(cur, espn_actual):
                cur.external_play_id = pid
                seen_play_ids.add(pid)
                start_from = idx + 1
                linked = True
                n_ops += 1
                debug.append(f"linked manual play to ESPN id {pid}")
                break
        if linked:
            continue
        drive_log.log(espn_actual)
        seen_play_ids.add(pid)
        start_from = len(drive_log.results)
        n_ops += 1
        debug.append(f"appended ESPN play {pid}")
        if snap_review_audit is not None:
            close_snap_review_row_with_logged_actual(
                snap_review_audit,
                plays_after_log=len(drive_log.results),
                actual=espn_actual,
            )

    return n_ops


def maybe_reset_drive_log_after_completed_import(
    drive_log: DriveLogger,
    imported_batch: Sequence[FeedCompletedDrive],
    session: MutableMapping[str, Any],
) -> bool:
    """
    If exactly one completed drive was imported this sync and its ESPN play ids match the
    in-memory drive log (all feed-tagged rows), clear the log so history lives in ``game.drives``.

    Manual-only rows without ids void the match — the operator keeps the live log.
    """
    if len(imported_batch) != 1:
        return False
    fd = imported_batch[0]
    ids_imp = [p.external_play_id for p in fd.plays if p.external_play_id]
    if not ids_imp:
        return False
    c_imp = Counter(ids_imp)
    c_log = Counter(p.external_play_id for p in drive_log.results if p.external_play_id)
    if c_imp != c_log:
        return False
    drive_log.reset()
    session[LIVE_FEED_SEEN_PLAY_IDS] = []
    return True


def prepare_seen_play_ids_for_feed(
    session: MutableMapping[str, Any],
    *,
    possession_team_id: str | None,
    last_possession_team_id: Any,
    reset_on_possession_change: bool,
) -> Set[str]:
    """Build the working ``seen`` set; optionally clear on possession change (same as auto-append)."""
    seen_list = list(session.get(LIVE_FEED_SEEN_PLAY_IDS) or [])
    seen: Set[str] = set(str(x) for x in seen_list)
    cur_p = possession_team_id
    if reset_on_possession_change and cur_p and last_possession_team_id and str(cur_p) != str(last_possession_team_id):
        seen.clear()
    return seen


def persist_seen_play_ids(session: MutableMapping[str, Any], seen: Set[str]) -> None:
    session[LIVE_FEED_SEEN_PLAY_IDS] = sorted(seen)

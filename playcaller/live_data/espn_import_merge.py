"""
Merge :class:`FeedCompletedDrive` rows into :class:`~playcaller.game.Game` with session dedup.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, List, MutableMapping, Optional, Sequence, Set, Tuple

from playcaller.game import Drive, Game, complete_drive_from_plays
from playcaller.streamlit_state.keys import LIVE_FEED_MERGED_ESPN_DRIVE_KEYS

from .drive_boundaries import (
    PARTIAL_COMPLETED_DRIVE_SKIP_PREFIX,
    completed_drive_fully_represented,
    completed_drive_overlaps_occupied,
    espn_play_ids_from_plays,
    sort_game_drives_by_feed_sequence,
)
from .types import FeedCompletedDrive


def merge_completed_espn_drives_into_game(
    game: Game,
    session: MutableMapping[str, Any],
    drives: Sequence[FeedCompletedDrive],
    *,
    coached_team_id: str,
    feed_team_scope: str = "",
    occupied_play_ids: Optional[Set[str]] = None,
) -> Tuple[int, Tuple[FeedCompletedDrive, ...], Tuple[str, ...]]:
    """
    Append newly seen completed ESPN drives to ``game.drives`` in API order, skipping keys already
    merged. ``drives.previous`` is oldest-first; each sync only appends drives whose stable keys are
    new, so re-sync does not duplicate. Uses ``session[LIVE_FEED_MERGED_ESPN_DRIVE_KEYS]``.

    **Team scope:** ``feed_team_scope`` is accepted for call-site compatibility and sync audit
    logging only. Completed drives are **never** filtered here — the full chronological list lives
    in ``game.drives``; the Previous drives UI uses :func:`playcaller.live_data.drive_display.filter_previous_drive_indices`.

    Drives whose ESPN play ids are **all** already in ``occupied_play_ids`` (DriveLogger
    and/or archived ``game.drives``) are skipped so a coached leftover drive is not copied
    into ``game.drives`` until **End drive**.

    Partial overlap (some but not all ids occupied) is **skipped with a warning** and the
    stable key is left unmerged so the drive imports whole once the logger is archived.
    """
    _ = feed_team_scope  # audit / call-site compatibility only
    if not drives or not str(coached_team_id or "").strip():
        return 0, (), ()

    raw_merged = session.get(LIVE_FEED_MERGED_ESPN_DRIVE_KEYS)
    merged: Set[str] = set(str(x) for x in raw_merged) if isinstance(raw_merged, list) else set()

    occupied: Set[str] = set(occupied_play_ids or ())
    oid = str(coached_team_id).strip()
    batch: List[Drive] = []
    imported_meta: List[FeedCompletedDrive] = []
    warnings: List[str] = []
    for fd in drives:
        if fd.stable_key in merged:
            continue
        if completed_drive_fully_represented(fd, occupied):
            continue
        if completed_drive_overlaps_occupied(fd, occupied):
            ids = espn_play_ids_from_plays(fd.plays)
            missing = len(ids - occupied)
            drive_label = str(fd.stable_key or "").strip() or "(unknown)"
            warnings.append(
                f"{PARTIAL_COMPLETED_DRIVE_SKIP_PREFIX}: id={drive_label} missing_plays={missing}"
            )
            # Leave key unmerged so a later sync imports the whole drive after End drive.
            continue
        possessing = "offense" if fd.team_espn_id == oid else "defense"
        if not fd.plays:
            merged.add(fd.stable_key)
            continue
        finished = complete_drive_from_plays(
            list(fd.plays),
            possessing_team=possessing,
            feed_team_espn_id=fd.team_espn_id,
            feed_team_abbr=fd.team_abbreviation,
            feed_team_display_name=fd.team_display_name,
            feed_audit=fd.feed_audit,
        )
        finished = replace(finished, feed_import_tag="espn")
        batch.append(finished)
        imported_meta.append(fd)
        merged.add(fd.stable_key)

    if batch:
        game.drives = game.drives + batch
        sort_game_drives_by_feed_sequence(game)

    session[LIVE_FEED_MERGED_ESPN_DRIVE_KEYS] = sorted(merged)
    return len(batch), tuple(imported_meta), tuple(warnings)

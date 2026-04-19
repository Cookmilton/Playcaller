"""
Merge :class:`FeedCompletedDrive` rows into :class:`~playcaller.game.Game` with session dedup.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, List, MutableMapping, Sequence, Set, Tuple

from playcaller.game import Drive, Game, complete_drive_from_plays
from playcaller.streamlit_state.keys import LIVE_FEED_MERGED_ESPN_DRIVE_KEYS

from .feed_team_scope import feed_completed_drive_matches_scope, normalize_feed_team_scope
from .types import FeedCompletedDrive


def merge_completed_espn_drives_into_game(
    game: Game,
    session: MutableMapping[str, Any],
    drives: Sequence[FeedCompletedDrive],
    *,
    coached_team_id: str,
    feed_team_scope: str,
) -> Tuple[int, Tuple[FeedCompletedDrive, ...]]:
    """
    Append newly seen completed ESPN drives to ``game.drives`` in API order, skipping keys already
    merged. ``drives.previous`` is oldest-first; each sync only appends drives whose stable keys are
    new, so re-sync does not duplicate. Uses ``session[LIVE_FEED_MERGED_ESPN_DRIVE_KEYS]``.
    """
    if not drives or not str(coached_team_id or "").strip():
        return 0, ()

    scope = normalize_feed_team_scope(feed_team_scope)
    raw_merged = session.get(LIVE_FEED_MERGED_ESPN_DRIVE_KEYS)
    merged: Set[str] = set(str(x) for x in raw_merged) if isinstance(raw_merged, list) else set()

    oid = str(coached_team_id).strip()
    batch: List[Drive] = []
    imported_meta: List[FeedCompletedDrive] = []
    for fd in drives:
        if fd.stable_key in merged:
            continue
        if not feed_completed_drive_matches_scope(fd, scope=scope, coached_team_id=oid):
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
        )
        finished = replace(finished, feed_import_tag="espn")
        batch.append(finished)
        imported_meta.append(fd)
        merged.add(fd.stable_key)

    if batch:
        game.drives = game.drives + batch

    session[LIVE_FEED_MERGED_ESPN_DRIVE_KEYS] = sorted(merged)
    return len(batch), tuple(imported_meta)

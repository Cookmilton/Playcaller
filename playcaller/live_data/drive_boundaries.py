"""
Drive-boundary helpers: ESPN play ids stay unique across DriveLogger and ``game.drives``.

Completed-feed import skips drives whose play ids are already in the live log or an
archived drive. When ``drives.current.id`` moves on while the logger still holds the
previous feed's ids, sync reports that the previous feed drive is still open — it does
not auto-archive (operator **End drive** owns that).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence, Set

from playcaller.game import Game
from playcaller.state import DriveLogger

from .types import FeedCompletedDrive

PREVIOUS_FEED_DRIVE_OPEN = "previous feed drive still open in DriveLogger"


def espn_play_ids_from_plays(plays: Optional[Iterable[Any]]) -> Set[str]:
    out: Set[str] = set()
    for play in plays or []:
        pid = getattr(play, "external_play_id", None)
        if pid:
            out.add(str(pid).strip())
    out.discard("")
    return out


def espn_play_ids_from_archived_drives(game: Game) -> Set[str]:
    out: Set[str] = set()
    for drive in game.drives or []:
        plays = getattr(drive, "plays", None)
        out |= espn_play_ids_from_plays(plays)
    return out


def espn_play_ids_from_raw_feed_plays(raw_plays: Optional[Sequence[Mapping[str, object]]]) -> Set[str]:
    out: Set[str] = set()
    for play in raw_plays or []:
        if not isinstance(play, Mapping):
            continue
        pid = str(play.get("id") or "").strip()
        if pid:
            out.add(pid)
    return out


def occupied_espn_play_ids(game: Game, drive_log: DriveLogger) -> Set[str]:
    return espn_play_ids_from_plays(drive_log.results) | espn_play_ids_from_archived_drives(game)


def drive_log_holds_previous_feed_drive(
    drive_log: DriveLogger,
    current_raw_plays: Optional[Sequence[Mapping[str, object]]],
) -> bool:
    """True when the logger has ESPN ids that are not on the current feed drive."""
    open_ids = espn_play_ids_from_plays(drive_log.results)
    if not open_ids:
        return False
    current_ids = espn_play_ids_from_raw_feed_plays(current_raw_plays)
    return not open_ids <= current_ids


def completed_drive_overlaps_occupied(fd: FeedCompletedDrive, occupied: Set[str]) -> bool:
    ids = espn_play_ids_from_plays(fd.plays)
    return bool(ids and ids & occupied)

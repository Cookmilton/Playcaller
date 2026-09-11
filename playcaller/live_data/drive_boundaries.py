"""
Drive-boundary helpers: ESPN play ids stay unique across DriveLogger and ``game.drives``.

Completed-feed import skips a feed drive only when **every** ESPN play id on that drive
is already in the live log or an archived drive. When ``drives.current.id`` moves on
while the logger still holds the previous feed's ids, sync tops up remaining plays by
id into DriveLogger and reports that the previous feed drive is still open — it does
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
    """True when this completed drive shares any ESPN play id with occupied stores."""
    ids = espn_play_ids_from_plays(fd.plays)
    return bool(ids and ids & occupied)


def completed_drive_fully_represented(fd: FeedCompletedDrive, occupied: Set[str]) -> bool:
    """True when every ESPN play id on the feed drive is already stored."""
    ids = espn_play_ids_from_plays(fd.plays)
    return bool(ids) and ids <= occupied


def matching_completed_drive_for_open_log(
    drive_log: DriveLogger,
    completed: Sequence[FeedCompletedDrive],
) -> Optional[FeedCompletedDrive]:
    """Completed feed drive that overlaps the open logger (largest overlap wins)."""
    open_ids = espn_play_ids_from_plays(drive_log.results)
    if not open_ids:
        return None
    best: Optional[FeedCompletedDrive] = None
    best_n = 0
    for fd in completed or ():
        n = len(open_ids & espn_play_ids_from_plays(fd.plays))
        if n > best_n:
            best = fd
            best_n = n
    return best


def archived_drive_feed_sequence(drive: Any) -> Optional[int]:
    """Sort key: first-play ``sequenceNumber`` when present, else min numeric ESPN play id."""
    plays = getattr(drive, "plays", None) or []
    seqs: list[int] = []
    pids: list[int] = []
    for play in plays:
        raw_seq = getattr(play, "feed_sequence_number", None)
        if raw_seq is None and isinstance(play, Mapping):
            raw_seq = play.get("sequenceNumber") or play.get("feed_sequence_number")
        if raw_seq is not None:
            try:
                seqs.append(int(str(raw_seq).strip()))
            except (TypeError, ValueError):
                pass
        pid = str(getattr(play, "external_play_id", None) or "").strip()
        if pid.isdigit():
            pids.append(int(pid))
    if seqs:
        return min(seqs)
    if pids:
        return min(pids)
    return None


def sort_game_drives_by_feed_sequence(game: Game) -> None:
    """Order ``game.drives`` by ESPN sequence, not insertion time. Manual drives keep relative order after ESPN rows."""
    indexed = list(enumerate(game.drives or []))
    if not indexed:
        return

    def _key(item: tuple[int, Any]) -> tuple[int, int, int]:
        i, dr = item
        seq = archived_drive_feed_sequence(dr)
        if seq is None:
            return (1, i, i)
        return (0, seq, i)

    game.drives = [dr for _, dr in sorted(indexed, key=_key)]

"""
Drive-boundary helpers: ESPN play ids stay unique across DriveLogger and ``game.drives``.

Completed-feed import skips a feed drive only when **every** ESPN play id on that drive
is already in the live log or an archived drive. When ``drives.current.id`` moves on
while the logger still holds the previous feed's ids, sync reports
``PREVIOUS_FEED_DRIVE_OPEN``. G2.2 auto-close may then archive through the shared
End-drive path when the leftover appears in ESPN completed drives with a result;
otherwise the hold stays and the tail is topped up in DriveLogger.
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
    *,
    current_feed_drive_id: Optional[str] = None,
    last_feed_drive_id: Optional[str] = None,
) -> bool:
    """
    True when the live logger still belongs to a prior feed drive.

    Fires whenever the logger is non-empty and ``drives.current.id`` has changed
    since the last sync — including manual-only rows with no ESPN play ids.
    Falls back to the ESPN play-id subset check when drive ids are unavailable.
    """
    if not drive_log.results:
        return False
    cur = str(current_feed_drive_id or "").strip()
    last = str(last_feed_drive_id or "").strip()
    if cur and last and cur != last:
        return True
    open_ids = espn_play_ids_from_plays(drive_log.results)
    if not open_ids:
        return False
    current_ids = espn_play_ids_from_raw_feed_plays(current_raw_plays)
    return not open_ids <= current_ids


PARTIAL_COMPLETED_DRIVE_SKIP_PREFIX = "partial completed feed drive skipped"


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


def parse_espn_sequence_number(raw: Any) -> Optional[int]:
    """ESPN ``plays[].sequenceNumber`` as int, or None when missing/unparseable (never raises)."""
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def archived_drive_identity_key(drive: Any) -> str:
    """Stable cache/review key: first ESPN play id, else session epoch, else object id."""
    ids = espn_play_ids_from_plays(getattr(drive, "plays", None))
    if ids:
        return "espnplay:" + min(ids)
    epoch = getattr(drive, "session_drive_epoch", None)
    if epoch is not None:
        return f"epoch:{int(epoch)}"
    return f"obj:{id(drive)}"


def archived_drive_feed_sequence(drive: Any) -> Optional[int]:
    """
    First-known ESPN ``sequenceNumber`` on the drive.

    Manual drives (no sequence on any play) return ``None`` so the sort keeps their
    list slot while ESPN-keyed neighbors permute among ESPN slots. Play ids are not
    used — they are not sequence numbers and must not invent an order.
    """
    plays = getattr(drive, "plays", None) or []
    seqs: list[int] = []
    for play in plays:
        raw_seq = getattr(play, "feed_sequence_number", None)
        if raw_seq is None and isinstance(play, Mapping):
            raw_seq = play.get("sequenceNumber") or play.get("feed_sequence_number")
        parsed = parse_espn_sequence_number(raw_seq)
        if parsed is not None:
            seqs.append(parsed)
    if seqs:
        return min(seqs)
    return None


def sort_game_drives_by_feed_sequence(game: Game) -> None:
    """
    Order ESPN-keyed drives in ``game.drives`` by ``sequenceNumber``.

    Drives with no sequence (manual / operator-only) keep their current list slots.
    ESPN drives are a stable sort among those slots: ``(sequenceNumber, original index)``.
    ``None`` is never compared, so the sort cannot TypeError.
    """
    drives = list(game.drives or [])
    if not drives:
        return
    seqs = [archived_drive_feed_sequence(dr) for dr in drives]
    espn_slots = [i for i, seq in enumerate(seqs) if seq is not None]
    if not espn_slots:
        return
    espn_order = sorted(espn_slots, key=lambda i: (seqs[i], i))
    out = list(drives)
    for slot, src in zip(espn_slots, espn_order):
        out[slot] = drives[src]
    game.drives = out

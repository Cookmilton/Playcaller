"""Ordered ESPN play dicts for one feed drive id (current or previous)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .drive_boundaries import parse_espn_sequence_number


def _drive_blocks(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    drives = payload.get("drives")
    if not isinstance(drives, Mapping):
        return []
    out: list[dict[str, Any]] = []
    current = drives.get("current")
    if isinstance(current, dict):
        out.append(current)
    previous = drives.get("previous")
    if isinstance(previous, list):
        out.extend(block for block in previous if isinstance(block, dict))
    return out


def _ordered_play_dicts(plays: Any) -> list[dict[str, Any]]:
    rows = [dict(p) for p in (plays or []) if isinstance(p, dict)]
    indexed = list(enumerate(rows))

    def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int]:
        i, play = item
        seq = parse_espn_sequence_number(play.get("sequenceNumber"))
        if seq is None:
            return (1, i, 0)
        return (0, seq, i)

    indexed.sort(key=sort_key)
    return [play for _, play in indexed]


def feed_drive_plays(payload: Mapping[str, Any], drive_id: str) -> list[dict[str, Any]]:
    """
    ESPN play dicts for ``drive_id``, in ``sequenceNumber`` order.

    Looks up ``drives.current`` first, then ``drives.previous``. Missing id or payload
    returns an empty list (honest empty — never invents plays).
    """
    did = str(drive_id or "").strip()
    if not did:
        return []
    for block in _drive_blocks(payload):
        if str(block.get("id") or "").strip() == did:
            return _ordered_play_dicts(block.get("plays"))
    return []


def feed_drive_id_from_block(block: Mapping[str, Any] | None) -> str:
    if not isinstance(block, Mapping):
        return ""
    return str(block.get("id") or "").strip()


__all__ = ["feed_drive_plays", "feed_drive_id_from_block"]

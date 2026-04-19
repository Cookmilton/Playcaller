"""
Extract completed drives from ESPN summary ``drives.previous`` for import into ``Game.drives``.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Tuple

from playcaller.domain import ActualPlayResult

from .espn_play_normalize import espn_play_to_actual, validate_actual_for_engine
from .espn_summary_teams import team_label_pair, team_labels_from_espn_summary
from .types import FeedCompletedDrive


def _stable_drive_key(event_id: str, drive: Dict[str, Any], fallback_index: int) -> str:
    did = str(drive.get("id") or "").strip()
    if did:
        return f"{event_id}|drive:{did}"
    team = drive.get("team") if isinstance(drive.get("team"), dict) else {}
    tid = str(team.get("id") or "")
    plays = drive.get("plays") or []
    first_pid = ""
    if plays and isinstance(plays[0], dict):
        first_pid = str(plays[0].get("id") or "")
    last_pid = ""
    if plays and isinstance(plays[-1], dict):
        last_pid = str(plays[-1].get("id") or "")
    return f"{event_id}|idx:{fallback_index}|team:{tid}|{first_pid}-{last_pid}"


def _drive_team_id(drive: Dict[str, Any]) -> str:
    team = drive.get("team") if isinstance(drive.get("team"), dict) else {}
    return str(team.get("id") or "")


def extract_completed_drives_from_espn_payload(
    payload: Dict[str, Any],
    *,
    event_id: str,
) -> Tuple[FeedCompletedDrive, ...]:
    """
    Parse ``drives.previous`` into :class:`FeedCompletedDrive` rows in API order (oldest first).

    ESPN typically lists earlier possessions first; we preserve that order so ``Game.drives``
    reads chronologically before any manually archived drives that were already present.
    """
    drives_block = payload.get("drives")
    if not isinstance(drives_block, dict):
        return ()
    prev = drives_block.get("previous")
    if not isinstance(prev, list):
        return ()

    team_labels = team_labels_from_espn_summary(payload)
    out: List[FeedCompletedDrive] = []
    for i, raw in enumerate(prev):
        if not isinstance(raw, dict):
            continue
        plays_raw = raw.get("plays") or []
        normalized: List[ActualPlayResult] = []
        for pr in plays_raw:
            if not isinstance(pr, dict):
                continue
            ap = espn_play_to_actual(pr)
            if ap is None:
                continue
            ap = validate_actual_for_engine(ap)
            pid = str(pr.get("id") or "").strip()
            if pid:
                ap = replace(ap, external_play_id=pid)
            normalized.append(ap)
        key = _stable_drive_key(event_id, raw, i)
        tid = _drive_team_id(raw)
        abbr, disp = team_label_pair(team_labels, tid)
        out.append(
            FeedCompletedDrive(
                stable_key=key,
                team_espn_id=tid,
                plays=tuple(normalized),
                team_abbreviation=abbr,
                team_display_name=disp,
            )
        )

    return tuple(out)

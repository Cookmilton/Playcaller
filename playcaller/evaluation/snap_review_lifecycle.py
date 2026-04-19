"""
First-class **snap review** lifecycle: one dict row per Generate → optional close on Log.

Rows live on ``Game.recommendation_audit`` (same list as JSON ``snap_review_log``).
This module is the **only** place that should orchestrate open/close/supersede/trim for that list from app events; low-level dict shaping stays in :mod:`playcaller.evaluation.audit`.

Matching rules (Log / feed append)
---------------------------------
* ``plays_at_recommend`` is ``len(drive_log.results)`` at **Generate** time.
* After ``drive_log.log(actual)``, ``plays_after_log == len(drive_log.results)``.
* **Close** the **most recent** row (reverse list order) with ``status == "open"`` and
  ``plays_at_recommend == plays_after_log - 1``.
* That ties one recommendation to the play that was just logged (1:1 for that snap).

Repeated Generate before Log
----------------------------
* Same ``(drive_epoch, plays_at_recommend)``: earlier **open** rows are marked
  ``status == "superseded"``; the newest row stays **open** (see ``supersede_open_audits_for_snap``).

Undo last play
--------------
* Most recent **closed** row → ``void_undone``; ``linked_actual`` cleared.
* Trailing **open** rows with ``plays_at_recommend`` greater than the current
  play count are dropped (``trim_stale_open_audits``).

End drive / new series
----------------------
* After the live ``drive_log`` is reset, call ``trim_snap_review_opens_for_play_count``
  with ``plays_on_drive=0`` so opens tied to the previous drive’s play index do not linger.

Live feed
---------
* Each **appended** feed play uses the same close rule as manual log; dedup / manual link
  paths avoid double-closing.

This data is **historical only** — not an input to recommendation scoring.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, TypedDict

from playcaller.domain import ActualPlayResult
from playcaller.game import Game
from playcaller.state import DriveLogger

from .audit import (
    append_open_audit,
    audit_record_from_recommendation,
    link_open_audit_to_actual,
    next_review_ordinal,
    supersede_open_audits_for_snap,
    trim_stale_open_audits,
    void_last_closed_audit,
)
from .snap_review_logging import log_after_generate, log_after_log_result

# --- Row shape (documentation; stored rows are plain dicts for JSON) ------------


class SnapReviewRowDict(TypedDict, total=False):
    """Expected keys on snap review rows (v1+). Omitted keys may exist on older exports."""

    review_record_version: int
    review_ordinal: int
    row_id: str
    snap_id: str
    session_game_id: str
    ts: float
    game_id: str
    drive_epoch: int
    plays_at_recommend: int
    status: str
    pre_snap: Dict[str, Any]
    team_possession: str
    scoreboard_at_generate: Dict[str, Any]
    session_context: Dict[str, Any]
    selected_family: str
    selected_play_name: str
    bucket: str
    top_families: List[Dict[str, Any]]
    model: Dict[str, Any]
    fourth_down_recommendation: Any
    linked_actual: Dict[str, Any]
    superseded_reason: str


STATUS_OPEN = "open"
STATUS_CLOSED = "closed"
STATUS_SUPERSEDED = "superseded"
STATUS_VOID_UNDONE = "void_undone"


def ensure_snap_review_list_on_game(game: Game) -> None:
    """Guarantee ``recommendation_audit`` / ``snap_review_log`` is a mutable list (session or import edge cases)."""
    raw = getattr(game, "recommendation_audit", None)
    if not isinstance(raw, list):
        game.recommendation_audit = []


def scoreboard_snapshot_from_game(game: Game) -> Dict[str, Any]:
    """Scoreboard + clock from ``Game`` at Generate time (alongside ``pre_snap``)."""
    return {
        "offense_points": int(game.offense_points),
        "defense_points": int(game.defense_points),
        "quarter": int(game.quarter),
        "clock_seconds_remaining": game.clock_seconds_remaining,
    }


def record_open_snap_review_row_after_generate(
    *,
    rows: List[Dict[str, Any]],
    game: Game,
    drive_log: DriveLogger,
    recommend_result: Dict[str, Any],
    eval_drive_epoch: int,
    session_context: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """
    After a successful ``recommend()``: supersede prior opens for this snap, append a new open row.

    Mutates ``rows`` in place (same list as ``game.recommendation_audit`` / export ``snap_review_log``).
    Returns the new row dict.
    """
    ensure_snap_review_list_on_game(game)
    pat = len(drive_log.results)
    de = int(eval_drive_epoch)
    supersede_open_audits_for_snap(rows, drive_epoch=de, plays_at_recommend=pat)
    ord_n = next_review_ordinal(rows)
    rec = audit_record_from_recommendation(
        result=recommend_result,
        plays_at_recommend=pat,
        drive_epoch=de,
        game_id=game.game_id,
        session_context=session_context,
        review_ordinal=ord_n,
        team_possession=game.possession,
        scoreboard_at_generate=scoreboard_snapshot_from_game(game),
    )
    append_open_audit(rows, rec)
    log_after_generate(row_count=len(rows), snap_id=str(rec.get("snap_id") or ""))
    return rec


def close_snap_review_row_with_logged_actual(
    snap_review_log: List[Dict[str, Any]],
    *,
    plays_after_log: int,
    actual: ActualPlayResult,
) -> bool:
    """
    After ``drive_log.log(actual)`` with ``plays_after_log == len(drive_log.results)``.

    See module docstring for matching rule. Returns whether a row was closed.
    """
    row = link_open_audit_to_actual(
        snap_review_log,
        plays_after_log=plays_after_log,
        actual=actual,
    )
    log_after_log_result(row=row)
    return row is not None


def apply_undo_last_logged_play_to_snap_review(
    snap_review_log: List[Dict[str, Any]],
    *,
    plays_on_drive_after_undo: int,
) -> None:
    """Undo pipeline: void last closed row; drop stale trailing opens."""
    void_last_closed_audit(snap_review_log)
    trim_stale_open_audits(snap_review_log, plays_on_drive_after_undo)


def trim_snap_review_opens_for_play_count(
    snap_review_log: List[Dict[str, Any]],
    *,
    plays_on_drive: int,
) -> None:
    """Drop trailing open rows that no longer match the live drive log (end drive, sync tail, undo)."""
    trim_stale_open_audits(snap_review_log, plays_on_drive)

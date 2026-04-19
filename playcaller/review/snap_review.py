"""
Formal **snap review** records for play-by-play session review.

Storage: the canonical list on :class:`~playcaller.game.Game` remains
``recommendation_audit`` (in-memory; JSON **primary** key ``snap_review_log``).
Orchestration: :mod:`~playcaller.evaluation.snap_review_lifecycle` (Generate / Log / undo / trim);
dict shaping: :func:`~playcaller.evaluation.audit.audit_record_from_recommendation` and
:func:`~playcaller.evaluation.audit.link_open_audit_to_actual`.

Exports write ``snap_review_log`` first, then legacy ``recommendation_audit`` (same list).

**Row schema (v1)** — keys commonly present on new rows:

- ``review_record_version`` (int): ``1`` for rows created after this pipeline change; older exports omit it.
- ``review_ordinal`` (int): monotonic per saved game (stable ordering with ``ts``).
- ``session_game_id`` (str): copy of ``session_metadata.session_game_id`` when available.
- ``row_id`` (str): stable hex id for the row (new exports); ``snap_id`` is the first 12 chars (legacy/display).
- ``game_id`` (str): :attr:`~playcaller.game.Game.game_id`.
- ``drive_epoch`` (int): session drive counter (increments on archived drive).
- ``plays_at_recommend`` (int): ``len(drive_log.results)`` at **Generate** time.
- ``status``: ``open`` | ``closed`` | ``void_undone`` | ``superseded``.
- ``pre_snap``: full :class:`~playcaller.domain.GameContext` as dict (quarter, clock, down, distance, field, scoreboard context, etc.).
- ``situation``: compact dict (down, distance, yardline, territory, quarter, clock, scores, score_diff) at **Generate** time.
- ``model_recommendation``: ``play_call``, ``family``, ``tags``, ``confidence``, model name/version (audit-facing summary).
- ``team_possession`` (optional str): ``offense`` / ``defense`` from :class:`~playcaller.game.Game` at **Generate** time (not duplicated inside ``pre_snap``).
- Model call: ``selected_family``, ``selected_play_name``, ``top_families``, ``bucket``, ``model``, ``fourth_down_recommendation``, optional influence fields.
- ``linked_actual``: full :class:`~playcaller.domain.ActualPlayResult` as dict when the operator logged a result for this snap.
- ``actual_result``: compact outcome dict (play_type, yards, result_type, TD/TO flags, etc.) when **completed**.
- ``completed`` (bool): ``True`` when ``actual_result`` / ``linked_actual`` are set (``status == "closed"``).
- ``session_context``: slim session metadata snapshot (see ``session_game_metadata.audit_context_from_game_metadata``).

Rows with ``status == "superseded"`` are replaced by a later **Generate** on the same
``(drive_epoch, plays_at_recommend)``; they are omitted from review timelines and metrics.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

SNAP_REVIEW_RECORD_VERSION = 1
"""Version baked into each new audit row under ``review_record_version``."""

SNAP_REVIEW_LOG_EXPORT_KEY = "snap_review_log"
"""Primary JSON key for the snap review list (``recommendation_audit`` mirrors the same data)."""


def snap_review_rows_from_export(data: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """
    Load review rows from a raw game JSON dict.

    Prefers ``snap_review_log`` when non-empty; otherwise ``recommendation_audit``.
    """
    raw_snap = data.get(SNAP_REVIEW_LOG_EXPORT_KEY)
    raw_legacy = data.get("recommendation_audit")
    if isinstance(raw_snap, list) and len(raw_snap) > 0:
        return [dict(x) if isinstance(x, dict) else {} for x in raw_snap]
    if isinstance(raw_legacy, list):
        return [dict(x) if isinstance(x, dict) else {} for x in raw_legacy]
    return []


def review_timeline_rows(records: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """
    Rows suitable for snap-by-snap Review UI: drop superseded recommendations.

    ``void_undone`` rows remain visible so operators can see undo artifacts if present.
    """
    out: List[Dict[str, Any]] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        if r.get("status") == "superseded":
            continue
        out.append(dict(r))
    return out

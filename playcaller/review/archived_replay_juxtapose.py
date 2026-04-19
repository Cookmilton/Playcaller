"""
Align **snap_review_log** (Generate-time) rows with **retroactive** replay rows for one archived drive.

``play_index`` on :class:`~playcaller.replay.analysis_types.ActualVsReplayComparisonRow` lines up with
``plays_at_recommend + 1`` on audit rows for the same ``drive_epoch``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence

from playcaller.domain import GameContext
from playcaller.game import Game
from playcaller.game_situation_input import context_quarter_from_period, score_diff_from_board
from playcaller.replay.analysis_types import ActualVsReplayComparisonRow
from playcaller.streamlit_state.keys import (
    GAME_CLOCK_TOTAL_SECONDS,
    GAME_CONTEXT_QUARTER,
    GAME_SCORE_OURS,
    GAME_SCORE_THEIRS,
)


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def play_index_from_audit_row(row: Mapping[str, Any]) -> Optional[int]:
    """
    Map an audit row to archived play ordinal (1-based), matching replay ``play_index``.

    At **Generate** time, ``plays_at_recommend`` is ``len(drive_log.results)`` — i.e. plays already
    logged before that snap. The snap is for the *next* play: index ``plays_at_recommend + 1``.
    """
    if "plays_at_recommend" not in row or row.get("plays_at_recommend") is None:
        return None
    pat = _safe_int(row.get("plays_at_recommend"), -999)
    if pat < 0:
        return None
    return pat + 1


def audit_rows_for_drive_epoch(
    audit: Sequence[Mapping[str, Any]],
    drive_epoch: int,
) -> List[Dict[str, Any]]:
    """Timeline-order audit rows for one ``drive_epoch`` (same order as ``audit``)."""
    de = int(drive_epoch)
    return [dict(r) for r in audit if _safe_int(r.get("drive_epoch"), -1) == de]


def build_ambient_context_for_model_replay(
    ss: MutableMapping[str, Any],
    game: Game,
) -> GameContext:
    """
    Console overlay for retroactive replay: defensive read, weather, clock — same idea as main console.

    Situation fields (down/distance/field) are **not** used for replay chain logic; replay rebuilds those
    from the archived play list. ``plays_this_drive`` is zeroed so we do not leak the live drive logger.
    """
    down = _safe_int(ss.get("ui_down"), 1)
    distance = _safe_int(ss.get("ui_distance"), 10)
    territory = str(ss.get("ui_territory", "own"))
    yardline = _safe_int(ss.get("ui_yardline"), 25)
    def_personnel = str(ss.get("ui_def_personnel", ""))
    box_count = _safe_int(ss.get("ui_box_count"), 7)
    coverage_shell = str(ss.get("ui_coverage_shell", ""))
    safeties = str(ss.get("ui_safeties", ""))
    blitz_likely = bool(ss.get("ui_blitz_likely", False))
    period = _safe_int(ss.get("ui_game_period", 1), 1)
    quarter = _safe_int(
        ss.get(GAME_CONTEXT_QUARTER, context_quarter_from_period(period)),
        1,
    )
    seconds_remaining = _safe_int(ss.get(GAME_CLOCK_TOTAL_SECONDS, 0), 0)
    offense_points = _safe_int(ss.get(GAME_SCORE_OURS, getattr(game, "offense_points", 0)), 0)
    defense_points = _safe_int(ss.get(GAME_SCORE_THEIRS, getattr(game, "defense_points", 0)), 0)
    score_diff = score_diff_from_board(our_score=offense_points, their_score=defense_points)
    own_timeouts = _safe_int(ss.get("ui_own_tos", 3), 3)
    opp_timeouts = _safe_int(ss.get("ui_opp_tos", 3), 3)
    weather = str(ss.get("ui_weather", "clear"))
    wind_mph = _safe_int(ss.get("ui_wind_mph", 0), 0) if weather == "wind" else 0
    qb_limited = bool(ss.get("ui_qb_limited", False))
    game_mode = str(ss.get("ui_game_mode", "normal"))
    mismatch = str(ss.get("ui_mismatch", "") or "")

    return GameContext(
        down=down,
        distance=distance,
        yardline=yardline,
        territory=territory,
        def_personnel=def_personnel,
        box_count=box_count,
        coverage_shell=coverage_shell,
        blitz_likely=blitz_likely,
        safeties=safeties,
        score_diff=score_diff,
        quarter=quarter,
        seconds_remaining=seconds_remaining,
        own_timeouts=own_timeouts,
        opp_timeouts=opp_timeouts,
        weather=weather,
        wind_mph=wind_mph,
        qb_limited=qb_limited,
        mismatch=mismatch or None,
        game_mode=game_mode,
        plays_this_drive=0,
        shown_concepts=[],
        run_plays_this_drive=0,
    )


def juxtapose_snap_review_and_replay(
    audit_rows_for_drive: Sequence[Mapping[str, Any]],
    replay_rows: Sequence[ActualVsReplayComparisonRow],
) -> List[Dict[str, Any]]:
    """
    One entry per Generate-time row on this drive, plus aligned ``retroactive_model_replay`` when ``play_index`` matches.
    """
    by_play: Dict[int, Dict[str, Any]] = {r.play_index: r.to_dict() for r in replay_rows}
    out: List[Dict[str, Any]] = []
    for row in audit_rows_for_drive:
        pi = play_index_from_audit_row(row)
        out.append(
            {
                "play_index": pi,
                "snap_review_log_row": dict(row),
                "retroactive_model_replay": by_play.get(pi) if pi is not None else None,
            }
        )
    return out


def drive_epochs_eligible_for_replay_compare(
    game: Game,
    audit: Sequence[Mapping[str, Any]],
) -> List[int]:
    """Drive indices that have archived plays and at least one snap-review row for that epoch."""
    drives = game.drives or []
    epochs_with_audit: set[int] = set()
    for r in audit:
        if not isinstance(r, Mapping):
            continue
        e = _safe_int(r.get("drive_epoch"), -1)
        if e >= 0:
            epochs_with_audit.add(e)
    out: List[int] = []
    for i, dr in enumerate(drives):
        if not getattr(dr, "plays", None):
            continue
        if i in epochs_with_audit:
            out.append(i)
    return out

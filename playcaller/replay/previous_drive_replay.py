"""
Reconstruct pre-snap situations from archived drive plays and run **current-model** replay.

This is a **retroactive replay** for UI and analysis helpers. It is not a log of what the
model said at game time, and must not be written to exports or snap review.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from playcaller import ActualPlayResult, FootballPlayPredictor, Game, GameContext
from playcaller.actual_result import (
    actual_play_structured_dict,
    format_actual_play_operator_detail,
    format_actual_play_operator_headline,
)
from playcaller.game import Drive
from playcaller.situation import advance_game_state_after_actual
from playcaller.state import DriveLogger

from .analysis_types import ActualVsReplayComparisonRow, PreSnapContextRecord
from .comparison import (
    actual_run_pass_bucket,
    family_match_actual_vs_replay,
    model_replay_one_line,
    model_replay_structured_from_recommend,
    pre_snap_record_from_context,
)
from .replay_taxonomy import actual_play_summary_bucket, coarse_bucket_alignment

DEFAULT_START_TERRITORY = "own"
DEFAULT_START_YARDLINE = 25
DEFAULT_START_DOWN = 1
DEFAULT_START_DISTANCE = 10

REPLAY_UNAVAILABLE = "Prediction unavailable"

# Session-state cache for ``cached_comparison_rows_for_archived_drive`` — FIFO prune bound.
_MAX_ARCHIVED_DRIVE_COMPARISON_CACHE_ENTRIES = 48

ANCHOR_CANDIDATES: Tuple[Tuple[str, int, int, int, str], ...] = (
    ("own", 25, 1, 10, "touchback_own_25"),
    ("own", 20, 1, 10, "touchback_own_20"),
    ("own", 30, 1, 10, "touchback_own_30"),
    ("own", 35, 1, 10, "touchback_own_35"),
)

OVERLAY_NOTE = (
    "Defense, weather, and clock use the **current console** as an overlay — not per-snap history."
)


def score_diff_for_archived_possession(game: Game, possessing_team: str) -> int:
    """
    ``GameContext.score_diff`` is positive when **our** team is ahead.

    When the opponent had the ball (``possessing_team == "defense"``), flip sign so
    script heuristics match the team that was actually on offense for this drive.
    """
    ours = int(game.offense_points)
    theirs = int(game.defense_points)
    base = ours - theirs
    pt = str(possessing_team or "offense").strip().lower()
    if pt == "defense":
        return -base
    return base


def presnap_chain_for_drive_plays(
    plays: Sequence[ActualPlayResult],
    *,
    start_territory: str = DEFAULT_START_TERRITORY,
    start_yardline: int = DEFAULT_START_YARDLINE,
    start_down: int = DEFAULT_START_DOWN,
    start_distance: int = DEFAULT_START_DISTANCE,
) -> Tuple[List[Tuple[str, int, int, int]], Optional[str]]:
    if not plays:
        return [], None

    t = start_territory if start_territory in ("own", "opponents") else DEFAULT_START_TERRITORY
    y = max(1, min(50, int(start_yardline)))
    d = max(1, min(4, int(start_down)))
    dist = max(1, min(25, int(start_distance)))

    out: List[Tuple[str, int, int, int]] = []
    err: Optional[str] = None

    for i, play in enumerate(plays):
        out.append((t, y, d, dist))
        try:
            snap = advance_game_state_after_actual(
                territory=t,
                yardline=y,
                down=d,
                distance=dist,
                actual=play,
            )
        except Exception:
            return out, "situation_advance_failed"

        if snap.touchdown and i < len(plays) - 1:
            err = "touchdown_mid_drive"
            break

        if snap.touchdown:
            t, y, d, dist = (
                DEFAULT_START_TERRITORY,
                DEFAULT_START_YARDLINE,
                DEFAULT_START_DOWN,
                DEFAULT_START_DISTANCE,
            )
        else:
            t, y, d, dist = snap.territory, int(snap.yardline), int(snap.down), int(snap.distance)

    return out, err


def _chain_rank(err: Optional[str]) -> int:
    if err is None:
        return 0
    if err == "touchdown_mid_drive":
        return 1
    return 2


def best_presnap_chain_for_drive_plays(
    plays: Sequence[ActualPlayResult],
) -> Tuple[List[Tuple[str, int, int, int]], Optional[str], str]:
    """
    Try several touchback-style anchors; prefer the chain with the fewest progression errors.

    Returns ``(chain, error, anchor_tag)``.
    """
    plist = list(plays)
    if not plist:
        return [], None, "empty"

    best: Optional[Tuple[List[Tuple[str, int, int, int]], Optional[str], str]] = None
    best_key: Optional[Tuple[int, int, str]] = None

    for terr, yl, dn, dst, tag in ANCHOR_CANDIDATES:
        chain, err = presnap_chain_for_drive_plays(
            plist,
            start_territory=terr,
            start_yardline=yl,
            start_down=dn,
            start_distance=dst,
        )
        key = (_chain_rank(err), 0 if "25" in tag else 1, tag)
        if best_key is None or key < best_key:
            best_key = key
            best = (chain, err, tag)

    assert best is not None
    chain, err, tag = best
    if _chain_rank(err) == 2 and not chain:
        chain, err = presnap_chain_for_drive_plays(plist)
        tag = "touchback_own_25_fallback"
    return chain, err, tag


def _run_plays_in_prefix(plays: Sequence[ActualPlayResult]) -> int:
    from playcaller.domain import PASS_FAMILIES, RUN_FAMILIES

    n = 0
    for p in plays:
        fam = str(p.family or "")
        if fam in RUN_FAMILIES:
            n += 1
        elif fam in PASS_FAMILIES:
            continue
        elif str(p.play_type or "").lower() == "run":
            n += 1
    return n


def _shown_concepts_from_prefix(plays: Sequence[ActualPlayResult]) -> List[str]:
    seen: List[str] = []
    for p in plays:
        fam = str(p.family or "")
        if fam and fam not in seen:
            seen.append(fam)
    return seen


def _drive_logger_prefix(plays: Sequence[ActualPlayResult], prefix_len: int) -> DriveLogger:
    dl = DriveLogger()
    for p in plays[:prefix_len]:
        dl.log(p)
    return dl


def build_replay_game_context(
    *,
    ambient: GameContext,
    territory: str,
    yardline: int,
    down: int,
    distance: int,
    drive_log: DriveLogger,
    score_diff: int,
) -> GameContext:
    return replace(
        ambient,
        territory=territory,
        yardline=int(yardline),
        down=int(down),
        distance=int(distance),
        score_diff=int(score_diff),
        plays_this_drive=len(drive_log.results),
        run_plays_this_drive=_run_plays_in_prefix(drive_log.results),
        shown_concepts=_shown_concepts_from_prefix(drive_log.results),
    )


def _fallback_pre_snap(
    *,
    ambient_ctx: GameContext,
    score_diff: int,
    anchor_tag: str,
    recon_notes: str,
    play_idx0: int,
    chain: List[Tuple[str, int, int, int]],
) -> PreSnapContextRecord:
    if play_idx0 < len(chain):
        t, y, d, dist = chain[play_idx0]
    else:
        t, y, d, dist = (
            DEFAULT_START_TERRITORY,
            DEFAULT_START_YARDLINE,
            DEFAULT_START_DOWN,
            DEFAULT_START_DISTANCE,
        )
    return PreSnapContextRecord(
        territory=t,
        yardline=y,
        down=d,
        distance=dist,
        quarter=int(ambient_ctx.quarter),
        seconds_remaining=int(ambient_ctx.seconds_remaining),
        score_diff=int(score_diff),
        own_timeouts=int(ambient_ctx.own_timeouts),
        opp_timeouts=int(ambient_ctx.opp_timeouts),
        plays_this_drive_before_snap=max(0, play_idx0),
        reconstruction_anchor=anchor_tag,
        reconstruction_notes=recon_notes,
        def_personnel=str(ambient_ctx.def_personnel),
        coverage_shell=str(ambient_ctx.coverage_shell),
        weather=str(ambient_ctx.weather),
    )


def comparison_rows_for_archived_drive(
    *,
    drive: Drive,
    game: Game,
    ambient_ctx: GameContext,
    predictor: FootballPlayPredictor,
    plays: Sequence[ActualPlayResult],
) -> List[ActualVsReplayComparisonRow]:
    rows: List[ActualVsReplayComparisonRow] = []
    plist = list(plays)
    if not plist:
        return rows

    chain, chain_err, anchor_tag = best_presnap_chain_for_drive_plays(plist)
    score_diff = score_diff_for_archived_possession(game, getattr(drive, "possessing_team", "offense"))
    recon_notes = f"{OVERLAY_NOTE} Anchor: {anchor_tag.replace('_', ' ')}."
    if chain_err:
        recon_notes += f" Chain: {chain_err}."

    for i, play in enumerate(plist):
        primary = format_actual_play_operator_headline(play)
        detail = format_actual_play_operator_detail(play)
        actual_struct = actual_play_structured_dict(play)
        actual_rp = actual_run_pass_bucket(play)
        act_bucket = actual_play_summary_bucket(play)

        if chain_err == "touchdown_mid_drive" and i >= len(chain):
            pre = _fallback_pre_snap(
                ambient_ctx=ambient_ctx,
                score_diff=score_diff,
                anchor_tag=anchor_tag,
                recon_notes=recon_notes,
                play_idx0=i,
                chain=chain,
            )
            rows.append(
                ActualVsReplayComparisonRow(
                    play_index=i + 1,
                    pre_snap_context=pre,
                    actual_play_summary_primary=primary,
                    actual_play_summary_detail=detail,
                    actual_structured_result=actual_struct,
                    model_replay_summary="",
                    model_replay_structured=None,
                    actual_run_pass=actual_rp,
                    model_run_pass=None,
                    run_pass_match=None,
                    family_match=None,
                    actual_summary_bucket=act_bucket,
                    replay_summary_bucket="",
                    coarse_bucket_match=None,
                    chain_error=chain_err,
                    replay_error=REPLAY_UNAVAILABLE,
                )
            )
            continue

        if chain_err == "situation_advance_failed" and i >= len(chain):
            pre = _fallback_pre_snap(
                ambient_ctx=ambient_ctx,
                score_diff=score_diff,
                anchor_tag=anchor_tag,
                recon_notes=recon_notes,
                play_idx0=i,
                chain=chain,
            )
            rows.append(
                ActualVsReplayComparisonRow(
                    play_index=i + 1,
                    pre_snap_context=pre,
                    actual_play_summary_primary=primary,
                    actual_play_summary_detail=detail,
                    actual_structured_result=actual_struct,
                    model_replay_summary="",
                    model_replay_structured=None,
                    actual_run_pass=actual_rp,
                    model_run_pass=None,
                    run_pass_match=None,
                    family_match=None,
                    actual_summary_bucket=act_bucket,
                    replay_summary_bucket="",
                    coarse_bucket_match=None,
                    chain_error=chain_err,
                    replay_error=REPLAY_UNAVAILABLE,
                )
            )
            continue

        if i >= len(chain):
            pre = _fallback_pre_snap(
                ambient_ctx=ambient_ctx,
                score_diff=score_diff,
                anchor_tag=anchor_tag,
                recon_notes=recon_notes,
                play_idx0=i,
                chain=chain,
            )
            rows.append(
                ActualVsReplayComparisonRow(
                    play_index=i + 1,
                    pre_snap_context=pre,
                    actual_play_summary_primary=primary,
                    actual_play_summary_detail=detail,
                    actual_structured_result=actual_struct,
                    model_replay_summary="",
                    model_replay_structured=None,
                    actual_run_pass=actual_rp,
                    model_run_pass=None,
                    run_pass_match=None,
                    family_match=None,
                    actual_summary_bucket=act_bucket,
                    replay_summary_bucket="",
                    coarse_bucket_match=None,
                    chain_error=chain_err,
                    replay_error=REPLAY_UNAVAILABLE,
                )
            )
            continue

        t, y, d, dist = chain[i]
        prefix_log = _drive_logger_prefix(plist, i)
        ctx = build_replay_game_context(
            ambient=ambient_ctx,
            territory=t,
            yardline=y,
            down=d,
            distance=dist,
            drive_log=prefix_log,
            score_diff=score_diff,
        )
        pre = pre_snap_record_from_context(
            ctx,
            plays_before=len(prefix_log.results),
            reconstruction_anchor=anchor_tag,
            reconstruction_notes=recon_notes,
        )

        try:
            rec = predictor.recommend(ctx, drive_log=prefix_log, game=None, historical_plays=None)
        except Exception:
            rows.append(
                ActualVsReplayComparisonRow(
                    play_index=i + 1,
                    pre_snap_context=pre,
                    actual_play_summary_primary=primary,
                    actual_play_summary_detail=detail,
                    actual_structured_result=actual_struct,
                    model_replay_summary="",
                    model_replay_structured=None,
                    actual_run_pass=actual_rp,
                    model_run_pass=None,
                    run_pass_match=None,
                    family_match=None,
                    actual_summary_bucket=act_bucket,
                    replay_summary_bucket="",
                    coarse_bucket_match=None,
                    chain_error=chain_err,
                    replay_error=REPLAY_UNAVAILABLE,
                )
            )
            continue

        structured = model_replay_structured_from_recommend(rec)
        summary_line = model_replay_one_line(structured) if structured else ""
        model_rp = structured.run_pass if structured else None
        rep_bucket = structured.summary_bucket if structured else ""
        coarse = coarse_bucket_alignment(
            act_bucket,
            rep_bucket,
            actual_run_pass=actual_rp,
            replay_run_pass=model_rp,
        )
        rpm: Optional[bool] = None
        if actual_rp is not None and model_rp is not None:
            rpm = actual_rp == model_rp
        fm = family_match_actual_vs_replay(play, rec)

        rows.append(
            ActualVsReplayComparisonRow(
                play_index=i + 1,
                pre_snap_context=pre,
                actual_play_summary_primary=primary,
                actual_play_summary_detail=detail,
                actual_structured_result=actual_struct,
                model_replay_summary=summary_line or (structured.play_family if structured else ""),
                model_replay_structured=structured,
                actual_run_pass=actual_rp,
                model_run_pass=model_rp,
                run_pass_match=rpm,
                family_match=fm,
                actual_summary_bucket=act_bucket,
                replay_summary_bucket=rep_bucket,
                coarse_bucket_match=coarse,
                chain_error=chain_err,
                replay_error=None if structured else REPLAY_UNAVAILABLE,
            )
        )

    return rows


def predictor_replay_cache_token(predictor: FootballPlayPredictor) -> str:
    cls = type(predictor)
    return f"{cls.__module__}.{cls.__qualname__}"


def ambient_replay_overlay_fingerprint(ctx: GameContext) -> str:
    """Overlay fields that affect replay (reconstructed down/distance are excluded)."""
    parts = (
        str(ctx.def_personnel),
        str(ctx.box_count),
        str(ctx.coverage_shell),
        str(ctx.blitz_likely),
        str(ctx.safeties),
        str(ctx.score_diff),
        str(ctx.quarter),
        str(ctx.seconds_remaining),
        str(ctx.own_timeouts),
        str(ctx.opp_timeouts),
        str(ctx.weather),
        str(ctx.wind_mph),
        str(ctx.qb_limited),
        str(ctx.mismatch or ""),
        str(ctx.game_mode),
    )
    return "|".join(parts)


def plays_list_fingerprint(plays: Sequence[ActualPlayResult]) -> str:
    """Cheap invalidation when archived plays change."""
    parts: List[str] = []
    for i, p in enumerate(plays):
        eid = getattr(p, "external_play_id", None) or ""
        parts.append(
            f"{i}:{eid}:{int(p.yards_gained)}:{p.family}:{p.result_type}:{int(bool(p.touchdown))}"
        )
    return f"{len(plays)};" + "|".join(parts)


def comparison_rows_cache_key(
    *,
    game: Game,
    drive_index: int,
    predictor: FootballPlayPredictor,
    ambient_ctx: GameContext,
    plays: Sequence[ActualPlayResult],
) -> str:
    gid = str(getattr(game, "game_id", "") or id(game))
    return ":".join(
        [
            gid,
            str(int(drive_index)),
            predictor_replay_cache_token(predictor),
            ambient_replay_overlay_fingerprint(ambient_ctx),
            plays_list_fingerprint(plays),
        ]
    )


def cached_comparison_rows_for_archived_drive(
    session_state: MutableMapping[str, Any],
    *,
    drive: Drive,
    drive_index: int,
    game: Game,
    ambient_ctx: GameContext,
    predictor: FootballPlayPredictor,
    plays: Sequence[ActualPlayResult],
) -> List[ActualVsReplayComparisonRow]:
    """
    Session-scoped memo for ``comparison_rows_for_archived_drive`` (Streamlit reruns).

    Keyed by game id, drive index, predictor class, replay overlay fingerprint, and a play-list fingerprint.
    """
    from playcaller.streamlit_state.keys import ARCHIVED_DRIVE_COMPARISON_ROWS_CACHE

    bucket = session_state.get(ARCHIVED_DRIVE_COMPARISON_ROWS_CACHE)
    if not isinstance(bucket, dict):
        bucket = {}
        session_state[ARCHIVED_DRIVE_COMPARISON_ROWS_CACHE] = bucket

    cache_key = comparison_rows_cache_key(
        game=game,
        drive_index=drive_index,
        predictor=predictor,
        ambient_ctx=ambient_ctx,
        plays=plays,
    )
    hit = bucket.get(cache_key)
    if isinstance(hit, list) and all(isinstance(x, ActualVsReplayComparisonRow) for x in hit):
        return hit

    rows = comparison_rows_for_archived_drive(
        drive=drive,
        game=game,
        ambient_ctx=ambient_ctx,
        predictor=predictor,
        plays=plays,
    )
    bucket[cache_key] = rows
    while len(bucket) > _MAX_ARCHIVED_DRIVE_COMPARISON_CACHE_ENTRIES:
        bucket.pop(next(iter(bucket)))
    return rows


# Alias for analysis pipelines
replay_rows_for_archived_drive = comparison_rows_for_archived_drive


def map_recommendation_to_run_pass(result: Mapping[str, Any]) -> Optional[str]:
    """Map a ``predictor.recommend`` dict to **Run** or **Pass** (thin wrapper)."""
    s = model_replay_structured_from_recommend(result)
    return s.run_pass if s else None

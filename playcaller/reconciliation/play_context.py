"""
Centralized per-play pre-snap context for archived-drive replay (not drive reconciler output).

Resolves quarter / clock / scores from ESPN feed fields on :class:`~playcaller.domain.ActualPlayResult`,
with explicit precedence and provenance — **no** default to Q1 or 15:00 when unknown.
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

from playcaller.domain import ActualPlayResult, GameContext
from playcaller.play_event_segment import PlayEventSegment, segment_from_actual
from playcaller.replay.analysis_types import PreSnapContextRecord
from playcaller.situation import territory_yardline_from_abs_yards

# Align with ``seconds_per_play`` heuristics used in drive reconciliation / inferred TOP.
ESTIMATED_SECONDS_BETWEEN_SNAPS = 38


def parse_espn_clock_display_to_seconds(display: str) -> Optional[int]:
    """
    Parse ESPN ``clock.displayValue`` (e.g. ``7:25``, ``12:56``, ``0:00``) to seconds left in the period.

    Returns ``None`` if the string is missing or not ``M:SS`` / ``MM:SS``.
    """
    s = (display or "").strip()
    if not s:
        return None
    if s.lower() in ("end", "end of period"):
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if not m:
        return None
    try:
        minutes, secs = int(m.group(1)), int(m.group(2))
        if secs >= 60:
            return None
        return max(0, minutes * 60 + secs)
    except ValueError:
        return None


def format_seconds_as_clock_mmss(total_seconds: int) -> str:
    s = max(0, int(total_seconds))
    m, sec = divmod(s, 60)
    return f"{m}:{sec:02d}"


def resolve_archived_pre_snap_timing(
    play: ActualPlayResult,
    prior_play: Optional[ActualPlayResult],
    play_index0: int,
    reconciled: object,
) -> Tuple[Optional[int], Optional[int], Optional[str], Dict[str, str]]:
    """
    Resolve quarter, seconds-left-in-period, and display clock string.

    Precedence for quarter / clock:
      1. ESPN fields on this play (``feed_period_number``, ``feed_clock_display``).
      2. First play of drive: reconciled drive start quarter / clock (drive-level ESPN).
      3. Same-quarter estimate from prior play's clock minus estimated snap spacing (marked reconstructed).
      4. Otherwise ``None`` (honest unknown).
    """
    prov: Dict[str, str] = {}

    q: Optional[int] = None
    if play.feed_period_number is not None:
        try:
            qi = int(play.feed_period_number)
            if qi > 0:
                q = qi
                prov["quarter"] = "espn"
        except (TypeError, ValueError):
            pass

    clk: Optional[str] = None
    if play.feed_clock_display and str(play.feed_clock_display).strip():
        clk = str(play.feed_clock_display).strip()
        prov["clock"] = "espn"

    sec: Optional[int] = parse_espn_clock_display_to_seconds(clk) if clk else None
    if sec is not None and "seconds" not in prov:
        prov["seconds"] = "espn"

    if q is not None and clk is not None:
        return q, sec, clk, prov

    if play_index0 == 0:
        if q is None and int(getattr(reconciled, "start_quarter", 0) or 0) > 0:
            q = int(reconciled.start_quarter)
            prov["quarter"] = "drive_fallback"
        sc = str(getattr(reconciled, "start_clock", "") or "").strip()
        if clk is None and sc:
            clk = sc
            prov["clock"] = "drive_fallback"
            sec = parse_espn_clock_display_to_seconds(clk)

    if clk is None or sec is None:
        if prior_play is not None:
            pq = prior_play.feed_period_number
            pclk = prior_play.feed_clock_display
            if pclk and str(pclk).strip():
                pclk_s = str(pclk).strip()
                psec = parse_espn_clock_display_to_seconds(pclk_s)
                if psec is not None:
                    eff_q = q if q is not None else (int(pq) if pq is not None and int(pq) > 0 else None)
                    if eff_q is not None and pq is not None and int(pq) == eff_q:
                        est = psec - ESTIMATED_SECONDS_BETWEEN_SNAPS
                        if est >= 0:
                            sec = est
                            clk = format_seconds_as_clock_mmss(est)
                            prov["clock"] = "reconstructed"
                            prov["seconds"] = "reconstructed"
                            if q is None:
                                q = eff_q
                                prov["quarter"] = "reconstructed"

    if q is None and prior_play is not None and prior_play.feed_period_number:
        try:
            qi = int(prior_play.feed_period_number)
            if qi > 0:
                q = qi
                prov["quarter"] = "inherited_prior"
        except (TypeError, ValueError):
            pass

    return q, sec, clk, prov


def _field_from_reconciled_start(reconciled: object) -> Tuple[Optional[str], Optional[int]]:
    """Drive-level ESPN ``start.yardLine`` as ytez → canonical ``(territory, yardline)``."""
    fp = getattr(reconciled, "start_field_position", None)
    if fp is None:
        return None, None
    raw_yl = getattr(fp, "yard_line", None)
    if raw_yl is None:
        return None, None
    try:
        y = int(raw_yl)
    except (TypeError, ValueError):
        return None, None
    if not 1 <= y <= 99:
        return None, None
    abs_y = 100 - y
    return territory_yardline_from_abs_yards(abs_y)


def resolve_archived_pre_snap_situation(
    play: ActualPlayResult,
    play_idx0: int,
    chain_tuple: Optional[Tuple[str, int, int, int]],
    reconciled: object,
    *,
    prior_play: Optional[ActualPlayResult] = None,
    offense_team_abbr: str = "",
    defense_team_abbr: str = "",
) -> Tuple[
    Optional[int],
    Optional[int],
    Optional[str],
    Optional[int],
    bool,
    Optional[int],
    Optional[int],
    str,
    str,
    Dict[str, str],
]:
    """
    ESPN-first pre-snap field + down/distance + scores with per-field provenance.

    Precedence per field: ESPN feed on ``ActualPlayResult`` → presnap chain (reconstructed)
    → drive-level start (first play, field only) → honest ``None`` / ``unknown`` on later plays.
    Scores: each of home/away uses ESPN when present on this play; otherwise the same field
    from ``prior_play`` (``computed``) when available.
    Special teams scrimmage rows: down/distance suppressed (``not_applicable``).
    """
    prov: Dict[str, str] = {}
    special = segment_from_actual(play) != PlayEventSegment.OFFENSE
    ct = str(offense_team_abbr or "").strip()
    opp = str(defense_team_abbr or "").strip() or "OPP"

    down: Optional[int] = None
    dist: Optional[int] = None
    terr: Optional[str] = None
    yl: Optional[int] = None
    hs: Optional[int] = play.feed_home_score
    aw: Optional[int] = play.feed_away_score
    poss = str(play.feed_possession_team_abbr or "").strip()
    g2g = bool(play.feed_presnap_goal_down)

    fd = play.feed_presnap_down
    if fd is not None:
        try:
            di0 = int(fd)
            if di0 in (1, 2, 3, 4):
                down = di0
                prov["down"] = "espn"
        except (TypeError, ValueError):
            pass

    fdi = play.feed_presnap_distance
    if fdi is not None:
        try:
            ddi = int(fdi)
            if 1 <= ddi <= 99:
                dist = ddi
                prov["distance"] = "espn"
        except (TypeError, ValueError):
            pass

    ft = play.feed_presnap_territory
    fy = play.feed_presnap_yardline
    if ft in ("own", "opponents") and fy is not None:
        try:
            yi = int(fy)
            if 1 <= yi <= 50:
                terr, yl = str(ft), yi
                prov["territory"] = "espn"
                prov["yard_line"] = "espn"
        except (TypeError, ValueError):
            pass

    ph = getattr(prior_play, "feed_home_score", None) if prior_play is not None else None
    pa = getattr(prior_play, "feed_away_score", None) if prior_play is not None else None

    if hs is not None and aw is not None:
        prov["home_score"] = "espn"
        prov["away_score"] = "espn"
    else:
        if hs is None and ph is not None:
            hs = int(ph)
            prov["home_score"] = "computed"
        elif hs is None:
            prov["home_score"] = "unknown"
        else:
            prov["home_score"] = "espn"

        if aw is None and pa is not None:
            aw = int(pa)
            prov["away_score"] = "computed"
        elif aw is None:
            prov["away_score"] = "unknown"
        else:
            prov["away_score"] = "espn"

    if play.feed_possession_team_abbr:
        poss = str(play.feed_possession_team_abbr).strip()
        prov["possession_team"] = "espn"
    elif ct:
        poss = ct
        prov["possession_team"] = "drive_fallback"

    if special:
        down, dist = None, None
        prov["down"] = "not_applicable"
        prov["distance"] = "not_applicable"
        g2g = False
    elif chain_tuple is not None:
        t_c, y_c, d_c, dist_c = chain_tuple
        if down is None:
            down = max(1, min(4, int(d_c)))
            prov["down"] = "reconstructed"
        if dist is None:
            dist = max(1, min(25, int(dist_c)))
            prov["distance"] = "reconstructed"
        if terr is None and str(t_c) in ("own", "opponents"):
            terr = str(t_c)
            yl = max(1, min(50, int(y_c)))
            prov["territory"] = "reconstructed"
            prov["yard_line"] = "reconstructed"

    if not special and play_idx0 == 0:
        if terr is None or yl is None:
            r_terr, r_yl = _field_from_reconciled_start(reconciled)
            if r_terr is not None and r_yl is not None:
                terr, yl = r_terr, r_yl
                prov["territory"] = "drive_fallback"
                prov["yard_line"] = "drive_fallback"
        if down is None:
            down = 1
            prov["down"] = "drive_fallback"
        if dist is None:
            dist = 10
            if terr == "opponents" and yl is not None:
                dist = min(10, int(yl))
            prov["distance"] = "drive_fallback"

    if not special and play_idx0 > 0:
        if down is None:
            prov["down"] = "unknown"
        if dist is None:
            prov["distance"] = "unknown"
        if terr is None:
            prov["territory"] = "unknown"
        if yl is None:
            prov["yard_line"] = "unknown"

    if (
        not g2g
        and not special
        and terr == "opponents"
        and yl is not None
        and dist is not None
        and 1 <= int(yl) <= 10
        and int(dist) >= int(yl)
    ):
        g2g = True

    return down, dist, terr, yl, g2g, hs, aw, poss, opp, prov


def build_pre_snap_record_for_archived_replay(
    *,
    chain_tuple: Optional[Tuple[str, int, int, int]],
    play_idx0: int,
    play: ActualPlayResult,
    prior_play: Optional[ActualPlayResult],
    ambient_ctx: GameContext,
    score_diff: int,
    plays_before: int,
    reconciled: object,
    reconstruction_anchor: str,
    reconstruction_notes: str,
    offense_team_abbr: str = "",
    defense_team_abbr: str = "",
) -> PreSnapContextRecord:
    """
    Build :class:`PreSnapContextRecord` for one archived play.

    Quarter and clock come from :func:`resolve_archived_pre_snap_timing`, not from ``ambient_ctx``
    (which reflects the live console and caused every replay row to share one Q/clock).

    Down, distance, and field position come from :func:`resolve_archived_pre_snap_situation`
    (ESPN-first, then chain reconstruction, then first-play drive fallback only when needed).
    """
    d_down, d_dist, d_terr, d_yl, g2g, hs, aw, poss_abbrev, opp_abbrev, sit_prov = (
        resolve_archived_pre_snap_situation(
            play,
            play_idx0,
            chain_tuple,
            reconciled,
            prior_play=prior_play,
            offense_team_abbr=offense_team_abbr,
            defense_team_abbr=defense_team_abbr,
        )
    )
    q, sec, clk, time_prov = resolve_archived_pre_snap_timing(
        play, prior_play, play_idx0, reconciled
    )
    prov_map = {**sit_prov, **time_prov}
    snap_prov = tuple(sorted(prov_map.items()))

    return PreSnapContextRecord(
        territory=d_terr,
        yardline=d_yl,
        down=d_down,
        distance=d_dist,
        quarter=q,
        seconds_remaining=sec,
        score_diff=int(score_diff),
        own_timeouts=int(ambient_ctx.own_timeouts),
        opp_timeouts=int(ambient_ctx.opp_timeouts),
        plays_this_drive_before_snap=max(0, int(plays_before)),
        reconstruction_anchor=reconstruction_anchor,
        reconstruction_notes=reconstruction_notes or "",
        clock_display=clk,
        home_score_snap=hs,
        away_score_snap=aw,
        snap_provenance=snap_prov,
        def_personnel=str(ambient_ctx.def_personnel),
        coverage_shell=str(ambient_ctx.coverage_shell),
        weather=str(ambient_ctx.weather),
        goal_to_go=g2g,
        possession_team_abbrev=poss_abbrev,
        opponent_team_abbrev=opp_abbrev,
    )

"""
Play-level implied score reconstruction for processed warehouse games (§10.1/§10.2).

Single source for event points; drive-level TD=7 is not used when warehouse tags are present.
"""

from __future__ import annotations

import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import DefaultDict, Literal, Optional

from playcaller.domain import ActualPlayResult
from playcaller.game import Game

from warehouse.taxonomy import PlayResult, PlayType

logger = logging.getLogger(__name__)


def _in_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


@dataclass
class UnattributableScoreAccumulator:
    n_unattributable_scores: int = 0
    unattributable_by_play_type: DefaultDict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    unattributable_by_reason: DefaultDict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )

    def add(self, play_type: str, reason: str) -> None:
        self.n_unattributable_scores += 1
        self.unattributable_by_play_type[play_type] += 1
        self.unattributable_by_reason[reason] += 1


def attribute_scoring_points(
    p: ActualPlayResult,
    points: int,
    *,
    team_abbr: str | None,
    provenance: str | None,
    role: Literal["poss", "def"],
    unattributable: UnattributableScoreAccumulator | None = None,
) -> tuple[int, str]:
    """
    Choke point for all warehouse score attribution. Never uses ``display_possession_team_abbr``.
    """
    if points == 0:
        return 0, ""
    ab = (team_abbr or "").strip()
    prov_raw = (provenance or "").strip()
    # Legacy :class:`ActualPlayResult` rows may omit ``posteam_source``; non-empty abbr
    # without provenance is treated as feed (loader normally sets this explicitly).
    prov = "feed" if (ab and not prov_raw) else (prov_raw or "missing")
    if ab and prov != "feed":
        msg = f"scoring field leak: team_abbr={ab!r} provenance={prov!r} role={role!r}"
        if _in_pytest():
            raise AssertionError(msg)
        logger.critical(msg)
        return 0, ""
    wtype = (p.feed_warehouse_play_type or "").strip() or "unknown"
    if not ab:
        reason = "missing_feed_defteam" if role == "def" else "missing_feed_posteam"
        if unattributable is not None:
            unattributable.add(wtype, reason)
        return 0, ""
    return points, ab


# Authoritative point values (§10.1) — scoring uses :func:`points_for_play` only.
TOUCHDOWN_POINTS = 6
EXTRA_POINT_KICK_POINTS = 1
TWO_POINT_CONVERSION_POINTS = 2
FIELD_GOAL_POINTS = 3
SAFETY_POINTS = 2
DEFENSIVE_TWO_POINT_RETURN_POINTS = 2

SideHA = Optional[Literal["home", "away"]]

SESSION_OFFENSE = "offense"  # session “us” in Drive — maps to :attr:`Game.offense_points` (warehouse: home)
SESSION_DEFENSE = "defense"  # “them” — maps to :attr:`Game.defense_points` (warehouse: away)


@dataclass
class ScoreBreakdown:
    """Implied point counts by event for one team (board home / away) for mismatch diagnostics."""

    td: int = 0
    pat: int = 0
    two: int = 0
    fg: int = 0
    safety: int = 0
    def_two: int = 0

    def as_parts_line(self) -> str:
        parts: list[str] = []
        if self.td:
            parts.append(f"{self.td}×TD(6)")
        if self.pat:
            parts.append(f"{self.pat}×PAT(1)")
        if self.two:
            parts.append(f"{self.two}×2PT(2)")
        if self.fg:
            parts.append(f"{self.fg}×FG(3)")
        if self.safety:
            parts.append(f"{self.safety}×SFTY(2)")
        if self.def_two:
            parts.append(f"{self.def_two}×def-2PT(2)")
        return " + ".join(parts) if parts else "0 pts"


def _side_for_abbr(abbr: Optional[str], *, home_team: str, away_team: str) -> SideHA:
    a = (abbr or "").strip()
    h, aw = (home_team or "").strip(), (away_team or "").strip()
    if a and h and a == h:
        return "home"
    if a and aw and a == aw:
        return "away"
    return None


def _session_is_home(game: Game) -> bool:
    m = game.session_metadata or {}
    return bool(m.get("warehouse_offense_is_home", True))


def _bump_breakdown(
    bd: DefaultDict[Literal["home", "away"], ScoreBreakdown],
    side: Literal["home", "away"],
    *,
    kind: str,
) -> None:
    b = bd[side]
    if kind == "td":
        b.td += 1
    elif kind == "pat":
        b.pat += 1
    elif kind == "two":
        b.two += 1
    elif kind == "fg":
        b.fg += 1
    elif kind == "safety":
        b.safety += 1
    elif kind == "def_two":
        b.def_two += 1


def points_for_play(
    p: ActualPlayResult,
    *,
    home_team: str,
    away_team: str,
    unattributable: UnattributableScoreAccumulator | None = None,
) -> tuple[int, SideHA]:
    """
    Return (points, scoring side home|away) for a single play.
    (0, None) for non-scoring. Uses warehouse :attr:`feed_warehouse_play_type` / ``..._result``.
    Scoring uses only the feed posteam (via :func:`attribute_scoring_points`); never ``display_possession_team_abbr``.
    """
    wt = (p.feed_warehouse_play_type or "").strip()
    wr = (p.feed_warehouse_play_result or "").strip()
    if not wt or not wr:
        return 0, None

    try:
        wte = PlayType(wt)
        wre = PlayResult(wr)
    except ValueError:
        return 0, None

    poss = p.feed_possession_team_abbr
    prov_p = p.posteam_source
    deff = p.feed_defense_team_abbr
    prov_d = p.defteam_source

    def _ha_from_poss(pts: int) -> tuple[int, SideHA]:
        r_pts, ab = attribute_scoring_points(
            p,
            pts,
            team_abbr=poss,
            provenance=prov_p,
            role="poss",
            unattributable=unattributable,
        )
        if not r_pts:
            return 0, None
        side = _side_for_abbr(ab, home_team=home_team, away_team=away_team)
        if side is None:
            return 0, None
        return r_pts, side

    def _ha_from_def(pts: int) -> tuple[int, SideHA]:
        r_pts, ab = attribute_scoring_points(
            p,
            pts,
            team_abbr=deff,
            provenance=prov_d,
            role="def",
            unattributable=unattributable,
        )
        if not r_pts:
            return 0, None
        side = _side_for_abbr(ab, home_team=home_team, away_team=away_team)
        if side is None:
            return 0, None
        return r_pts, side

    # Touchdown plays (6) — team with possession at scoring moment.
    if wre in (
        PlayResult.TOUCHDOWN_RUN,
        PlayResult.TOUCHDOWN_PASS,
        PlayResult.TOUCHDOWN_RETURN,
        PlayResult.KICKOFF_RETURN_TD,
    ):
        return _ha_from_poss(TOUCHDOWN_POINTS)

    if wte == PlayType.EXTRA_POINT and wre == PlayResult.EXTRA_POINT_MADE:
        return _ha_from_poss(EXTRA_POINT_KICK_POINTS)

    if wte == PlayType.TWO_POINT and wre == PlayResult.TWO_POINT_GOOD:
        return _ha_from_poss(TWO_POINT_CONVERSION_POINTS)

    if wte == PlayType.FIELD_GOAL and wre == PlayResult.FIELD_GOAL_MADE:
        return _ha_from_poss(FIELD_GOAL_POINTS)

    if wre == PlayResult.SAFETY:
        return _ha_from_def(SAFETY_POINTS)

    # Some feeds mark TDs as ``COMPLETE``/rush gains with a ``touchdown`` bit only.
    poss_has_feed = bool((poss or "").strip())
    if p.touchdown and poss_has_feed:
        if wre in (PlayResult.COMPLETE, PlayResult.SCRAMBLE_GAIN, PlayResult.RUSH_GAIN, PlayResult.RUSH_LOSS) or wte in (
            PlayType.PASS,
            PlayType.RUN,
            PlayType.SCRAMBLE,
        ):
            return _ha_from_poss(TOUCHDOWN_POINTS)
    return 0, None


def _admin_play_skip_delta(p: ActualPlayResult) -> bool:
    """
    Kicks, punts, and clock-only rows can carry a **lagged** score change from the previous snap;
    :func:`_scoreboard_delta_ha` must not treat that as a new scoring play.
    """
    wt = (p.feed_warehouse_play_type or "").strip()
    if not wt:
        return True
    try:
        wte = PlayType(wt)
    except ValueError:
        return True
    if wte == PlayType.KICKOFF:
        # Warehouse mis-tags some live plays as ``KICKOFF`` with a scrimmage result (e.g. fair
        # catch) while the live board advances (+2 safety / conversion); do not treat as
        # administrative-only — allow :func:`_scoreboard_delta_ha` (Category 1/2, §10.3).
        wr0 = (p.feed_warehouse_play_result or "").strip()
        if wr0 in (PlayResult.PUNT_FAIR_CATCH.value, PlayResult.PUNT_NORMAL.value):
            return False
    return wte in (
        PlayType.KICKOFF,
        PlayType.PUNT,
        PlayType.TIMEOUT,
        PlayType.PENALTY_NO_PLAY,
        PlayType.SPIKE,
        PlayType.KNEEL,
        PlayType.UNKNOWN,
    )


def _scoreboard_delta_ha(
    p: ActualPlayResult, prev: Optional[ActualPlayResult]
) -> tuple[int, SideHA]:
    """Points and home/away side from the running board delta (current vs previous play).

    Returns ``(0, None)`` when the delta cannot be interpreted as a single scoring side:

    * Missing current feed columns (``feed_cumulative_home`` / ``feed_cumulative_away``).
    * **Negative** delta on either side (resets, corrections, or out-of-order rows) —
      caller should not attribute points to this play.
    * **No bump**: ``d_home == d_away == 0`` (no net change; includes first-play
      baseline when previous totals were unset).
    * **Symmetric two-team bump** ``d_home == d_away > 0`` (rare) returns
      ``(d_home, "home")`` — not ``(0, None)``; the scoreboard did move, but the
      side is arbitrary; upstream may treat that as a bad row.

    One-sided bumps map cleanly: only home or only away increments. When both sides
    increment **unequally**, the larger side is taken as the delta source (e.g. PAT
    only on one row vs lag on the other).
    """
    if p.feed_cumulative_home is None or p.feed_cumulative_away is None:
        return 0, None
    if (
        prev is not None
        and prev.feed_cumulative_home is not None
        and prev.feed_cumulative_away is not None
    ):
        d_home = int(p.feed_cumulative_home) - int(prev.feed_cumulative_home)
        d_away = int(p.feed_cumulative_away) - int(prev.feed_cumulative_away)
    else:
        d_home = int(p.feed_cumulative_home)
        d_away = int(p.feed_cumulative_away)
    if d_home < 0 or d_away < 0:
        return 0, None
    if d_home > 0 and d_away == 0:
        return d_home, "home"
    if d_away > 0 and d_home == 0:
        return d_away, "away"
    if d_home > 0 and d_away > 0 and d_home != d_away:
        return (d_home, "home") if d_home > d_away else (d_away, "away")
    if d_home > 0 and d_away > 0 and d_home == d_away:  # extremely rare; split symmetrically
        return d_home, "home"
    return 0, None


def _bump_from_raw_pts(
    bd: DefaultDict[Literal["home", "away"], ScoreBreakdown],
    side: Literal["home", "away"],
    pts: int,
) -> None:
    if pts in (0, 4, 5, 7, 8, 9):
        return
    if pts == TOUCHDOWN_POINTS:
        _bump_breakdown(bd, side, kind="td")
    elif pts == EXTRA_POINT_KICK_POINTS:
        _bump_breakdown(bd, side, kind="pat")
    elif pts == FIELD_GOAL_POINTS:
        _bump_breakdown(bd, side, kind="fg")
    elif pts == TWO_POINT_CONVERSION_POINTS:
        _bump_breakdown(bd, side, kind="two")
    elif pts == SAFETY_POINTS:
        _bump_breakdown(bd, side, kind="safety")
    else:
        # Unknown increment — do not attribute to a bucket.
        return


def _ha_to_session_off_def(side: SideHA, *, game: Game) -> Optional[Literal["offense", "defense"]]:
    if side is None:
        return None
    home_is_us = _session_is_home(game)
    if side == "home":
        return SESSION_OFFENSE if home_is_us else SESSION_DEFENSE
    return SESSION_DEFENSE if home_is_us else SESSION_OFFENSE


def warehouse_possession_one_team_only_warning(game: Game) -> str | None:
    """Loud data/interpretation signal when no alternating possession in session frame (§10.3)."""
    sides: set[str] = set()
    for dr in game.drives:
        if dr.plays and dr.possessing_team in (SESSION_OFFENSE, SESSION_DEFENSE):
            sides.add(dr.possessing_team)
    if len(sides) == 1 and game.drives:
        only = next(iter(sides))
        return (
            f"🔴 **Drive coverage:** only `{only}` appears as `possessing_team` across drives — "
            f"implied per-team score cannot be trusted. Check `posteam` / home–away mapping."
        )
    return None


def _prev_had_dedicated_post_td_conversion_row(prev: ActualPlayResult) -> bool:
    """
    When the live feed already advanced the score on an EXTRA_POINT / TWO_POINT row, the
    following KICKOFF must not re-apply a +1 / +2 board bump (avoids double-counting).
    """
    wt = (prev.feed_warehouse_play_type or "").strip()
    wr = (prev.feed_warehouse_play_result or "").strip()
    if not wt or not wr:
        return False
    try:
        wte, wre = PlayType(wt), PlayResult(wr)
    except ValueError:
        return False
    if wte == PlayType.EXTRA_POINT and wre in (
        PlayResult.EXTRA_POINT_MADE,
        PlayResult.EXTRA_POINT_MISSED,
        PlayResult.EXTRA_POINT_BLOCKED,
    ):
        return True
    if wte == PlayType.TWO_POINT and wre in (
        PlayResult.TWO_POINT_GOOD,
        PlayResult.TWO_POINT_FAILED,
    ):
        return True
    return False


def _lagged_kickoff_small_conversion_delta(
    p: ActualPlayResult, prev: Optional[ActualPlayResult]
) -> bool:
    """
    KICKOFF rows sometimes carry a +1 / +2 conversion after the feed put the play on
    *PENALTY_NO_PLAY* (placeholder / no-play) or similar — never open this path after
    a live scrimmage or conversion snap (avoids +1 on kickoff when PAT was already in enum
    and the +1 is only scoreboard catch-up; §10.3 narrow allow-on-skip).
    """
    if prev is None:
        return False
    pwt = (p.feed_warehouse_play_type or "").strip()
    try:
        wte = PlayType(pwt)
    except ValueError:
        return False
    if wte != PlayType.KICKOFF:
        return False
    prev_wt = (prev.feed_warehouse_play_type or "").strip()
    try:
        prev_wt_e = PlayType(prev_wt)
    except ValueError:
        return False
    if prev_wt_e != PlayType.PENALTY_NO_PLAY:
        return False
    if _prev_had_dedicated_post_td_conversion_row(prev):
        return False
    d_pts, d_ha = _scoreboard_delta_ha(p, prev)
    # +1 PAT on KICKOFF after PENALTY is more often a duplicate of an EXTRA_POINT row when
    # the feed labels were inconsistent; the two-point +2 case is the common legitimate lag.
    if d_pts != 2 or d_ha is None:
        return False
    return True


def warehouse_session_points_for_play(
    p: ActualPlayResult,
    prev: Optional[ActualPlayResult],
    game: Game,
    *,
    home_team: str,
    away_team: str,
    unattributable: UnattributableScoreAccumulator | None = None,
) -> tuple[
    int, int, int, Literal["enum", "delta", "none"], SideHA
]:
    """
    (add_to_session_offense, add_to_session_defense, raw_pts_on_play, source, home|away|None for breakdown).
    Tries :func:`points_for_play` (includes ``touchdown``+enum repairs), else running scoreboard delta.
    """
    e_pts, e_ha = points_for_play(
        p, home_team=home_team, away_team=away_team, unattributable=unattributable
    )
    if e_pts and e_ha is not None:
        s = _ha_to_session_off_def(e_ha, game=game)
        if s == SESSION_OFFENSE:
            return e_pts, 0, e_pts, "enum", e_ha
        if s == SESSION_DEFENSE:
            return 0, e_pts, e_pts, "enum", e_ha
    skip = _admin_play_skip_delta(p)
    if not skip:
        d_pts, d_ha = _scoreboard_delta_ha(p, prev)
        if d_pts and d_ha is not None:
            s2 = _ha_to_session_off_def(d_ha, game=game)
            if s2 == SESSION_OFFENSE:
                return d_pts, 0, d_pts, "delta", d_ha
            if s2 == SESSION_DEFENSE:
                return 0, d_pts, d_pts, "delta", d_ha
    elif _lagged_kickoff_small_conversion_delta(p, prev):
        d_pts, d_ha = _scoreboard_delta_ha(p, prev)
        if d_pts and d_ha is not None:
            s2 = _ha_to_session_off_def(d_ha, game=game)
            if s2 == SESSION_OFFENSE:
                return d_pts, 0, d_pts, "delta", d_ha
            if s2 == SESSION_DEFENSE:
                return 0, d_pts, d_pts, "delta", d_ha
    return 0, 0, 0, "none", None


def implied_totals_and_breakdown_from_warehouse_plays(
    game: Game,
    *,
    unattributable: UnattributableScoreAccumulator | None = None,
) -> tuple[int, int, DefaultDict[Literal["home", "away"], ScoreBreakdown]]:
    """
    Return (implied_offense_points, implied_defense_points, per_board_breakdown).

    ``offense``/``defense`` follow :class:`Game` session convention (warehouse: offense=home, defense=away).
    """
    meta = game.session_metadata or {}
    home_team = str(meta.get("warehouse_home_team") or "")
    away_team = str(meta.get("warehouse_away_team") or "")
    if not home_team or not away_team:
        return 0, 0, defaultdict(ScoreBreakdown)

    off = de = 0
    bd: DefaultDict[Literal["home", "away"], ScoreBreakdown] = defaultdict(ScoreBreakdown)
    prev: Optional[ActualPlayResult] = None
    for dr in game.drives:
        for p in dr.plays:
            a, b, r, src, s_ha = warehouse_session_points_for_play(
                p, prev, game, home_team=home_team, away_team=away_team, unattributable=unattributable
            )
            off += a
            de += b
            if s_ha is not None and r and src == "enum":
                if r == TOUCHDOWN_POINTS:
                    _bump_breakdown(bd, s_ha, kind="td")
                elif r == EXTRA_POINT_KICK_POINTS:
                    _bump_breakdown(bd, s_ha, kind="pat")
                elif r == TWO_POINT_CONVERSION_POINTS:
                    _bump_breakdown(bd, s_ha, kind="two")
                elif r == FIELD_GOAL_POINTS:
                    _bump_breakdown(bd, s_ha, kind="fg")
                elif r == SAFETY_POINTS:
                    _bump_breakdown(bd, s_ha, kind="safety")
                elif r == DEFENSIVE_TWO_POINT_RETURN_POINTS:
                    _bump_breakdown(bd, s_ha, kind="def_two")
            elif s_ha is not None and r and src == "delta":
                _bump_from_raw_pts(bd, s_ha, r)
            prev = p

    return off, de, bd

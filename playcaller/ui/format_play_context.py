"""
Single canonical per-play context line for Review Session surfaces.

Format: ``Q3 7:25 · 1st & 10 · GB 28 · 24–17`` (clock · down & distance · team + yard · scoreboard).

No Streamlit imports — safe for analytics and tests.
"""

from __future__ import annotations

from typing import Any, Mapping

from playcaller.game import Game
from playcaller.play_event_segment import PlayEventSegment
from playcaller.ui_components import fmt_clock


def _prov_map(pre: Mapping[str, Any]) -> dict[str, str]:
    sp = pre.get("snap_provenance")
    if not sp:
        return {}
    if isinstance(sp, dict):
        return {str(k): str(v) for k, v in sp.items()}
    out: dict[str, str] = {}
    for item in sp:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out[str(item[0])] = str(item[1])
    return out


def _ordinal_down(d: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}.get(d, f"{d}th")


def _clock_segment(pre: Mapping[str, Any]) -> tuple[str, bool]:
    """
    Returns ``Qx mm:ss`` plus whether clock/seconds were reconstructed (for ``*`` marker).
    """
    try:
        q = int(pre.get("quarter", 1))
    except (TypeError, ValueError):
        q = 1
    prov = _prov_map(pre)
    recon = prov.get("clock") == "reconstructed" or prov.get("seconds") == "reconstructed"
    cd = pre.get("clock_display")
    if cd and str(cd).strip():
        return f"Q{q} {str(cd).strip()}", recon
    try:
        sec = int(pre.get("seconds_remaining", 0))
    except (TypeError, ValueError):
        sec = 0
    if prov.get("seconds") == "reconstructed":
        recon = True
    return f"Q{q} {fmt_clock(sec)}", recon


def _scoreboard_segment(pre: Mapping[str, Any], game: Game) -> str:
    hs = pre.get("home_score_snap")
    aw = pre.get("away_score_snap")
    if hs is not None and aw is not None:
        try:
            return f"{int(hs)}–{int(aw)}"
        except (TypeError, ValueError):
            pass
    return f"{int(game.offense_points)}–{int(game.defense_points)}"


def _possession_abbr(pre: Mapping[str, Any], game: Game, drive_id: int) -> str:
    ab = str(pre.get("possession_team_abbrev") or "").strip()
    if ab:
        return ab
    terr = str(pre.get("territory", "own"))
    opp_pre = str(pre.get("opponent_team_abbrev") or "").strip()
    if 0 <= drive_id < len(game.drives):
        own = str(getattr(game.drives[drive_id], "feed_team_abbr", "") or "").strip()
        if terr == "opponents" and opp_pre:
            return opp_pre
        if own:
            return own
    if terr == "opponents" and opp_pre:
        return opp_pre
    return "—"


def _field_segment(pre: Mapping[str, Any], possession_abbr: str) -> str:
    try:
        yl = int(pre.get("yardline", 0))
    except (TypeError, ValueError):
        yl = 0
    ab = possession_abbr or "—"
    return f"{ab} {yl}"


def format_play_context(
    pre: Mapping[str, Any],
    segment: PlayEventSegment,
    *,
    game: Game,
    drive_id: int = 0,
) -> str:
    """
    Canonical context line for drive expanders, Top Mistakes, and situational play lists.

    Uses middle dots (·) between clauses. Reconstructed clock/seconds append ``*`` to the clock clause.
    """
    if not pre:
        return "—"
    score_part = _scoreboard_segment(pre, game)
    clk_part, clk_recon = _clock_segment(pre)
    if clk_recon:
        clk_part = f"{clk_part}*"

    if segment != PlayEventSegment.OFFENSE:
        kind = {
            PlayEventSegment.KICKOFF: "Kickoff",
            PlayEventSegment.PUNT: "Punt",
            PlayEventSegment.FIELD_GOAL: "Field goal attempt",
            PlayEventSegment.PAT: "Extra point",
            PlayEventSegment.ADMIN: "Admin / clock",
            PlayEventSegment.OTHER_SPECIAL: "Special teams",
        }.get(segment, "Special teams")
        return f"{clk_part} · {kind} · {score_part}"

    try:
        dn = int(pre.get("down", 1))
    except (TypeError, ValueError):
        dn = 1
    try:
        dist = int(pre.get("distance", 10))
    except (TypeError, ValueError):
        dist = 10
    down_s = f"{_ordinal_down(dn)} & {dist}"
    poss = _possession_abbr(pre, game, drive_id)
    field = _field_segment(pre, poss)
    return f"{clk_part} · {down_s} · {field} · {score_part}"

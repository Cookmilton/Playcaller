"""
Turn a parsed ``Game`` into normalized play-level rows (pure logic, no I/O).

Joins ``drives[*].plays`` with closed snap review rows (in-memory ``recommendation_audit``;
JSON exports use ``snap_review_log`` for the same list) via ``linked_actual`` matching.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Any, Dict, List, Mapping, Optional, Tuple

from playcaller.domain import ActualPlayResult
from playcaller.evaluation.audit import situation_bucket
from playcaller.game import Game
from playcaller.session_game_metadata import session_flat_for_normalize
from playcaller.situation import yards_from_own_goal

from .records import NormalizedHistoricalPlay

EXPLOSIVE_GAIN_YARDS = 15


def _coerce_int(x: Any) -> Optional[int]:
    if x is None:
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _coerce_actual_play(play: Any) -> ActualPlayResult:
    if isinstance(play, ActualPlayResult):
        return play
    if isinstance(play, dict):
        names = {f.name for f in fields(ActualPlayResult)}
        return ActualPlayResult(**{k: v for k, v in play.items() if k in names})
    raise TypeError(f"Unexpected play type: {type(play)!r}")


def linked_actual_matches_play(linked: Mapping[str, Any], play: ActualPlayResult) -> bool:
    """
    Whether an audit ``linked_actual`` dict describes this logged play.

    Only compares keys that exist on ``linked_actual`` so older exports stay compatible.
    """
    if not isinstance(linked, Mapping):
        return False
    for key in ("concept_name", "family", "yards_gained", "result_type", "touchdown", "turnover"):
        if key not in linked:
            continue
        lv = linked.get(key)
        pv = getattr(play, key, None)
        if key == "yards_gained":
            if _coerce_int(lv) != _coerce_int(pv):
                return False
        elif key in ("touchdown", "turnover"):
            if bool(lv) != bool(pv):
                return False
        else:
            if str(lv or "") != str(pv or ""):
                return False
    return True


def derive_yardline_100(*, territory: Optional[str], yardline: Optional[int]) -> Optional[int]:
    if territory is None or yardline is None:
        return None
    try:
        return int(yards_from_own_goal(str(territory), int(yardline)))
    except (TypeError, ValueError):
        return None


def derive_field_zone(*, territory: Optional[str], yardline: Optional[int]) -> Optional[str]:
    """Coarse field bucket from ``GameContext`` territory + yardline (1–50) model."""
    if territory is None or yardline is None:
        return None
    try:
        t = str(territory)
        y = int(yardline)
    except (TypeError, ValueError):
        return None
    if t == "opponents" and y <= 20:
        return "red_zone"
    if t == "opponents" and y <= 35:
        return "scoring_range"
    if t == "own" and y <= 15:
        return "backed_up"
    return "open_field"


def derive_distance_bucket(*, down: Optional[int], distance: Optional[int]) -> Optional[str]:
    if down is None or distance is None:
        return None
    try:
        d = int(down)
        dist = int(distance)
    except (TypeError, ValueError):
        return None
    if d == 4:
        return "fourth_down"
    if dist <= 2 and d < 4:
        return "short"
    if dist >= 7:
        return "long"
    return "standard"


def derive_play_success(
    play: ActualPlayResult,
    *,
    down: Optional[int],
    distance: Optional[int],
) -> Optional[bool]:
    """Positive outcome proxy: TD, official first down, or gain ≥ to-go when context known."""
    if play.touchdown or play.first_down:
        return True
    if down is None or distance is None:
        return None
    try:
        gain = int(play.yards_gained)
        to_go = int(distance)
    except (TypeError, ValueError):
        return None
    if to_go <= 0:
        return gain > 0
    return gain >= to_go


def derive_explosive(play: ActualPlayResult) -> bool:
    try:
        return int(play.yards_gained) >= EXPLOSIVE_GAIN_YARDS
    except (TypeError, ValueError):
        return False


def _situation_from_pre(pre: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(pre, dict):
        return {
            "quarter": None,
            "clock_seconds_remaining": None,
            "down": None,
            "distance": None,
            "territory": None,
            "yardline": None,
            "yardline_100": None,
            "field_zone": None,
            "score_diff": None,
            "situation_bucket": None,
            "distance_bucket": None,
        }
    q = _coerce_int(pre.get("quarter"))
    clk = _coerce_int(pre.get("seconds_remaining"))
    down = _coerce_int(pre.get("down"))
    dist = _coerce_int(pre.get("distance"))
    terr = pre.get("territory")
    terr_s = str(terr) if terr is not None else None
    yl = _coerce_int(pre.get("yardline"))
    y100 = derive_yardline_100(territory=terr_s, yardline=yl)
    fz = derive_field_zone(territory=terr_s, yardline=yl)
    sd = _coerce_int(pre.get("score_diff"))
    try:
        sb = situation_bucket(pre) if pre else None
    except (TypeError, ValueError):
        sb = None
    db = derive_distance_bucket(down=down, distance=dist)
    return {
        "quarter": q,
        "clock_seconds_remaining": clk,
        "down": down,
        "distance": dist,
        "territory": terr_s,
        "yardline": yl,
        "yardline_100": y100,
        "field_zone": fz,
        "score_diff": sd,
        "situation_bucket": sb,
        "distance_bucket": db,
    }


def _map_closed_audits_to_plays(game: Game) -> Dict[Tuple[int, int], Dict[str, Any]]:
    """
    Match each logged play to at most one closed audit row (``linked_actual``).

    Greedy in drive/play order; each audit index consumed at most once.
    """
    audits = list(game.recommendation_audit or [])
    candidates: List[Tuple[int, Dict[str, Any]]] = [
        (i, r)
        for i, r in enumerate(audits)
        if isinstance(r, dict) and r.get("status") == "closed" and isinstance(r.get("linked_actual"), dict)
    ]
    used: set[int] = set()
    out: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for di, drive in enumerate(game.drives):
        for pi, play in enumerate(drive.plays):
            play = _coerce_actual_play(play)
            for ai, rec in candidates:
                if ai in used:
                    continue
                linked = rec.get("linked_actual")
                if not isinstance(linked, dict):
                    continue
                if linked_actual_matches_play(linked, play):
                    out[(di, pi)] = rec
                    used.add(ai)
                    break
    return out


def _family_match(recommended: Optional[str], actual_family: str) -> Optional[bool]:
    if not recommended or not str(recommended).strip() or not (actual_family or "").strip():
        return None
    return str(recommended) == str(actual_family)


def _raw_audit_ref(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "snap_id": rec.get("snap_id"),
        "drive_epoch": rec.get("drive_epoch"),
        "plays_at_recommend": rec.get("plays_at_recommend"),
        "status": rec.get("status"),
    }


def build_normalized_plays(
    game: Game,
    *,
    source_path: str = "",
    schema_version: Optional[int] = None,
    game_label: Optional[str] = None,
) -> List[NormalizedHistoricalPlay]:
    """
    One row per logged play in ``game.drives``, enriched from recommendation audit when possible.
    """
    audit_by_play = _map_closed_audits_to_plays(game)
    sess = session_flat_for_normalize(game)
    rows: List[NormalizedHistoricalPlay] = []
    abs_idx = 0
    for di, drive in enumerate(game.drives):
        pt = str(getattr(drive, "possessing_team", "offense") or "offense")
        for pi, play_raw in enumerate(drive.plays):
            play = _coerce_actual_play(play_raw)
            rec = audit_by_play.get((di, pi))
            pre = rec.get("pre_snap") if rec and isinstance(rec.get("pre_snap"), dict) else None
            ctx = _situation_from_pre(pre)

            reco_family = str(rec.get("selected_family") or "") if rec else None
            if reco_family == "":
                reco_family = None
            reco_play = str(rec.get("selected_play_name") or "") if rec else None
            if reco_play == "":
                reco_play = None
            reco_bucket = str(rec.get("bucket") or "") if rec else None
            if reco_bucket == "":
                reco_bucket = None

            down = ctx["down"]
            dist = ctx["distance"]
            success = derive_play_success(play, down=down, distance=dist)
            explosive = derive_explosive(play)

            snap_id = str(rec.get("snap_id")) if rec and rec.get("snap_id") is not None else None
            d_epoch = _coerce_int(rec.get("drive_epoch")) if rec else None
            pat = _coerce_int(rec.get("plays_at_recommend")) if rec else None
            status = str(rec.get("status")) if rec and rec.get("status") is not None else None

            rows.append(
                NormalizedHistoricalPlay(
                    source_path=source_path,
                    game_id=str(game.game_id),
                    game_label=game_label,
                    schema_version=schema_version,
                    drive_index=di,
                    play_index=pi,
                    absolute_snap_index=abs_idx,
                    possessing_team=pt,
                    quarter=ctx["quarter"],
                    clock_seconds_remaining=ctx["clock_seconds_remaining"],
                    down=ctx["down"],
                    distance=ctx["distance"],
                    territory=ctx["territory"],
                    yardline=ctx["yardline"],
                    yardline_100=ctx["yardline_100"],
                    field_zone=ctx["field_zone"],
                    score_diff=ctx["score_diff"],
                    situation_bucket=ctx["situation_bucket"],
                    distance_bucket=ctx["distance_bucket"],
                    audit_snap_id=snap_id,
                    audit_drive_epoch=d_epoch,
                    audit_plays_at_recommend=pat,
                    recommendation_status=status,
                    recommended_family=reco_family,
                    recommended_play_name=reco_play,
                    recommendation_bucket=reco_bucket,
                    family_match=_family_match(reco_family, play.family),
                    actual=play,
                    play_success=success,
                    explosive_play=explosive,
                    raw_audit_ref=_raw_audit_ref(rec) if rec else None,
                    session_game_id=sess["session_game_id"],
                    session_team_name=sess["session_team_name"],
                    session_opponent=sess["session_opponent"],
                    session_game_date=sess["session_game_date"],
                    session_game_label=sess["session_game_label"],
                    session_season=sess["session_season"],
                    session_roster_version=sess["session_roster_version"],
                    session_is_simulated=sess["session_is_simulated"],
                )
            )
            abs_idx += 1
    return rows

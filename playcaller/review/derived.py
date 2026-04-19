"""
Pure helpers to turn ``Game.recommendation_audit`` rows into review-friendly structures.

Keeps parsing/derivation out of Streamlit pages so the same builders can back
offline JSON review and (later) live-session review.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from playcaller.actual_result import format_actual_play_result_description
from playcaller.domain import ActualPlayResult, FG_RANGE_YARDLINE
from playcaller.evaluation.audit import situation_bucket
from playcaller.evaluation.metrics import (
    EXPLOSIVE_GAIN_YARD_THRESHOLD,
    actual_fields_is_explosive,
    actual_fields_is_turnover,
)
from playcaller.game import Game
from playcaller.history.normalize import derive_field_zone, derive_yardline_100
from playcaller.ui.review_helpers import format_clock_line, format_scrimmage_line, humanize_situation_bucket


def linked_actual_to_play(linked: Mapping[str, Any]) -> ActualPlayResult:
    """Build ``ActualPlayResult`` from an audit ``linked_actual`` dict (JSON-safe)."""
    names = {f.name for f in fields(ActualPlayResult)}
    return ActualPlayResult(**{k: v for k, v in linked.items() if k in names})


def format_situation_line(pre: Mapping[str, Any]) -> str:
    """Single readable line: down & distance, field, clock."""
    if not pre:
        return ""
    try:
        dn = int(pre.get("down", 1))
    except (TypeError, ValueError):
        dn = 1
    try:
        dist = int(pre.get("distance", 10))
    except (TypeError, ValueError):
        dist = 10
    los = format_scrimmage_line(pre)
    clk = format_clock_line(pre)
    return f"{dn} & {dist} · {los} · {clk}"


def format_field_position_sentence(pre: Mapping[str, Any]) -> str:
    """Narrative field context including goal-to-go style phrasing when distance ≥ yardline in opp territory."""
    if not pre:
        return ""
    terr = str(pre.get("territory", "own"))
    try:
        yl = int(pre.get("yardline", 25))
    except (TypeError, ValueError):
        yl = 25
    try:
        dist = int(pre.get("distance", 10))
    except (TypeError, ValueError):
        dist = 10
    side = "Own" if terr == "own" else "Opponent"
    y100 = derive_yardline_100(territory=terr, yardline=yl)
    zone = derive_field_zone(territory=terr, yardline=yl) or ""
    parts = [f"{side} {yl}"]
    if y100 is not None:
        parts.append(f"({y100} yds from own goal)")
    if zone == "red_zone":
        parts.append("red zone")
        if terr == "opponents" and dist >= yl:
            parts.append(f"goal-to-go (~{yl} yd line)")
    elif zone == "scoring_range" and terr == "opponents" and yl <= FG_RANGE_YARDLINE:
        parts.append("FG range")
    return " · ".join(parts)


def format_play_result_label(actual: Mapping[str, Any]) -> str:
    """
    Short result label: result type + yards + key flags (not a full broadcast sentence).

    Uses ``format_actual_play_result_description`` when a full ``ActualPlayResult`` can be built.
    """
    if not isinstance(actual, Mapping) or not actual:
        return "—"
    try:
        ap = linked_actual_to_play(actual)
        base = format_actual_play_result_description(ap)
    except (TypeError, ValueError):
        base = ""
    if not base:
        rt = str(actual.get("result_type") or "").replace("_", " ").strip() or "—"
        try:
            yds = int(actual.get("yards_gained", 0))
        except (TypeError, ValueError):
            yds = 0
        base = f"{rt} ({yds:+d} yd)" if rt != "—" else f"{yds:+d} yd"
    badges: List[str] = []
    if actual_fields_is_explosive(actual):
        badges.append("explosive")
    if actual_fields_is_turnover(actual):
        badges.append("turnover")
    if bool(actual.get("touchdown")):
        badges.append("TD")
    if bool(actual.get("sack")) or str(actual.get("pass_result", "")).lower() == "sack":
        badges.append("sack")
    rt_lower = str(actual.get("result_type", "")).lower()
    if rt_lower in ("field_goal",):
        badges.append("FG")
    if rt_lower in ("field_goal_miss",):
        badges.append("FG miss")
    if str(actual.get("play_type", "")).lower() == "two_point" and not bool(actual.get("touchdown")):
        badges.append("failed 2PT")
    if badges:
        return f"{base} · " + ", ".join(badges)
    return base


def _pre_dict(row: Mapping[str, Any]) -> Dict[str, Any]:
    pre = row.get("pre_snap")
    return dict(pre) if isinstance(pre, dict) else {}


def _actual_dict(row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    act = row.get("linked_actual")
    return dict(act) if isinstance(act, dict) else None


def _is_red_zone(pre: Mapping[str, Any]) -> bool:
    return str(pre.get("territory")) == "opponents" and _safe_int(pre.get("yardline"), 99) <= 20


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ReviewPlaySnapshot:
    """One audit row with review-oriented flags and formatted context."""

    audit_index: int
    snap_id: str
    drive_epoch: int
    status: str
    situation_line: str
    field_sentence: str
    situation_bucket: str
    situation_bucket_label: str
    is_red_zone: bool
    is_third_down: bool
    is_fourth_down: bool
    is_two_minute: bool
    is_short_clock: bool
    reco_family: str
    reco_play_name: str
    outcome_line: Optional[str]
    outcome_detail: Optional[str]
    flags: Tuple[str, ...]
    family_match: Optional[bool]


def _snapshot_flags(
    *,
    pre: Mapping[str, Any],
    act: Optional[Mapping[str, Any]],
    family_match: Optional[bool],
) -> Tuple[str, ...]:
    out: List[str] = []
    if _is_red_zone(pre):
        out.append("red_zone")
    if _safe_int(pre.get("down"), 1) == 3:
        out.append("3rd_down")
    if _safe_int(pre.get("down"), 1) == 4:
        out.append("4th_down")
    gm = str(pre.get("game_mode", "")).lower()
    if gm == "two_minute":
        out.append("two_minute")
    if _safe_int(pre.get("seconds_remaining"), 99999) <= 120:
        out.append("under_2_min_clock")
    if isinstance(act, Mapping):
        if actual_fields_is_explosive(act):
            out.append("explosive")
        if actual_fields_is_turnover(act):
            out.append("turnover")
        if bool(act.get("touchdown")):
            out.append("touchdown")
        if bool(act.get("sack")) or str(act.get("pass_result", "")).lower() == "sack":
            out.append("sack")
        rt = str(act.get("result_type", "")).lower()
        if rt in ("field_goal",):
            out.append("field_goal")
        if rt in ("field_goal_miss",):
            out.append("fg_miss")
        if str(act.get("play_type", "")).lower() == "two_point":
            out.append("two_point_try")
            if not bool(act.get("touchdown")):
                out.append("failed_conversion")
        if bool(act.get("first_down")):
            out.append("first_down")
    if family_match is True:
        out.append("family_match")
    if family_match is False:
        out.append("family_mismatch")
    return tuple(out)


def _family_match_row(row: Mapping[str, Any]) -> Optional[bool]:
    act = row.get("linked_actual")
    if not isinstance(act, dict):
        return None
    af = str(act.get("family", "") or "")
    sf = str(row.get("selected_family", "") or "")
    if not af or not sf:
        return None
    return af == sf


def build_play_snapshots(audit: Sequence[Mapping[str, Any]]) -> List[ReviewPlaySnapshot]:
    snaps: List[ReviewPlaySnapshot] = []
    for i, row in enumerate(audit):
        pre = _pre_dict(row)
        act = _actual_dict(row)
        sb = situation_bucket(pre) if pre else ""
        fm = _family_match_row(row)
        outcome_line: Optional[str] = None
        outcome_detail: Optional[str] = None
        if act:
            outcome_line = format_play_result_label(act)
            try:
                outcome_detail = format_actual_play_result_description(linked_actual_to_play(act))
            except (TypeError, ValueError):
                outcome_detail = outcome_line
        snaps.append(
            ReviewPlaySnapshot(
                audit_index=i,
                snap_id=str(row.get("snap_id", "") or ""),
                drive_epoch=_safe_int(row.get("drive_epoch"), 0),
                status=str(row.get("status", "") or ""),
                situation_line=format_situation_line(pre),
                field_sentence=format_field_position_sentence(pre),
                situation_bucket=sb,
                situation_bucket_label=humanize_situation_bucket(sb) if sb else "",
                is_red_zone=_is_red_zone(pre) if pre else False,
                is_third_down=_safe_int(pre.get("down"), 1) == 3 if pre else False,
                is_fourth_down=_safe_int(pre.get("down"), 1) == 4 if pre else False,
                is_two_minute=str(pre.get("game_mode", "")).lower() == "two_minute" if pre else False,
                is_short_clock=_safe_int(pre.get("seconds_remaining"), 9999) <= 120 if pre else False,
                reco_family=str(row.get("selected_family", "") or ""),
                reco_play_name=str(row.get("selected_play_name", "") or ""),
                outcome_line=outcome_line,
                outcome_detail=outcome_detail,
                flags=_snapshot_flags(pre=pre, act=act, family_match=fm),
                family_match=fm,
            )
        )
    return snaps


@dataclass
class DriveReviewSummary:
    """Aggregates for one ``drive_epoch`` (all audit rows on that drive)."""

    drive_epoch: int
    audit_indices: Tuple[int, ...]
    snap_count: int
    closed_count: int
    explosive_count: int
    turnover_count: int
    sack_count: int
    touchdown_count: int
    field_goal_count: int
    red_zone_snap_count: int
    third_down_snap_count: int
    fourth_down_snap_count: int
    total_yards_logged: int
    first_quarter: Optional[int]
    last_quarter: Optional[int]
    first_clock_seconds: Optional[int]
    last_clock_seconds: Optional[int]
    headline: str
    detail: str
    logged_drive_result: Optional[str]


def _game_drive_headline(game: Game, drive_epoch: int) -> Optional[str]:
    if drive_epoch < 0 or drive_epoch >= len(game.drives):
        return None
    dr = game.drives[drive_epoch].result
    if dr is None:
        return None
    return f"{dr.headline} — {dr.detail_line}"


def build_drive_summaries(game: Game, audit: Sequence[Mapping[str, Any]]) -> List[DriveReviewSummary]:
    snaps = build_play_snapshots(audit)
    by_epoch: Dict[int, List[ReviewPlaySnapshot]] = {}
    for s in snaps:
        by_epoch.setdefault(s.drive_epoch, []).append(s)

    order = sorted(by_epoch.keys(), key=lambda e: min(sn.audit_index for sn in by_epoch[e]))
    out: List[DriveReviewSummary] = []
    for epoch in order:
        group = sorted(by_epoch[epoch], key=lambda s: s.audit_index)
        indices = tuple(s.audit_index for s in group)
        closed = sum(1 for s in group if s.status == "closed")
        pre_list = [_pre_dict(audit[s.audit_index]) for s in group]
        quarters = [_safe_int(p.get("quarter"), 0) for p in pre_list if p]
        clocks = [_safe_int(p.get("seconds_remaining"), 0) for p in pre_list if p]
        explosive = sum(1 for s in group if "explosive" in s.flags)
        tov = sum(1 for s in group if "turnover" in s.flags)
        sacks = sum(1 for s in group if "sack" in s.flags)
        tds = sum(1 for s in group if "touchdown" in s.flags)
        fgs = sum(1 for s in group if "field_goal" in s.flags)
        rz = sum(1 for s in group if s.is_red_zone)
        d3 = sum(1 for s in group if s.is_third_down)
        d4 = sum(1 for s in group if s.is_fourth_down)

        yards = 0
        for s in group:
            act = _actual_dict(audit[s.audit_index])
            if act:
                yards += _safe_int(act.get("yards_gained"), 0)

        first_q = min(quarters) if quarters else None
        last_q = max(quarters) if quarters else None
        first_clk = min(clocks) if clocks else None
        last_clk = max(clocks) if clocks else None

        logged = _game_drive_headline(game, epoch)
        headline = f"Drive {epoch}"
        detail_parts = [
            f"{len(group)} engine call{'s' if len(group) != 1 else ''}",
            f"{closed} with logged result" if closed else "no linked outcomes yet",
        ]
        if explosive:
            detail_parts.append(f"{explosive} explosive")
        if tov:
            detail_parts.append(f"{tov} turnover(s)")
        if tds:
            detail_parts.append(f"{tds} TD")
        if fgs:
            detail_parts.append(f"{fgs} FG")
        if rz:
            detail_parts.append(f"{rz} RZ snap(s)")
        detail = " · ".join(detail_parts)

        out.append(
            DriveReviewSummary(
                drive_epoch=epoch,
                audit_indices=indices,
                snap_count=len(group),
                closed_count=closed,
                explosive_count=explosive,
                turnover_count=tov,
                sack_count=sacks,
                touchdown_count=tds,
                field_goal_count=fgs,
                red_zone_snap_count=rz,
                third_down_snap_count=d3,
                fourth_down_snap_count=d4,
                total_yards_logged=yards,
                first_quarter=first_q,
                last_quarter=last_q,
                first_clock_seconds=first_clk,
                last_clock_seconds=last_clk,
                headline=headline,
                detail=detail,
                logged_drive_result=logged,
            )
        )
    return out


@dataclass(frozen=True)
class KeyMoment:
    kind: str
    audit_index: int
    drive_epoch: int
    headline: str
    detail: str


def derive_key_moments(audit: Sequence[Mapping[str, Any]]) -> List[KeyMoment]:
    """High-signal swings derived from audit rows (closed rows preferred for outcomes)."""
    moments: List[KeyMoment] = []
    snaps = build_play_snapshots(audit)

    for s in snaps:
        pre = _pre_dict(audit[s.audit_index])
        act = _actual_dict(audit[s.audit_index])

        if act and actual_fields_is_turnover(act):
            moments.append(
                KeyMoment(
                    kind="turnover",
                    audit_index=s.audit_index,
                    drive_epoch=s.drive_epoch,
                    headline="Turnover",
                    detail=f"{format_situation_line(pre)} → {format_play_result_label(act)}",
                )
            )
        elif act and bool(act.get("touchdown")):
            moments.append(
                KeyMoment(
                    kind="touchdown",
                    audit_index=s.audit_index,
                    drive_epoch=s.drive_epoch,
                    headline="Touchdown",
                    detail=f"{format_situation_line(pre)} → {format_play_result_label(act)}",
                )
            )
        elif act and str(act.get("result_type", "")).lower() in ("field_goal",):
            moments.append(
                KeyMoment(
                    kind="score",
                    audit_index=s.audit_index,
                    drive_epoch=s.drive_epoch,
                    headline="Field goal",
                    detail=f"{format_situation_line(pre)} → {format_play_result_label(act)}",
                )
            )
        elif act and actual_fields_is_explosive(act):
            moments.append(
                KeyMoment(
                    kind="explosive",
                    audit_index=s.audit_index,
                    drive_epoch=s.drive_epoch,
                    headline=f"Explosive (+{EXPLOSIVE_GAIN_YARD_THRESHOLD}+)",
                    detail=f"{format_situation_line(pre)} → {format_play_result_label(act)}",
                )
            )
        elif act and (
            bool(act.get("sack")) or str(act.get("pass_result", "")).lower() == "sack"
        ):
            moments.append(
                KeyMoment(
                    kind="sack",
                    audit_index=s.audit_index,
                    drive_epoch=s.drive_epoch,
                    headline="Sack",
                    detail=f"{format_situation_line(pre)} → {format_play_result_label(act)}",
                )
            )
        elif s.is_fourth_down and act:
            # Highlight 4th-down outcomes (decision point).
            gained = _safe_int(act.get("yards_gained"), 0)
            fd = bool(act.get("first_down"))
            if not fd and gained < _safe_int(pre.get("distance"), 10):
                label = "Short of line" if not actual_fields_is_turnover(act) else "Turnover"
            else:
                label = "Converted" if fd or bool(act.get("touchdown")) else "Result"
            moments.append(
                KeyMoment(
                    kind="fourth_down",
                    audit_index=s.audit_index,
                    drive_epoch=s.drive_epoch,
                    headline=f"4th down · {label}",
                    detail=f"{format_situation_line(pre)} → {format_play_result_label(act)}",
                )
            )

    # Score / momentum swings: compare consecutive closed snaps' pre_snap score_diff.
    prev_diff: Optional[int] = None
    prev_idx: Optional[int] = None
    for i, row in enumerate(audit):
        if row.get("status") != "closed":
            continue
        pre = _pre_dict(row)
        try:
            diff = int(pre.get("score_diff", 0))
        except (TypeError, ValueError):
            diff = 0
        if prev_diff is not None and prev_idx is not None and diff != prev_diff:
            delta = diff - prev_diff
            if abs(delta) >= 8 or (abs(delta) >= 1 and i - prev_idx <= 2):
                moments.append(
                    KeyMoment(
                        kind="momentum",
                        audit_index=i,
                        drive_epoch=_safe_int(row.get("drive_epoch"), 0),
                        headline="Score margin shifted",
                        detail=f"Score diff {prev_diff:+d} → {diff:+d} (Δ {delta:+d}) before {format_situation_line(pre)}",
                    )
                )
        prev_diff = diff
        prev_idx = i

    # De-dupe (kind, audit_index); keep stable snap order.
    seen: set = set()
    deduped: List[KeyMoment] = []
    for m in sorted(moments, key=lambda x: (x.audit_index, x.kind)):
        k = (m.kind, m.audit_index)
        if k in seen:
            continue
        seen.add(k)
        deduped.append(m)
    return deduped


def play_by_play_lines(
    audit: Sequence[Mapping[str, Any]],
    *,
    drive_epoch: Optional[int] = None,
) -> List[str]:
    """Compact one-line strings for a drive or full game."""
    snaps = build_play_snapshots(audit)
    lines: List[str] = []
    for s in snaps:
        if drive_epoch is not None and s.drive_epoch != drive_epoch:
            continue
        n = s.audit_index + 1
        tag = "●" if s.status == "closed" else "○"
        res = s.outcome_line or "—"
        lines.append(f"{tag} Snap {n} · {s.situation_line} · Reco {s.reco_family or '—'} → {res}")
    return lines


@dataclass
class ReviewFilter:
    """Optional UI filters; empty lists mean 'any'."""

    require_closed: bool = False
    tags_any: Tuple[str, ...] = ()

    def active(self) -> bool:
        return bool(self.require_closed or self.tags_any)


def matching_audit_indices(snaps: Sequence[ReviewPlaySnapshot], flt: ReviewFilter) -> List[int]:
    if not flt.active():
        return [s.audit_index for s in snaps]
    out: List[int] = []
    for s in snaps:
        if flt.require_closed and s.status != "closed":
            continue
        if flt.tags_any:
            if not any(t in s.flags for t in flt.tags_any):
                continue
        out.append(s.audit_index)
    return out


def pattern_bullets_from_snapshots(snaps: Sequence[ReviewPlaySnapshot]) -> List[str]:
    """Short tendency lines for the Patterns section (audit-weighted, not full game charting)."""
    if not snaps:
        return []
    closed = [s for s in snaps if s.status == "closed"]
    bullets: List[str] = []
    if closed:
        rz_closed = [s for s in closed if s.is_red_zone]
        if len(rz_closed) >= 2:
            passes = sum(
                1
                for s in rz_closed
                if str(s.reco_family or "") in {"quick_game", "dropback_pass", "screen", "play_action", "fade_iso"}
            )
            bullets.append(
                f"Red zone: **{len(rz_closed)}** logged snap(s); **{passes}** featured a pass-family recommendation."
            )
        d3 = [s for s in closed if s.is_third_down]
        if len(d3) >= 2:
            conv = sum(1 for s in d3 if "first_down" in s.flags or "touchdown" in s.flags)
            bullets.append(
                f"Third down (logged): **{conv}** of **{len(d3)}** snaps moved the chains or scored."
            )
        expl = sum(1 for s in closed if "explosive" in s.flags)
        if expl:
            bullets.append(f"Explosive gains on **{expl}** logged snap(s) (≥{EXPLOSIVE_GAIN_YARD_THRESHOLD} yds).")
    d4 = [s for s in snaps if s.is_fourth_down]
    if len(d4) >= 1:
        bullets.append(f"**{len(d4)}** fourth-down recommendation(s) — review decision points in Key moments / filters.")
    return bullets

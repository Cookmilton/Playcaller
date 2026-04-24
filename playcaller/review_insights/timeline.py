"""
Drive timeline + momentum annotations (reconciled drives only; deterministic).

UI should call :func:`build_game_flow` once per render — no insight math in Streamlit layout.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import List, Literal, Optional, Sequence, Tuple

from playcaller.game import (
    DRIVE_END_FIELD_GOAL,
    DRIVE_END_FIELD_GOAL_MISS,
    DRIVE_END_PUNT,
    DRIVE_END_TOUCHDOWN,
    DRIVE_END_TURNOVER_FUMBLE,
    DRIVE_END_TURNOVER_INT,
    DRIVE_END_TURNOVER_ON_DOWNS,
    Drive,
    Game,
)
from playcaller.live_data.drive_display import classify_drive_team_side, drive_identity_key
from playcaller.reconciliation.drive_reconciler import ReconciledDrive, reconcile_drive

# Momentum overlays suppressed when the session is too short to be structurally meaningful.
MIN_DRIVES_FOR_MOMENTUM = 8

# Detection thresholds (spec)
MIN_SCORING_RUN_LEN = 3
MIN_DROUGHT_LEN = 4

OutcomeStyle = Literal["score", "turnover", "punt", "half", "miss", "other"]


@dataclass(frozen=True)
class DriveRange:
    start_drive: int  # 1-based game drive index (inclusive)
    end_drive: int  # 1-based inclusive
    team: str
    label: str
    points_scored: int


@dataclass(frozen=True)
class TurningPoint:
    drive_number: int  # 1-based
    category: Literal["response", "post_turnover", "4min_drill"]
    label: str


@dataclass(frozen=True)
class GameFlowTimelineRow:
    drive_number: int  # 1-based
    team_abbr: str
    team_key: str
    outcome_short: str
    outcome_style: OutcomeStyle
    plays: int
    yards: int
    top_display: str
    score_display: str  # coached perspective "ours–theirs"
    net_yards_for_bar: int


@dataclass(frozen=True)
class GameFlowBundle:
    rows: Tuple[GameFlowTimelineRow, ...]
    scoring_runs: Tuple[DriveRange, ...]
    droughts: Tuple[DriveRange, ...]
    turning_points: Tuple[TurningPoint, ...]
    momentum_suppressed: bool


def _safe_abbr(dr: Drive) -> str:
    ab = str(getattr(dr, "feed_team_abbr", "") or "").strip().upper()
    if ab:
        return ab
    return "OUR" if dr.possessing_team == "offense" else "OPP"


def _team_abbr_for_key(game: Game, key: str) -> str:
    for dr in game.drives:
        if drive_identity_key(dr) == key:
            return _safe_abbr(dr)
    return "TEAM"


def _reconcile_all(game: Game) -> List[ReconciledDrive]:
    return [reconcile_drive(d, espn=d.feed_audit) for d in game.drives]


def _is_end_half(rec: ReconciledDrive) -> bool:
    return (rec.espn_coarse_bucket or "").upper() == "END_HALF"


def _is_scoring_drive(rec: ReconciledDrive) -> bool:
    if _is_end_half(rec):
        return False
    return rec.outcome_kind in (DRIVE_END_TOUCHDOWN, DRIVE_END_FIELD_GOAL)


def _is_drought_drive(rec: ReconciledDrive) -> bool:
    """Non-scoring ending in punt or turnover (and missed FG); not end of half."""
    if _is_end_half(rec):
        return False
    return rec.outcome_kind in (
        DRIVE_END_PUNT,
        DRIVE_END_TURNOVER_INT,
        DRIVE_END_TURNOVER_FUMBLE,
        DRIVE_END_TURNOVER_ON_DOWNS,
        DRIVE_END_FIELD_GOAL_MISS,
    )


def _outcome_style(rec: ReconciledDrive) -> OutcomeStyle:
    if _is_end_half(rec):
        return "half"
    k = rec.outcome_kind
    if k in (DRIVE_END_TOUCHDOWN, DRIVE_END_FIELD_GOAL):
        return "score"
    if k in (
        DRIVE_END_TURNOVER_INT,
        DRIVE_END_TURNOVER_FUMBLE,
        DRIVE_END_TURNOVER_ON_DOWNS,
    ):
        return "turnover"
    if k == DRIVE_END_PUNT:
        return "punt"
    if k == DRIVE_END_FIELD_GOAL_MISS:
        return "miss"
    return "other"


def _outcome_short(rec: ReconciledDrive) -> str:
    if _is_end_half(rec):
        return "End half"
    k = rec.outcome_kind
    if k == DRIVE_END_TOUCHDOWN:
        return "TD"
    if k == DRIVE_END_FIELD_GOAL:
        return "FG"
    if k == DRIVE_END_FIELD_GOAL_MISS:
        return "FG miss"
    if k == DRIVE_END_PUNT:
        return "Punt"
    if k == DRIVE_END_TURNOVER_INT:
        return "INT"
    if k == DRIVE_END_TURNOVER_FUMBLE:
        return "Fumble"
    if k == DRIVE_END_TURNOVER_ON_DOWNS:
        return "Downs"
    return rec.outcome_headline[:18] if rec.outcome_headline else "—"


def detect_scoring_runs(game: Game) -> List[DriveRange]:
    """Same team, consecutive game drives, each ending TD/FG — length >= 3."""
    drives = game.drives
    recs = _reconcile_all(game)
    n = len(recs)
    if n < MIN_SCORING_RUN_LEN:
        return []
    keys = [drive_identity_key(d) for d in drives]
    out: List[DriveRange] = []
    i = 0
    while i < n:
        if not _is_scoring_drive(recs[i]):
            i += 1
            continue
        tk = keys[i]
        j = i
        while (
            j < n
            and keys[j] == tk
            and _is_scoring_drive(recs[j])
            and not _is_end_half(recs[j])
        ):
            j += 1
        if j - i >= MIN_SCORING_RUN_LEN:
            pts = sum(recs[k].possession_points for k in range(i, j))
            abbr = _team_abbr_for_key(game, tk)
            a, b = i + 1, j
            out.append(
                DriveRange(
                    start_drive=a,
                    end_drive=b,
                    team=abbr,
                    label=f"{abbr} scoring run (drives {a}–{b}, {pts} pts)",
                    points_scored=int(pts),
                )
            )
        i = j if j > i else i + 1
    return out


def detect_droughts(game: Game) -> List[DriveRange]:
    """Same team, consecutive drives ending punt / turnover / FG miss — length >= 4."""
    recs = _reconcile_all(game)
    drives = game.drives
    n = len(recs)
    if n < MIN_DROUGHT_LEN:
        return []
    keys = [drive_identity_key(d) for d in drives]
    out: List[DriveRange] = []
    i = 0
    while i < n:
        if not _is_drought_drive(recs[i]):
            i += 1
            continue
        tk = keys[i]
        j = i
        while j < n and keys[j] == tk and _is_drought_drive(recs[j]):
            j += 1
        if j - i >= MIN_DROUGHT_LEN:
            abbr = _team_abbr_for_key(game, tk)
            a, b = i + 1, j
            out.append(
                DriveRange(
                    start_drive=a,
                    end_drive=b,
                    team=abbr,
                    label=f"{abbr} drought (drives {a}–{b})",
                    points_scored=0,
                )
            )
        i = j if j > i else i + 1
    return out


def detect_turning_points(game: Game, *, our_coached_espn_id: str) -> List[TurningPoint]:
    """
    Uses running score before each drive (coached-team perspective) + reconciled outcomes.
    """
    drives = game.drives
    recs = _reconcile_all(game)
    n = len(recs)
    out: List[TurningPoint] = []
    our_pts, opp_pts = 0, 0
    first_q4_idx: Optional[int] = None

    for i in range(n):
        rec = recs[i]
        dr = drives[i]
        if first_q4_idx is None and rec.start_quarter >= 4:
            first_q4_idx = i

        margin_before = our_pts - opp_pts
        if i > 0:
            prev = recs[i - 1]
            prev_dr = drives[i - 1]
            prev_key = drive_identity_key(prev_dr)
            cur_key = drive_identity_key(dr)

            # Response: previous drive scored (TD/FG) and this drive goes to the other team
            if _is_scoring_drive(prev) and not _is_end_half(prev) and prev_key != cur_key:
                scorer = _safe_abbr(prev_dr)
                out.append(
                    TurningPoint(
                        drive_number=i + 1,
                        category="response",
                        label=f"Response drive after {scorer} score",
                    )
                )

            # Post-turnover possession
            if prev.outcome_kind in (
                DRIVE_END_TURNOVER_INT,
                DRIVE_END_TURNOVER_FUMBLE,
                DRIVE_END_TURNOVER_ON_DOWNS,
            ) and prev_key != cur_key:
                out.append(
                    TurningPoint(
                        drive_number=i + 1,
                        category="post_turnover",
                        label="Possession after turnover",
                    )
                )

        # One “late / one-score” anchor per game: first drive whose reconciled start is Q4+.
        if first_q4_idx is not None and i == first_q4_idx and abs(margin_before) <= 8:
            out.append(
                TurningPoint(
                    drive_number=i + 1,
                    category="4min_drill",
                    label="Late-game drive inside one score",
                )
            )

        # Advance scoreboard after this drive
        side = classify_drive_team_side(dr, our_coached_espn_id=our_coached_espn_id)
        pts = int(rec.possession_points or 0)
        if side == "our":
            our_pts += pts
        elif side == "opp":
            opp_pts += pts
        else:
            if dr.possessing_team == "offense":
                our_pts += pts
            else:
                opp_pts += pts

    # De-dupe same drive + category (4th quarter can duplicate with others — keep first pass)
    seen: set[tuple[int, str]] = set()
    deduped: List[TurningPoint] = []
    for tp in out:
        key = (tp.drive_number, tp.category)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(tp)
    return deduped


def _running_scores(game: Game, recs: Sequence[ReconciledDrive], *, our_coached_espn_id: str) -> List[Tuple[int, int]]:
    """Cumulative (our_pts, opp_pts) after each drive."""
    our_pts, opp_pts = 0, 0
    rows: List[Tuple[int, int]] = []
    for i, dr in enumerate(game.drives):
        rec = recs[i]
        side = classify_drive_team_side(dr, our_coached_espn_id=our_coached_espn_id)
        pts = int(rec.possession_points or 0)
        if side == "our":
            our_pts += pts
        elif side == "opp":
            opp_pts += pts
        else:
            if dr.possessing_team == "offense":
                our_pts += pts
            else:
                opp_pts += pts
        rows.append((our_pts, opp_pts))
    return rows


def build_game_flow(game: Game, *, our_coached_espn_id: str) -> GameFlowBundle:
    """
    Full timeline rows + momentum payload. Always returns one row per drive.

    When ``len(drives) < MIN_DRIVES_FOR_MOMENTUM``, momentum lists are empty (timeline still populated).
    """
    drives = game.drives
    recs = _reconcile_all(game)
    scores = _running_scores(game, recs, our_coached_espn_id=our_coached_espn_id)

    rows: List[GameFlowTimelineRow] = []
    for i, dr in enumerate(drives):
        rec = recs[i]
        ou, de = scores[i]
        rows.append(
            GameFlowTimelineRow(
                drive_number=i + 1,
                team_abbr=_safe_abbr(dr),
                team_key=drive_identity_key(dr),
                outcome_short=_outcome_short(rec),
                outcome_style=_outcome_style(rec),
                plays=int(rec.plays),
                yards=int(rec.yards),
                top_display=rec.time_of_possession_display or "—",
                score_display=f"{ou}–{de}",
                net_yards_for_bar=max(0, int(rec.yards)),
            )
        )

    n_drv = len(drives)
    short = n_drv < MIN_DRIVES_FOR_MOMENTUM
    if short:
        return GameFlowBundle(
            rows=tuple(rows),
            scoring_runs=(),
            droughts=(),
            turning_points=(),
            momentum_suppressed=True,
        )

    return GameFlowBundle(
        rows=tuple(rows),
        scoring_runs=tuple(detect_scoring_runs(game)),
        droughts=tuple(detect_droughts(game)),
        turning_points=tuple(detect_turning_points(game, our_coached_espn_id=our_coached_espn_id)),
        momentum_suppressed=False,
    )


def row_momentum_strip_class(drive_number: int, bundle: GameFlowBundle) -> str:
    """Left-edge strip for table rows (scoring run overrides drought)."""
    if bundle.momentum_suppressed:
        return ""
    for r in bundle.scoring_runs:
        if r.start_drive <= drive_number <= r.end_drive:
            return "gfm-strip-run"
    for d in bundle.droughts:
        if d.start_drive <= drive_number <= d.end_drive:
            return "gfm-strip-drought"
    return ""


def turning_point_badges_for_drive(drive_number: int, bundle: GameFlowBundle) -> Tuple[TurningPoint, ...]:
    return tuple(tp for tp in bundle.turning_points if tp.drive_number == drive_number)


def timeline_momentum_annotations_html(
    bundle: GameFlowBundle,
) -> str:
    """Compact caption block for momentum (no drive math in UI)."""
    if bundle.momentum_suppressed:
        return "<p style='color:#64748b;font-size:12px;margin:0 0 8px 0'>Momentum highlights hidden — fewer than 8 drives.</p>"
    parts: List[str] = []
    for r in bundle.scoring_runs:
        parts.append(
            f"<div style='font-size:12px;color:#22c55e;margin:2px 0'><strong>↑</strong> {html.escape(r.label)}</div>"
        )
    for d in bundle.droughts:
        parts.append(
            f"<div style='font-size:12px;color:#94a3b8;margin:2px 0'><strong>↓</strong> {html.escape(d.label)}</div>"
        )
    if not parts:
        return ""
    return "<div style='margin:0 0 10px 0'>" + "".join(parts) + "</div>"


def game_flow_section_html(game: Game, bundle: GameFlowBundle, *, our_coached_espn_id: str) -> str:
    """Table + compact SVG strip (analytics layer — Streamlit passes through ``unsafe_allow_html``)."""
    lines: List[str] = [
        "<style>",
        ".gfm-wrap{font-family:system-ui,Segoe UI,sans-serif;font-size:13px;color:#e2e8f0;}",
        ".gfm-table{width:100%;border-collapse:collapse;margin:6px 0 4px 0;}",
        ".gfm-th{text-align:left;color:#94a3b8;font-size:11px;font-weight:600;padding:6px 8px;border-bottom:1px solid #334155;}",
        ".gfm-td{padding:5px 8px;border-bottom:1px solid #1e293b;vertical-align:middle;}",
        ".gfm-num{color:#64748b;font-size:12px;min-width:2.2em;}",
        ".gfm-mono{color:#94a3b8;font-size:12px;text-align:right;white-space:nowrap;}",
        ".gfm-strip-run{border-left:4px solid #22c55e;padding-left:8px;}",
        ".gfm-strip-drought{border-left:4px solid #475569;padding-left:8px;}",
        ".gfm-chip{display:inline-block;padding:2px 7px;border-radius:999px;font-size:11px;font-weight:600;}",
        ".gfm-chip-our{background:#1e3a8a;color:#93c5fd;}",
        ".gfm-chip-opp{background:#78350f;color:#fcd34d;}",
        ".gfm-chip-unk{background:#334155;color:#cbd5e1;}",
        ".gfm-dot{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px;vertical-align:middle;}",
        ".gfm-out-score{color:#4ade80;font-weight:600;}",
        ".gfm-out-to{color:#f87171;font-weight:600;}",
        ".gfm-out-punt{color:#94a3b8;font-weight:600;}",
        ".gfm-out-half{color:#eab308;font-weight:600;}",
        ".gfm-out-other{color:#cbd5e1;font-weight:600;}",
        "</style>",
        "<div class='gfm-wrap'>",
        timeline_momentum_annotations_html(bundle),
        f"<div style='max-height:118px;overflow:hidden'>{game_flow_bar_chart_svg(bundle.rows)}</div>",
        "<table class='gfm-table'><thead><tr>",
        "<th class='gfm-th gfm-num'>Drive</th>",
        "<th class='gfm-th'>Poss</th>",
        "<th class='gfm-th'>Outcome</th>",
        "<th class='gfm-mono gfm-th' style='text-align:right'>Plays · Yds · TOP</th>",
        "<th class='gfm-mono gfm-th' style='text-align:right'>Score</th>",
        "</tr></thead><tbody>",
    ]

    def dot_class(st: OutcomeStyle) -> str:
        return {
            "score": "gfm-out-score",
            "turnover": "gfm-out-to",
            "punt": "gfm-out-punt",
            "half": "gfm-out-half",
            "miss": "gfm-out-other",
            "other": "gfm-out-other",
        }[st]

    for row in bundle.rows:
        i = row.drive_number
        dr = game.drives[i - 1]
        side = classify_drive_team_side(dr, our_coached_espn_id=our_coached_espn_id)
        chip = "gfm-chip-unk"
        if side == "our":
            chip = "gfm-chip-our"
        elif side == "opp":
            chip = "gfm-chip-opp"
        strip = row_momentum_strip_class(i, bundle)
        tr_cls = f"gfm-td {strip}" if strip else "gfm-td"
        outcome_cls = dot_class(row.outcome_style)
        line_bits = (
            f"{row.plays} · {row.yards} · {html.escape(row.top_display)}"
        )
        bad = turning_point_badges_for_drive(i, bundle)
        badge_html = ""
        if bad:
            lbls = []
            for tp in bad:
                lbls.append(f"<span style='font-size:11px;color:#38bdf8;margin-left:6px'>⚡ {html.escape(tp.label)}</span>")
            badge_html = "".join(lbls)
        lines.append(
            f"<tr><td class='{tr_cls} gfm-num' rowspan='1'>{i}</td>"
            f"<td class='{tr_cls}'><span class='gfm-chip {chip}'>{html.escape(row.team_abbr)}</span></td>"
            f"<td class='{tr_cls}'><span class='gfm-dot {outcome_cls}'></span>"
            f"<span class='{outcome_cls}'>{html.escape(row.outcome_short)}</span>{badge_html}</td>"
            f"<td class='gfm-td gfm-mono'>{html.escape(line_bits)}</td>"
            f"<td class='gfm-td gfm-mono'>{html.escape(row.score_display)}</td></tr>"
        )

    lines.append("</tbody></table></div>")
    return "".join(lines)


def game_flow_bar_chart_svg(rows: Sequence[GameFlowTimelineRow], *, max_height_px: int = 72) -> str:
    """Minimal horizontal bar strip: drive order, color by outcome, height ∝ yards. No axes."""
    if not rows:
        return ""
    max_y = max((r.net_yards_for_bar for r in rows), default=0)
    max_y = max(max_y, 1)
    n = len(rows)
    gap = 2
    total_w = 100  # percent
    bar_w = (total_w - gap * (n - 1)) / n if n else 0

    def color(st: OutcomeStyle) -> str:
        return {
            "score": "#22c55e",
            "turnover": "#ef4444",
            "punt": "#64748b",
            "half": "#eab308",
            "miss": "#a78bfa",
            "other": "#475569",
        }[st]

    parts: List[str] = []
    parts.append(
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 {max_height_px + 8}' "
        f"style='width:100%;max-height:{max_height_px + 12}px;display:block'>"
    )
    for i, r in enumerate(rows):
        x = i * (bar_w + gap)
        h = max(2, int(max_height_px * (r.net_yards_for_bar / max_y)))
        y0 = max_height_px - h
        parts.append(
            f"<rect x='{x:.3f}' y='{y0}' width='{bar_w:.3f}' height='{h}' "
            f"fill='{color(r.outcome_style)}' rx='1'/>"
        )
    parts.append("</svg>")
    return "".join(parts)

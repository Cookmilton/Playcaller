"""
Archived drive integrity audit — pure helpers for Streamlit debug UI.

Compares inferred end-of-drive classification vs ESPN drive metadata when present,
reconciles implied scoring to the session scoreboard, and surfaces ingest gaps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

from playcaller.game import (
    DRIVE_END_UNKNOWN,
    Drive,
    DriveFeedAuditSnapshot,
    Game,
)
from playcaller.live_data.drive_display import chronological_team_drive_indices
from playcaller.live_data.espn_game_state import parse_display_clock_seconds
from playcaller.reconciliation.drive_reconciler import (
    espn_outcome_bucket,
    inferred_outcome_bucket,
    reconcile_drive,
)

DriveAuditSeverity = Literal["clean", "warning", "critical"]

# Shared audit “lens” for archived drives + audit table (UI filter chips).
AuditLensChip = Literal["all", "score", "outcome", "clean"]

# Coarse UI category for drive headers / overlays (one primary label).
DriveAuditStatusKind = Literal[
    "clean",
    "score_conflict",
    "outcome_mismatch",
    "missing_incomplete",
    "warning_other",
]


def _down_distance_hint_from_play_text(text: str) -> str:
    if not (text or "").strip():
        return ""
    m = re.search(r"\b([1-4])(?:st|nd|rd|th)\s+and\s+(\d{1,2})\b", text.lower())
    if m:
        return f"{m.group(1)} & {m.group(2)}"
    return ""


def implied_points_for_drive(dr: Drive) -> int:
    """Legacy helper — play-inferred points only. Prefer :func:`reconcile_drive` for threaded scoring."""
    rec = reconcile_drive(dr, espn=dr.feed_audit)
    return int(rec.possession_points)


def _buckets_align(espn_b: str, inf_b: str) -> bool:
    if not espn_b:
        return True
    if espn_b == inf_b:
        return True
    if espn_b == "FG" and inf_b == "FG":
        return True
    if espn_b == "TD" and inf_b == "TD":
        return True
    # ESPN sometimes omits detail
    if espn_b in inf_b or inf_b in espn_b:
        return True
    return False


def espn_explicit_scoring_guess(audit: Optional[DriveFeedAuditSnapshot]) -> Optional[bool]:
    if audit is None:
        return None
    if audit.espn_is_score is not None:
        return audit.espn_is_score
    b = espn_outcome_bucket(audit)
    if b == "TD" or b == "FG":
        return True
    if b == "FG_MISS" or b == "PUNT" or b == "INT" or b == "FUMBLE" or b == "DOWNS":
        return False
    return None


def _severity_and_badge(
    flags: List[str],
    *,
    possession_pts: int,
    global_score_mismatch: bool,
    raw_outcome_disagree: bool,
    reconciler_error: bool,
    reconciler_warn: bool,
    reconciler_info: bool,
    outcome_resolved_info_only: bool,
) -> Tuple[DriveAuditSeverity, str]:
    """Post-reconciliation badges: 🔴 unresolved / score; ⚠️ warnings or provenance; ✅ clean."""
    text = " ".join(flags)
    if "Running implied score decreased" in text:
        return "critical", "🔴"
    if global_score_mismatch and possession_pts > 0:
        return "critical", "🔴"
    if reconciler_error:
        return "critical", "🔴"
    if flags or global_score_mismatch or reconciler_warn:
        return "warning", "⚠️"
    if reconciler_info and not outcome_resolved_info_only:
        return "warning", "⚠️"
    if raw_outcome_disagree and not outcome_resolved_info_only:
        return "warning", "⚠️"
    return "clean", "✅"


@dataclass(frozen=True)
class DriveAuditRow:
    """One drive’s audit — shared by ribbon, table, and expander badges."""

    drive_index: int
    chron_drive_number: int
    team_drive_number: int
    team_label: str
    possessing_side: Literal["offense", "defense"]
    severity: DriveAuditSeverity
    badge: str
    flags: Tuple[str, ...]
    outcome_reconciled: str
    outcome_inferred: str
    outcome_espn: str
    inferred_vs_espn_ok: bool
    outcome_mismatch: bool
    provenance_summary: str
    resolution_notes: Tuple[str, ...]
    reconciled_top_display: str
    inferred_outcome_code: str
    espn_outcome_code: str
    play_count: int
    total_yards: int
    time_elapsed_seconds: Optional[int]
    espn_top_display: str
    score_start_us: int
    score_start_them: int
    score_after_us: int
    score_after_them: int
    inferred_points: int
    field_start: str
    quarter_start: str
    clock_start: str
    first_play_dn_dist: str
    _table_row: Dict[str, Any] = field(repr=False)

    def to_table_row(self) -> Dict[str, Any]:
        return dict(self._table_row)

    @property
    def has_flags(self) -> bool:
        return bool(self.flags)

    @property
    def tooltip_line(self) -> str:
        side = self.team_label or ("Our O" if self.possessing_side == "offense" else "Our D")
        oc = (self.outcome_reconciled or self.outcome_inferred or "").strip()
        return f"{side} · {oc} · after {self.score_after_us}–{self.score_after_them}"


def archived_drive_expander_title_from_audit(drive: Drive, team_drive_index: int, ar: DriveAuditRow) -> str:
    """Archive expander title using reconciled outcome, plays, yards, TOP (single source with audit row)."""
    ab = str(getattr(drive, "feed_team_abbr", "") or "").strip()
    name = str(getattr(drive, "feed_team_display_name", "") or "").strip()
    if ab and name and ab.upper() != name.upper():
        team_part = f"{name} ({ab}) drive {team_drive_index}"
    elif name:
        team_part = f"{name} drive {team_drive_index}"
    elif ab:
        team_part = f"{ab} drive {team_drive_index}"
    else:
        side = "Our team" if drive.possessing_team == "offense" else "Opponent"
        team_part = f"{side} drive {team_drive_index}"
    detail = f"{ar.play_count} plays, {ar.total_yards} yards, {ar.reconciled_top_display}"
    oc = (ar.outcome_reconciled or "").strip() or "Drive"
    return f"{team_part} · {oc} — {detail}"


def audit_status_kind(row: DriveAuditRow) -> DriveAuditStatusKind:
    """Single primary category for headers — stable, UI-agnostic."""
    if row.severity == "critical":
        return "score_conflict"
    if row.severity != "clean" and row.outcome_mismatch:
        return "outcome_mismatch"
    if row.severity == "clean":
        return "clean"
    joined = " ".join(row.flags).lower()
    if any(
        s in joined
        for s in (
            "without feed_audit",
            "starting field position missing",
            "start clock missing",
            "start quarter missing",
            "field position not stored",
        )
    ):
        return "missing_incomplete"
    return "warning_other"


def audit_status_header_tag(row: DriveAuditRow) -> str:
    """Short bracket text for expander titles (keep compact)."""
    k = audit_status_kind(row)
    if k == "clean":
        return "clean"
    if k == "score_conflict":
        return "score Δ"
    if k == "outcome_mismatch":
        return "ESPN≠model"
    if k == "missing_incomplete":
        return "incomplete"
    return "review"


def filter_audit_rows_for_lens(
    report: "DriveAuditReport",
    *,
    show_all: bool,
    chip: AuditLensChip,
) -> List[DriveAuditRow]:
    """Same semantics as the Streamlit audit table: flagged-only unless ``show_all``."""
    rows = list(report.rows)
    if not show_all:
        # Keep drives with raw ESPN≠plays bucket disagreement even when reconciled cleanly (diagnostic).
        rows = [r for r in rows if r.severity != "clean" or r.outcome_mismatch]
    if chip == "all":
        return rows
    if chip == "score":
        return [r for r in rows if r.severity == "critical"]
    if chip == "outcome":
        return [r for r in rows if r.outcome_mismatch]
    if chip == "clean":
        return [r for r in rows if r.severity == "clean"]
    return rows


def drive_indices_matching_lens(
    report: "DriveAuditReport",
    *,
    show_all: bool,
    chip: AuditLensChip,
) -> frozenset[int]:
    """``game.drives`` indices that pass the current audit lens."""
    return frozenset(r.drive_index for r in filter_audit_rows_for_lens(report, show_all=show_all, chip=chip))


def filter_archived_indices_by_audit_lens(
    *,
    base_indices: List[int],
    report: "DriveAuditReport",
    show_all: bool,
    chip: AuditLensChip,
) -> List[int]:
    """Intersect feed-scoped archived indices with the audit lens."""
    allow = drive_indices_matching_lens(report, show_all=show_all, chip=chip)
    return [i for i in base_indices if i in allow]


def audit_actionable_explanation_lines(row: DriveAuditRow) -> List[str]:
    """
    Short, operator-facing lines (not a full duplicate of ``flags``).
    Order: outcome → scoring consistency → ingest/metadata.
    """
    lines: List[str] = []
    inf_c = (row.inferred_outcome_code or "").strip()
    espn_c = (row.espn_outcome_code or "").strip()
    if row.outcome_mismatch and inf_c and espn_c:
        lines.append(f"Inferred end **{inf_c}** vs ESPN drive result **{espn_c}** — check last plays or feed lag.")
    elif row.outcome_mismatch:
        lines.append("Inferred drive result disagrees with ESPN drive metadata — compare play list to Gamecast.")

    for f in row.flags:
        fl = f.strip()
        if "Running implied score decreased" in fl:
            lines.append("Implied score ran backward — drive order/team attribution may be wrong.")
        elif "ESPN marked scoring drive but inferred outcome has 0 pts" in fl:
            lines.append("ESPN treats this as scoring; model inferred 0 pts — PAT/2PT model or classification gap.")
        elif "Inferred scoring drive but ESPN is_score/result suggests none" in fl:
            lines.append("Model inferred points; ESPN metadata does not look scoring — verify TD/FG vs turnover.")
        elif "session scoreboard" in fl.lower():
            continue
        elif fl.startswith("⚠️ ESPN outcome"):
            if not row.outcome_mismatch:
                lines.append("Outcome wording differs between feed and model — see flags for detail.")
        elif "Play count archive=" in fl:
            lines.append("Archived play count differs from ESPN offensive play count — partial import or feed mismatch.")
        elif "Yards archive=" in fl:
            lines.append("Yardage differs materially from ESPN — check feed yards vs replay reconstruction.")
        elif "start clock equals end clock" in fl:
            lines.append("Feed shows identical start/end clock on a multi-play drive — possible ingest bug.")
        elif "Drive `start.clock`" in fl or "first play clock" in fl:
            lines.append("Kickoff vs scrimmage clock mismatch on this drive — verify possession start.")
        elif "older session JSON" in fl or "without feed_audit" in fl:
            lines.append("No ESPN snapshot on this drive — re-sync or reload from a feed-captured session.")
        elif "Field position not stored" in fl or "Starting field position missing" in fl:
            lines.append("Field position missing from feed snapshot — harder to validate context.")

    # De-dupe preserving order
    seen: set[str] = set()
    out: List[str] = []
    for x in lines:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out[:6]


def score_reconciliation_summary_lines(game: Game, report: DriveAuditReport) -> List[str]:
    """Compact bullets for score integrity (session board vs implied-from-drives)."""
    lines: List[str] = []
    if not report.rows:
        return lines
    ou, them = int(game.offense_points), int(game.defense_points)
    iu, it_ = report.implied_final_us, report.implied_final_them
    if report.global_score_mismatch:
        lines.append(
            f"Session scoreboard **{ou}–{them}** vs implied from drives **{iu}–{it_}** (TD counted as 7 incl. PAT)."
        )
        first_crit = next((r.chron_drive_number for r in report.rows if r.severity == "critical"), None)
        if first_crit is not None:
            lines.append(f"First **score conflict** signal at chron drive **{first_crit}**.")
        lines.append(
            "Common causes: missing opponent possession in archive, PAT/2PT vs TD=7 assumption, or scoreboard not synced."
        )
    else:
        lines.append(f"Implied totals **{iu}–{it_}** match the session scoreboard **{ou}–{them}** (within the TD=7 model).")

    first_flag = next((r.chron_drive_number for r in report.rows if r.severity != "clean"), None)
    if first_flag is not None and not report.global_score_mismatch:
        lines.append(f"First integrity flag at chron drive **{first_flag}** (outcome/metadata — not necessarily score).")
    return lines


@dataclass(frozen=True)
class DriveAuditReport:
    rows: Tuple[DriveAuditRow, ...]
    global_warn: Tuple[str, ...]
    global_score_mismatch: bool
    implied_final_us: int
    implied_final_them: int

    def score_ribbon_unavailable(self) -> bool:
        """True when cumulative implied scoring looks broken vs points on drives."""
        if not self.rows:
            return True
        last = self.rows[-1]
        total_inf = sum(r.inferred_points for r in self.rows)
        if total_inf > 0 and last.score_after_us == 0 and last.score_after_them == 0:
            return True
        return False


def compute_drive_audit(game: Game) -> DriveAuditReport:
    """
    Build per-drive audit rows (game.drives order) and global warnings.

    Uses ``possessing_team`` (offense = session OC / our team) for score reconciliation —
    same frame as ``game.offense_points`` / ``game.defense_points``.
    """
    if not game.drives:
        return DriveAuditReport((), (), False, 0, 0)

    team_seq = chronological_team_drive_indices(game)
    off_pts = def_pts = 0
    prev_off = prev_def = 0

    pending: List[Dict[str, Any]] = []

    for i, dr in enumerate(game.drives):
        audit = dr.feed_audit
        rec = reconcile_drive(dr, espn=audit)
        team_drive_n = team_seq[i] if i < len(team_seq) else i + 1
        team_label = (
            (dr.feed_team_display_name or dr.feed_team_abbr).strip()
            or ("Our team" if dr.possessing_team == "offense" else "Opponent")
        )
        side = dr.possessing_team
        assert side in ("offense", "defense")
        inf_b = inferred_outcome_bucket(dr)
        espn_b = espn_outcome_bucket(audit)
        outcome_mismatch = bool(espn_b and not _buckets_align(espn_b, inf_b))
        inf_label = dr.result.headline if dr.result else "—"

        explicit_line = ""
        if audit and (audit.espn_display_result or audit.espn_result_code):
            explicit_line = (audit.espn_display_result or audit.espn_result_code).strip()
        outcome_source = "Reconciled (ESPN + plays)" if audit else "Reconciled (plays only)"

        possession_pts = int(rec.possession_points)
        score_off_start = off_pts
        score_def_start = def_pts

        if side == "offense":
            off_pts += possession_pts
        else:
            def_pts += possession_pts

        flags: List[str] = []

        if off_pts < prev_off or def_pts < prev_def:
            flags.append("⚠️ Running implied score decreased (ordering/attribution bug)")

        if rec.raw_espn_vs_inferred_disagree:
            flags.append(
                f"ℹ️ Raw buckets ESPN **{espn_b}** vs plays **{inf_b}** — primary outcome **{rec.outcome_headline}** "
                f"(see Provenance)."
            )
        for af in rec.audit_flags:
            sym = "ℹ️" if af.severity == "info" else "⚠️" if af.severity == "warn" else "🔴"
            flags.append(f"{sym} [{af.field}] {af.reason}")

        if audit:
            guess = espn_explicit_scoring_guess(audit)
            if guess is True and possession_pts == 0:
                flags.append("⚠️ ESPN marked scoring drive but reconciled possession has 0 pts")
            if guess is False and possession_pts > 0:
                flags.append("⚠️ Reconciled scoring possession but ESPN is_score/result suggests none")

            if dr.play_count and audit.feed_offensive_plays is not None:
                if abs(int(dr.play_count) - int(audit.feed_offensive_plays)) > 2:
                    flags.append(
                        f"⚠️ Archived play count={dr.play_count} vs ESPN offensivePlays={audit.feed_offensive_plays}"
                    )
            if audit.feed_yards is not None and abs(int(dr.total_yards) - int(audit.feed_yards)) > 15:
                flags.append(f"⚠️ Sum yards in plays={dr.total_yards} vs ESPN yards={audit.feed_yards}")

            if audit.start_period is None or audit.start_period == 0:
                if rec.start_quarter <= 0:
                    flags.append("⚠️ Start quarter missing or 0")
            sp = audit.start_period
            if sp is not None and sp >= 4:
                sec = parse_display_clock_seconds(audit.start_clock_display)
                if sec is not None and sec >= 870:
                    flags.append("⚠️ Late-game quarter with ~full-period clock (verify start clock)")

            if (
                dr.play_count > 1
                and audit.start_clock_display
                and audit.end_clock_display
                and audit.start_clock_display == audit.end_clock_display
            ):
                flags.append("⚠️ Multi-play drive: start clock equals end clock (possible ingest bug)")

            if (
                audit.start_clock_display
                and audit.first_play_clock_display
                and audit.start_clock_display != audit.first_play_clock_display
            ):
                flags.append("⚠️ Drive `start.clock` ≠ first play clock (check kickoff vs scrimmage)")

        else:
            if getattr(dr, "feed_import_tag", None) == "espn":
                flags.append("⚠️ ESPN import without feed_audit (older session JSON?)")

        first_play_dn_dist = "— (not in summary JSON; use replay expander for reconstruction)"
        if dr.plays:
            hint = _down_distance_hint_from_play_text(dr.plays[0].description or "")
            if hint:
                first_play_dn_dist = f"{hint} (parsed from first play text)"

        field_start = rec.start_field_position.display
        if field_start == "—":
            flags.append("⚠️ Field position not stored for audit")

        quarter_start = str(rec.start_quarter) if rec.start_quarter > 0 else "—"
        clock_start = rec.start_clock if rec.start_clock != "—" else "—"
        if clock_start == "—":
            flags.append("⚠️ Start clock missing")

        vs_ok = not outcome_mismatch
        prov_summary = "; ".join(f"{k}→{v}" for k, v in sorted(rec.provenance.items()))
        table_row = {
            "#": i + 1,
            "Team #": team_drive_n,
            "Team": team_label,
            "Side": "Our O" if side == "offense" else "Our D",
            "Outcome (reconciled)": rec.outcome_headline,
            "Outcome (inferred)": inf_label,
            "Outcome (ESPN)": explicit_line or "—",
            "Provenance": prov_summary,
            "Outcome source": outcome_source,
            "Raw buckets match": "✓" if vs_ok else "✗",
            "Plays": rec.plays,
            "Yards": rec.yards,
            "TOP (display)": rec.time_of_possession_display,
            "ESPN TOP": (audit.time_elapsed_display if audit else "") or "—",
            "Score start (us–them)": f"{score_off_start}–{score_def_start}",
            "Field start": field_start,
            "Q start": quarter_start,
            "Clock start": clock_start,
            "1st & dist (start)": first_play_dn_dist,
            "Pts (reconciled)": possession_pts,
            "Flags": " ".join(flags) if flags else "",
        }

        af = rec.audit_flags
        r_err = any(x.severity == "error" for x in af)
        r_warn = any(x.severity == "warn" for x in af)
        r_info = any(x.severity == "info" for x in af)
        outcome_resolved_info_only = bool(
            rec.raw_espn_vs_inferred_disagree
            and len(af) == 1
            and af[0].severity == "info"
            and af[0].field == "outcome"
        )

        pending.append(
            {
                "drive_index": i,
                "chron_drive_number": i + 1,
                "team_drive_number": team_drive_n,
                "team_label": team_label,
                "possessing_side": side,
                "flags": tuple(flags),
                "outcome_reconciled": rec.outcome_headline,
                "outcome_inferred": inf_label,
                "outcome_espn": explicit_line or "—",
                "provenance_summary": prov_summary,
                "resolution_notes": rec.resolution_notes,
                "reconciled_top_display": rec.time_of_possession_display,
                "inferred_outcome_code": inf_b,
                "espn_outcome_code": espn_b,
                "inferred_vs_espn_ok": vs_ok,
                "outcome_mismatch": outcome_mismatch,
                "play_count": rec.plays,
                "total_yards": rec.yards,
                "time_elapsed_seconds": dr.time_elapsed_seconds,
                "espn_top_display": (audit.time_elapsed_display if audit else "") or "—",
                "score_start_us": score_off_start,
                "score_start_them": score_def_start,
                "score_after_us": off_pts,
                "score_after_them": def_pts,
                "inferred_points": possession_pts,
                "field_start": field_start,
                "quarter_start": quarter_start,
                "clock_start": clock_start,
                "first_play_dn_dist": first_play_dn_dist,
                "table_row": table_row,
                "reconciler_error": r_err,
                "reconciler_warn": r_warn,
                "reconciler_info": r_info,
                "outcome_resolved_info_only": outcome_resolved_info_only,
            }
        )

        prev_off, prev_def = off_pts, def_pts

    diff_off = off_pts - int(game.offense_points)
    diff_def = def_pts - int(game.defense_points)
    global_score_mismatch = diff_off != 0 or diff_def != 0
    global_warn_list: List[str] = []
    if global_score_mismatch:
        global_warn_list.append(
            f"⚠️ Drive outcomes imply **{off_pts}–{def_pts}** (TD=7 incl. PAT) but session scoreboard shows "
            f"**{game.offense_points}–{game.defense_points}** — diff ({diff_off:+d}, {diff_def:+d}). "
            "Possible missing/mislabeled drives, PAT/2PT mismatch vs assumption, or scoreboard not synced."
        )

    finalized: List[DriveAuditRow] = []
    for p in pending:
        sev, badge = _severity_and_badge(
            list(p["flags"]),
            possession_pts=int(p["inferred_points"]),
            global_score_mismatch=global_score_mismatch,
            raw_outcome_disagree=bool(p["outcome_mismatch"]),
            reconciler_error=bool(p["reconciler_error"]),
            reconciler_warn=bool(p["reconciler_warn"]),
            reconciler_info=bool(p["reconciler_info"]),
            outcome_resolved_info_only=bool(p["outcome_resolved_info_only"]),
        )
        finalized.append(
            DriveAuditRow(
                drive_index=int(p["drive_index"]),
                chron_drive_number=int(p["chron_drive_number"]),
                team_drive_number=int(p["team_drive_number"]),
                team_label=str(p["team_label"]),
                possessing_side=p["possessing_side"],  # type: ignore[arg-type]
                severity=sev,
                badge=badge,
                flags=p["flags"],  # type: ignore[arg-type]
                outcome_reconciled=str(p["outcome_reconciled"]),
                outcome_inferred=str(p["outcome_inferred"]),
                outcome_espn=str(p["outcome_espn"]),
                inferred_outcome_code=str(p.get("inferred_outcome_code") or ""),
                espn_outcome_code=str(p.get("espn_outcome_code") or ""),
                inferred_vs_espn_ok=bool(p["inferred_vs_espn_ok"]),
                outcome_mismatch=bool(p["outcome_mismatch"]),
                provenance_summary=str(p["provenance_summary"]),
                resolution_notes=tuple(p["resolution_notes"]),  # type: ignore[arg-type]
                reconciled_top_display=str(p["reconciled_top_display"]),
                play_count=int(p["play_count"]),
                total_yards=int(p["total_yards"]),
                time_elapsed_seconds=p["time_elapsed_seconds"],  # type: ignore[arg-type]
                espn_top_display=str(p["espn_top_display"]),
                score_start_us=int(p["score_start_us"]),
                score_start_them=int(p["score_start_them"]),
                score_after_us=int(p["score_after_us"]),
                score_after_them=int(p["score_after_them"]),
                inferred_points=int(p["inferred_points"]),
                field_start=str(p["field_start"]),
                quarter_start=str(p["quarter_start"]),
                clock_start=str(p["clock_start"]),
                first_play_dn_dist=str(p["first_play_dn_dist"]),
                _table_row=p["table_row"],
            )
        )

    return DriveAuditReport(
        rows=tuple(finalized),
        global_warn=tuple(global_warn_list),
        global_score_mismatch=global_score_mismatch,
        implied_final_us=off_pts,
        implied_final_them=def_pts,
    )


def compute_drive_audit_report(game: Game) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Backward-compatible (table dicts, global warnings). Prefer :func:`compute_drive_audit`."""
    rep = compute_drive_audit(game)
    return [r.to_table_row() for r in rep.rows], list(rep.global_warn)

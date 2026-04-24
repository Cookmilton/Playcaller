"""
Canonical drive reconciliation: ESPN completed-drive metadata + play-inferred stats → one truth.

Data flow (single source):
  ESPN raw snapshot + inferred Drive → reconcile_drive() → ReconciledDrive → archive header, audit, score thread.

UI and parsers call this module; they do not choose ESPN vs inferred ad hoc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

from playcaller.game import (
    DRIVE_END_FIELD_GOAL,
    DRIVE_END_FIELD_GOAL_MISS,
    DRIVE_END_PUNT,
    DRIVE_END_TOUCHDOWN,
    DRIVE_END_TURNOVER_FUMBLE,
    DRIVE_END_TURNOVER_INT,
    DRIVE_END_TURNOVER_ON_DOWNS,
    DRIVE_END_UNKNOWN,
    Drive,
    DriveFeedAuditSnapshot,
    DriveResult,
    _fmt_drive_clock,
    _drive_detail_line,
    drive_result_for_kind,
)
from playcaller.replay.previous_drive_replay import best_presnap_chain_for_drive_plays

# --- Precedence constants (readable rules) ------------------------------------

# ESPN coarse buckets we treat as authoritative for outcome when non-empty.
_ESPN_AUTHORITATIVE_BUCKETS = frozenset(
    {
        "TD",
        "FG",
        "FG_MISS",
        "PUNT",
        "INT",
        "FUMBLE",
        "DOWNS",
        "SAFETY",
        "END_HALF",
    }
)

_MAX_PLAY_COUNT_DELTA_WARN = 2
_MAX_YARDS_DELTA_WARN = 15


def _norm_espn_text(*parts: str) -> str:
    return " ".join(p for p in parts if (p or "").strip()).upper().strip()


def espn_outcome_bucket(audit: Optional[DriveFeedAuditSnapshot]) -> str:
    """Coarse ESPN result label (shared with audit diagnostics)."""
    if not audit:
        return ""
    s = _norm_espn_text(audit.espn_display_result, audit.espn_result_code)
    if not s:
        return ""
    if "TOUCHDOWN" in s or s in ("TD", "TDS"):
        return "TD"
    if "FIELD GOAL" in s:
        if "MISS" in s or "NO GOOD" in s or "BLOCK" in s:
            return "FG_MISS"
        return "FG"
    if "PUNT" in s:
        return "PUNT"
    if "INTERCEPT" in s or " INT" in s or s == "INT":
        return "INT"
    if "FUMBLE" in s:
        return "FUMBLE"
    if "DOWNS" in s or "TURNOVER ON DOWNS" in s:
        return "DOWNS"
    if "SAFETY" in s:
        return "SAFETY"
    if "END OF HALF" in s or "END HALF" in s:
        return "END_HALF"
    return s[:24]


def inferred_outcome_bucket(dr: Drive) -> str:
    k = dr.result.kind if dr.result else DRIVE_END_UNKNOWN
    if k == DRIVE_END_TOUCHDOWN:
        return "TD"
    if k == DRIVE_END_FIELD_GOAL:
        return "FG"
    if k == DRIVE_END_FIELD_GOAL_MISS:
        return "FG_MISS"
    if k == DRIVE_END_PUNT:
        return "PUNT"
    if k == DRIVE_END_TURNOVER_INT:
        return "INT"
    if k == DRIVE_END_TURNOVER_FUMBLE:
        return "FUMBLE"
    if k == DRIVE_END_TURNOVER_ON_DOWNS:
        return "DOWNS"
    return "OTHER"


def _espn_bucket_to_drive_kind(bucket: str) -> str:
    if bucket == "TD":
        return DRIVE_END_TOUCHDOWN
    if bucket == "FG":
        return DRIVE_END_FIELD_GOAL
    if bucket == "FG_MISS":
        return DRIVE_END_FIELD_GOAL_MISS
    if bucket == "PUNT":
        return DRIVE_END_PUNT
    if bucket == "INT":
        return DRIVE_END_TURNOVER_INT
    if bucket == "FUMBLE":
        return DRIVE_END_TURNOVER_FUMBLE
    if bucket == "DOWNS":
        return DRIVE_END_TURNOVER_ON_DOWNS
    return DRIVE_END_UNKNOWN


def _headline_for_espn_bucket(
    bucket: str,
    audit: Optional[DriveFeedAuditSnapshot],
    *,
    fallback_kind: str,
) -> str:
    explicit = ""
    if audit and (audit.espn_display_result or audit.espn_result_code):
        explicit = (audit.espn_display_result or audit.espn_result_code).strip()
    if explicit:
        return explicit.split("—")[0].strip()[:48]
    if bucket == "TD":
        return "Touchdown"
    if bucket == "FG":
        return "Field goal"
    if bucket == "FG_MISS":
        return "Missed field goal"
    if bucket == "PUNT":
        return "Punt"
    if bucket == "INT":
        return "Interception"
    if bucket == "FUMBLE":
        return "Fumble"
    if bucket == "DOWNS":
        return "Turnover on downs"
    if bucket == "SAFETY":
        return "Safety"
    if bucket == "END_HALF":
        return "End of half"
    res = drive_result_for_kind(fallback_kind, [])
    return res.headline


def _first_snap_field_display(drive: Drive) -> Optional[str]:
    if not drive.plays:
        return None
    chain, _err, _tag = best_presnap_chain_for_drive_plays(drive.plays)
    if not chain:
        return None
    terr, yl, _, _ = chain[0]
    if terr == "own":
        return f"Own {int(yl)}"
    return f"Opp {int(yl)}"


def _safety_from_last_play(drive: Drive) -> bool:
    if not drive.plays:
        return False
    last = drive.plays[-1]
    desc = (last.description or "").lower()
    rt = (last.result_type or "").lower()
    return "safety" in desc or rt == "safety"


def scoring_points_for_reconciled_kind(
    kind: str,
    drive: Drive,
    *,
    td_extra_point: Optional[str] = None,
) -> int:
    """Points for threaded scoreboard: TD default 7 (PAT); 8 after 2PT; 6 after missed PAT / failed 2PT."""
    rk = kind if kind in (
        DRIVE_END_TOUCHDOWN,
        DRIVE_END_FIELD_GOAL,
        DRIVE_END_FIELD_GOAL_MISS,
        DRIVE_END_PUNT,
        DRIVE_END_TURNOVER_INT,
        DRIVE_END_TURNOVER_FUMBLE,
        DRIVE_END_TURNOVER_ON_DOWNS,
        DRIVE_END_UNKNOWN,
    ) else DRIVE_END_UNKNOWN
    if rk == DRIVE_END_TOUCHDOWN:
        if td_extra_point == "two_point":
            return 8
        if td_extra_point == "pat_missed":
            return 6
        return 7
    if rk == DRIVE_END_FIELD_GOAL:
        return 3
    if drive.plays and _safety_from_last_play(drive) and rk == DRIVE_END_UNKNOWN:
        return 2
    return 0


@dataclass(frozen=True)
class FieldPosition:
    """Display-safe field position (no bare yard integers without side)."""

    display: str
    yard_line: Optional[int] = None


@dataclass
class EspnDriveRaw:
    """Fields taken from ESPN summary JSON (optional holes)."""

    outcome_display: Optional[str]
    outcome_code: Optional[str]
    plays: Optional[int]
    yards: Optional[int]
    time_of_possession_display: Optional[str]
    start_field_text: Optional[str]
    start_yard_line: Optional[int]
    start_quarter: Optional[int]
    start_clock: Optional[str]
    end_reason_display: Optional[str]
    first_play_quarter: Optional[int]
    first_play_clock: Optional[str]
    # PAT / 2PT after TD (from feed play text); drives TD scoring when present.
    td_extra_point: Optional[str] = None


@dataclass
class InferredDriveSnapshot:
    """Play-derived reconstruction for the same drive."""

    kind: str
    headline: str
    plays: int
    yards: int
    time_elapsed_seconds: int
    detail_line: str


@dataclass(frozen=True)
class AuditFlag:
    field: str
    espn_value: Any
    inferred_value: Any
    reconciled_value: Any
    reason: str
    severity: Literal["info", "warn", "error"]


@dataclass(frozen=True)
class ReconciledDrive:
    """Best-available truth for UI + threaded scoring."""

    outcome_kind: str
    outcome_headline: str
    plays: int
    yards: int
    time_of_possession_display: str
    start_field_position: FieldPosition
    start_quarter: int
    start_clock: str
    end_reason: Optional[str]
    possession_points: int
    espn_coarse_bucket: str
    provenance: Dict[str, Literal["espn", "inferred", "computed", "default"]]
    audit_flags: Tuple[AuditFlag, ...]
    raw_espn_vs_inferred_disagree: bool
    resolution_notes: Tuple[str, ...]


def _build_espn_raw(audit: Optional[DriveFeedAuditSnapshot]) -> EspnDriveRaw:
    if not audit:
        return EspnDriveRaw(
            outcome_display=None,
            outcome_code=None,
            plays=None,
            yards=None,
            time_of_possession_display=None,
            start_field_text=None,
            start_yard_line=None,
            start_quarter=None,
            start_clock=None,
            end_reason_display=None,
            first_play_quarter=None,
            first_play_clock=None,
            td_extra_point=None,
        )
    od = (audit.espn_display_result or audit.espn_result_code or "").strip() or None
    oc = (audit.espn_result_code or "").strip() or None
    ep = getattr(audit, "espn_td_extra_point", None)
    return EspnDriveRaw(
        outcome_display=od,
        outcome_code=oc,
        plays=audit.feed_offensive_plays,
        yards=audit.feed_yards,
        time_of_possession_display=(audit.time_elapsed_display or "").strip() or None,
        start_field_text=(audit.start_field_text or "").strip() or None,
        start_yard_line=audit.start_yard_line,
        start_quarter=audit.start_period,
        start_clock=(audit.start_clock_display or "").strip() or None,
        end_reason_display=(getattr(audit, "end_field_text", "") or "").strip() or None,
        first_play_quarter=audit.first_play_period,
        first_play_clock=(audit.first_play_clock_display or "").strip() or None,
        td_extra_point=ep,
    )


def _build_inferred_snapshot(dr: Drive, *, seconds_per_play: int = 38) -> InferredDriveSnapshot:
    plays = list(dr.plays)
    res = dr.result or DriveResult(kind=DRIVE_END_UNKNOWN, headline="Drive ended", detail_line="0 plays, 0 yards, 0:00")
    detail = res.detail_line if res.detail_line else _drive_detail_line(plays, seconds_per_play=seconds_per_play)
    net = sum(int(p.yards_gained) + (int(p.penalty_yards) if p.penalty else 0) for p in plays)
    n = len(plays)
    elapsed = max(0, int(seconds_per_play) * n)
    return InferredDriveSnapshot(
        kind=res.kind,
        headline=res.headline,
        plays=n,
        yards=net,
        time_elapsed_seconds=elapsed,
        detail_line=detail,
    )


def reconcile_drive(
    drive: Drive,
    *,
    espn: Optional[DriveFeedAuditSnapshot],
    seconds_per_play: int = 38,
) -> ReconciledDrive:
    """
    Merge ESPN drive snapshot and play-inferred ``Drive`` into one reconciled row.

    Precedence (outcome): ESPN bucket when authoritative → else inferred kind → else unknown (flagged).
    Precedence (plays/yards/TOP): ESPN when present and sane → else inferred.
    Precedence (start field): ESPN text/yl → else reconstructed first snap → else placeholder.
    Precedence (start Q/clock): ESPN start_* only — never end_* (explicit guard).
    Fallback Q/clock: first play clock from ESPN when start clock missing (still drive start, not end).
    """
    raw = _build_espn_raw(espn)
    inf = _build_inferred_snapshot(drive, seconds_per_play=seconds_per_play)
    prov: Dict[str, Literal["espn", "inferred", "computed", "default"]] = {}
    flags: List[AuditFlag] = []
    notes: List[str] = []

    espn_b = espn_outcome_bucket(espn)
    inf_b = inferred_outcome_bucket(drive)
    raw_disagree = bool(espn_b and inf_b and espn_b != inf_b)

    # --- Outcome ---
    outcome_kind = DRIVE_END_UNKNOWN
    outcome_headline = inf.headline
    if espn_b and espn_b in _ESPN_AUTHORITATIVE_BUCKETS:
        if espn_b == "SAFETY":
            outcome_kind = DRIVE_END_UNKNOWN
            outcome_headline = "Safety"
        else:
            outcome_kind = _espn_bucket_to_drive_kind(espn_b)
            outcome_headline = _headline_for_espn_bucket(espn_b, espn, fallback_kind=inf.kind)
        prov["outcome"] = "espn"
        if raw_disagree:
            flags.append(
                AuditFlag(
                    field="outcome",
                    espn_value=espn_b,
                    inferred_value=inf_b,
                    reconciled_value=outcome_headline,
                    reason="ESPN authoritative for drive result; play-inferred bucket retained as diagnostic",
                    severity="info",
                )
            )
            notes.append(f"Resolved: ESPN **{espn_b}** chosen over inferred **{inf_b}** (feed authoritative).")
    elif inf.kind != DRIVE_END_UNKNOWN:
        outcome_kind = inf.kind
        outcome_headline = inf.headline
        prov["outcome"] = "inferred"
        if not espn_b:
            flags.append(
                AuditFlag(
                    field="outcome",
                    espn_value=None,
                    inferred_value=inf_b,
                    reconciled_value=outcome_headline,
                    reason="ESPN outcome missing — used play-inferred classification",
                    severity="warn",
                )
            )
            notes.append("ESPN did not provide a drive outcome; using play-inferred result.")
    else:
        outcome_headline = "Unknown"
        prov["outcome"] = "default"
        flags.append(
            AuditFlag(
                field="outcome",
                espn_value=espn_b or None,
                inferred_value=inf_b,
                reconciled_value="Unknown",
                reason="Neither authoritative ESPN bucket nor a classified drive end",
                severity="error",
            )
        )
        notes.append("Could not determine a drive outcome from ESPN or plays.")

    # --- Plays / yards (prefer ESPN counts when present; warn on large deltas) ---
    plays = inf.plays
    yards = inf.yards
    if raw.plays is not None and int(raw.plays) > 0:
        plays = int(raw.plays)
        prov["plays"] = "espn"
        if abs(plays - inf.plays) > _MAX_PLAY_COUNT_DELTA_WARN:
            flags.append(
                AuditFlag(
                    field="plays",
                    espn_value=raw.plays,
                    inferred_value=inf.plays,
                    reconciled_value=plays,
                    reason="ESPN offensive play count differs materially from archived plays — ESPN value shown",
                    severity="warn",
                )
            )
            notes.append(f"Play count ESPN={raw.plays} vs archive plays={inf.plays} — showing **ESPN {plays}**.")
    else:
        prov["plays"] = "inferred"

    if raw.yards is not None:
        yards = int(raw.yards)
        prov["yards"] = "espn"
        if abs(yards - inf.yards) > _MAX_YARDS_DELTA_WARN:
            flags.append(
                AuditFlag(
                    field="yards",
                    espn_value=raw.yards,
                    inferred_value=inf.yards,
                    reconciled_value=yards,
                    reason="ESPN yards differ from sum of archived plays — ESPN value shown",
                    severity="warn",
                )
            )
    else:
        prov["yards"] = "inferred"

    # --- TOP ---
    top_s = _fmt_drive_clock(inf.time_elapsed_seconds)
    top_disp = top_s
    if raw.time_of_possession_display:
        top_disp = raw.time_of_possession_display
        prov["time_of_possession"] = "espn"
    else:
        prov["time_of_possession"] = "inferred"

    # --- Start field ---
    field_disp = "—"
    if raw.start_field_text:
        field_disp = raw.start_field_text
        if raw.start_yard_line is not None:
            field_disp = f"{field_disp} (yl={raw.start_yard_line})"
        prov["start_field"] = "espn"
    elif raw.start_yard_line is not None:
        field_disp = f"yl={raw.start_yard_line}"
        prov["start_field"] = "espn"
    else:
        snap = _first_snap_field_display(drive)
        if snap:
            field_disp = snap
            prov["start_field"] = "inferred"
            flags.append(
                AuditFlag(
                    field="start_field",
                    espn_value=None,
                    inferred_value=snap,
                    reconciled_value=snap,
                    reason="Start field from first reconstructed scrimmage position; ESPN summary missing",
                    severity="info",
                )
            )
        else:
            prov["start_field"] = "default"
            flags.append(
                AuditFlag(
                    field="start_field",
                    espn_value=None,
                    inferred_value=None,
                    reconciled_value="—",
                    reason="No ESPN field and no reconstructable first snap",
                    severity="warn",
                )
            )

    # --- Start quarter / clock (never use end_* for drive start) ---
    start_q = 0
    start_clk = "—"
    if raw.start_quarter is not None and raw.start_quarter > 0:
        start_q = int(raw.start_quarter)
        prov["start_quarter"] = "espn"
    elif raw.first_play_quarter is not None and raw.first_play_quarter > 0:
        start_q = int(raw.first_play_quarter)
        prov["start_quarter"] = "espn"
        flags.append(
            AuditFlag(
                field="start_quarter",
                espn_value=raw.start_quarter,
                inferred_value=raw.first_play_quarter,
                reconciled_value=start_q,
                reason="Drive start quarter taken from first play metadata; ESPN drive.start.period missing",
                severity="info",
            )
        )
    else:
        prov["start_quarter"] = "default"

    if raw.start_clock:
        start_clk = raw.start_clock
        prov["start_clock"] = "espn"
    elif raw.first_play_clock:
        start_clk = raw.first_play_clock
        prov["start_clock"] = "espn"
        flags.append(
            AuditFlag(
                field="start_clock",
                espn_value=raw.start_clock,
                inferred_value=raw.first_play_clock,
                reconciled_value=start_clk,
                reason="Drive start clock taken from first play; ESPN drive.start.clock missing",
                severity="info",
            )
        )
    else:
        prov["start_clock"] = "default"

    end_reason = raw.end_reason_display if raw.end_reason_display else None
    prov["end_reason"] = "espn" if end_reason else "default"

    fp = FieldPosition(display=field_disp, yard_line=raw.start_yard_line)

    possession_pts = scoring_points_for_reconciled_kind(
        outcome_kind,
        drive,
        td_extra_point=raw.td_extra_point,
    )
    if espn_b == "SAFETY":
        possession_pts = 2

    return ReconciledDrive(
        outcome_kind=outcome_kind,
        outcome_headline=outcome_headline,
        plays=plays,
        yards=yards,
        time_of_possession_display=top_disp,
        start_field_position=fp,
        start_quarter=start_q,
        start_clock=start_clk,
        end_reason=end_reason,
        possession_points=possession_pts,
        espn_coarse_bucket=espn_b,
        provenance=prov,
        audit_flags=tuple(flags),
        raw_espn_vs_inferred_disagree=raw_disagree,
        resolution_notes=tuple(notes),
    )


def archived_drive_expander_title(
    drive: Drive,
    team_drive_index: int,
    rec: ReconciledDrive,
) -> str:
    """Archive card title — team, drive #, reconciled outcome, plays/yards/TOP."""
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

    detail = f"{rec.plays} plays, {rec.yards} yards, {rec.time_of_possession_display}"
    return f"{team_part} · {rec.outcome_headline} — {detail}"

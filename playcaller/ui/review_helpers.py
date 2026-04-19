"""Helpers for the Review session / game review Streamlit page (no Streamlit imports)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from playcaller.domain import PASS_FAMILIES, RUN_FAMILIES, play_type_for_family
from playcaller.evaluation.audit import aggressiveness_label, situation_bucket
from playcaller.game import Game
from playcaller.session_game_metadata import compact_session_summary_line, read_session_metadata_dict
from playcaller.ui_components import FAM_LABEL, fmt_clock

_STATUS_LABELS = {
    "closed": "Complete — outcome linked",
    "open": "Open — no logged play yet",
    "void_undone": "Voided (undo)",
}


def audit_status_caption(status: Any) -> str:
    s = str(status or "")
    return _STATUS_LABELS.get(s, s or "Unknown")


def format_scrimmage_line(pre: Mapping[str, Any]) -> str:
    terr = str(pre.get("territory", "own"))
    try:
        yl = int(pre.get("yardline", 0))
    except (TypeError, ValueError):
        yl = 0
    side = "Own" if terr == "own" else "Opponent"
    return f"{side} {yl}"


def format_clock_line(pre: Mapping[str, Any]) -> str:
    try:
        q = int(pre.get("quarter", 1))
    except (TypeError, ValueError):
        q = 1
    try:
        sec = int(pre.get("seconds_remaining", 0))
    except (TypeError, ValueError):
        sec = 0
    return f"Q{q} · {fmt_clock(sec)} left"


def humanize_situation_bucket(key: str) -> str:
    """Turn metrics bucket keys into short plain English."""
    s = str(key).replace("_", " ").strip()
    if not s:
        return ""
    if s.lower().startswith("4th"):
        rest = s[4:].lstrip()
        return "4th down · " + rest.title() if rest else "4th down"
    return s.title()


def family_display_name(family: Any) -> str:
    f = str(family or "").strip()
    if not f:
        return "—"
    return FAM_LABEL.get(f, f.replace("_", " ").title())


def play_header_markdown(
    *,
    snap_index_1based: int,
    snap_count: int,
    row: Mapping[str, Any],
) -> str:
    pre = row.get("pre_snap") if isinstance(row.get("pre_snap"), dict) else {}
    los = format_scrimmage_line(pre)
    clk = format_clock_line(pre)
    try:
        dn = int(pre.get("down", 1))
    except (TypeError, ValueError):
        dn = 1
    try:
        dist = int(pre.get("distance", 10))
    except (TypeError, ValueError):
        dist = 10
    mode = str(pre.get("game_mode", "normal")).replace("_", " ")
    situ = humanize_situation_bucket(situation_bucket(pre)) if pre else ""
    status = audit_status_caption(row.get("status"))
    return (
        f"**Snap {snap_index_1based} of {snap_count}** · Drive session **{row.get('drive_epoch', '—')}** · "
        f"{status}  \n"
        f"**{dn} & {dist}** · **{los}** · {clk} · _{mode}_ \n"
        f"<span style='color:#64748b'>Situation group: {situ}</span>"
    )


def _family_match(rec: Mapping[str, Any]) -> Optional[bool]:
    act = rec.get("linked_actual")
    if not isinstance(act, dict):
        return None
    af = str(act.get("family", "") or "")
    sf = str(rec.get("selected_family", "") or "")
    if not af or not sf:
        return None
    return af == sf


def match_explanation(row: Mapping[str, Any]) -> Tuple[str, str]:
    """(short headline, one-line detail) for recommended vs actual."""
    act = row.get("linked_actual")
    sf = family_display_name(row.get("selected_family"))
    if not isinstance(act, dict):
        return ("No outcome yet", "Log this snap on the main page to compare to the recommendation.")
    af = family_display_name(act.get("family"))
    m = _family_match(row)
    reco_ag = aggressiveness_label(str(row.get("selected_family", "") or ""))
    act_ag = aggressiveness_label(str(act.get("family", "") or ""))
    if m is True:
        return (
            "Family match",
            f"Both sides are **{sf}** — same play family the model picked.",
        )
    if m is False:
        lane = ""
        if reco_ag != act_ag and reco_ag in ("run_family", "pass_family") and act_ag in (
            "run_family",
            "pass_family",
        ):
            lane = " Run/pass lane differed from the call."
        return (
            "Family mismatch",
            f"Model: **{sf}** · Actual: **{af}**.{lane}",
        )
    return ("Incomplete comparison", "Missing family on one side — check the detailed record below.")


def count_run_pass_from_game(game: Game) -> Tuple[int, int, int]:
    """Returns (run_count, pass_count, other_count) across logged plays."""
    runs = passes = other = 0
    for d in game.drives:
        for p in d.plays:
            pt = str(p.play_type or "").lower().strip()
            if pt == "run":
                runs += 1
            elif pt == "pass":
                passes += 1
            elif pt in ("qb_scramble", "two_point"):
                other += 1
            else:
                inferred = play_type_for_family(str(p.family or ""))
                if inferred == "run":
                    runs += 1
                elif inferred == "pass":
                    passes += 1
                else:
                    other += 1
    return runs, passes, other


def count_turnovers_from_game(game: Game) -> int:
    n = 0
    for d in game.drives:
        for p in d.plays:
            if p.turnover:
                n += 1
                continue
            rt = str(p.result_type or "").lower()
            if rt in ("interception", "fumble"):
                n += 1
                continue
            pr = str(p.pass_result or "").lower()
            if pr == "intercepted":
                n += 1
    return n


def red_zone_snap_count_from_audit(audit: Sequence[Mapping[str, Any]]) -> int:
    """Snaps (audit rows) where pre-snap is opponent territory inside the 20."""
    n = 0
    for r in audit:
        pre = r.get("pre_snap")
        if not isinstance(pre, dict):
            continue
        if str(pre.get("territory")) != "opponents":
            continue
        try:
            yl = int(pre.get("yardline", 99))
        except (TypeError, ValueError):
            continue
        if yl <= 20:
            n += 1
    return n


def red_zone_drive_count_from_audit(audit: Sequence[Mapping[str, Any]]) -> int:
    drives: set = set()
    for r in audit:
        pre = r.get("pre_snap")
        if not isinstance(pre, dict):
            continue
        if str(pre.get("territory")) != "opponents":
            continue
        try:
            yl = int(pre.get("yardline", 99))
        except (TypeError, ValueError):
            continue
        if yl <= 20:
            drives.add(r.get("drive_epoch"))
    return len(drives)


def drive_epoch_first_indices(audit: Sequence[Mapping[str, Any]]) -> List[Tuple[str, int, int]]:
    """(label, first_index, snap_count) for each drive_epoch in order of appearance."""
    order: List[Any] = []
    seen: set = set()
    for r in audit:
        e = r.get("drive_epoch")
        if e not in seen:
            seen.add(e)
            order.append(e)
    out: List[Tuple[str, int, int]] = []
    for e in order:
        indices = [i for i, r in enumerate(audit) if r.get("drive_epoch") == e]
        if not indices:
            continue
        first = min(indices)
        cnt = len(indices)
        out.append((f"Drive {e} · {cnt} engine call{'s' if cnt != 1 else ''}", first, cnt))
    return out


def compute_review_overview(game: Game, audit: Sequence[Mapping[str, Any]], ev: Mapping[str, Any]) -> Dict[str, Any]:
    total_logged = sum(len(d.plays) for d in game.drives)
    n_drives = len(game.drives)
    runs, passes, other = count_run_pass_from_game(game)
    tov = count_turnovers_from_game(game)
    rz_snaps = red_zone_snap_count_from_audit(audit)
    rz_drives = red_zone_drive_count_from_audit(audit)
    n_closed = int(ev.get("n_closed_vs_actual") or 0)
    rate = ev.get("family_match_rate")
    sm = read_session_metadata_dict(game)
    sid = str(sm.get("session_game_id") or "").strip() if sm else ""
    sim = sm.get("is_simulated") if sm and "is_simulated" in sm else None
    return {
        "game_id": str(game.game_id),
        "score": f"{game.offense_points}–{game.defense_points}",
        "possession_note": "Our offense" if game.possession == "offense" else "Opponent offense (session)",
        "total_drives": n_drives,
        "total_logged_plays": total_logged,
        "audit_rows": len(audit),
        "runs": runs,
        "passes": passes,
        "other_play_types": other,
        "turnovers_logged": tov,
        "red_zone_snaps_in_audit": rz_snaps,
        "red_zone_drive_sessions": rz_drives,
        "closed_with_actual": n_closed,
        "family_match_rate": rate,
        "session_summary_line": compact_session_summary_line(sm),
        "session_game_id_short": sid[:8] + "…" if len(sid) > 8 else sid,
        "session_is_simulated": sim,
    }


def build_takeaways(ev: Mapping[str, Any]) -> List[str]:
    """Short plain-English bullets; keep readable for coaches/operators."""
    out: List[str] = []
    n_total = int(ev.get("n_audit_total") or 0)
    n_closed = int(ev.get("n_closed_vs_actual") or 0)
    n_open = int(ev.get("n_open_unlogged") or 0)
    rate = ev.get("family_match_rate")
    agg = ev.get("aggressiveness_alignment_rate")
    tov = ev.get("turnover_rate_after_logged_play")

    if n_total == 0:
        return ["No recommendation records to review."]

    if n_closed < 3:
        out.append(
            f"Only **{n_closed}** logged snap(s) are tied to a recommendation — keep logging results "
            "on the main page for stronger conclusions."
        )
    else:
        if rate is not None:
            pct = int(round(float(rate) * 100))
            out.append(
                f"On **{n_closed}** snaps with outcomes, the **play family** matched **{pct}%** of the time."
            )

    if n_open:
        out.append(f"**{n_open}** recommendation(s) still **waiting for a logged play** (open rows).")

    weak = list(ev.get("situation_buckets_weak") or [])
    strong = list(ev.get("situation_buckets_strong") or [])
    if strong:
        w0 = strong[0]
        out.append(
            f"Strongest area: **{humanize_situation_bucket(str(w0.get('situation', '')))}** "
            f"({int(round(float(w0.get('match_rate', 0)) * 100))}% match, n={w0.get('n')})."
        )
    if weak:
        l0 = weak[0]
        out.append(
            f"Trickiest area: **{humanize_situation_bucket(str(l0.get('situation', '')))}** "
            f"({int(round(float(l0.get('mismatch_rate', 0)) * 100))}% mismatch, n={l0.get('n')})."
        )

    if agg is not None and n_closed >= 2:
        ap = int(round(float(agg) * 100))
        if ap >= 70:
            out.append(
                f"Run/pass **aggressiveness** (family lane) lined up **{ap}%** of the time — "
                "usually in the same broad category as what was run."
            )
        elif ap < 50:
            out.append(
                f"Run/pass lane differed often (**{100 - ap}%** of snaps) — worth spot-checking "
                "whether the model was too aggressive or too conservative for your script."
            )

    if tov is not None and n_closed >= 3 and float(tov) >= 0.15:
        out.append(
            f"Turnovers showed up on **{int(round(float(tov) * 100))}%** of logged plays — "
            "review those snaps for execution vs. situation, not just family match."
        )

    flags = list(ev.get("heuristic_flags") or [])
    if flags:
        out.append("Spot check: " + flags[0] + (" …" if len(flags) > 1 else ""))

    if not out:
        out.append("Generate calls and log plays to unlock richer takeaways.")

    return out


def overview_summary_sentence(overview: Mapping[str, Any], ev: Mapping[str, Any]) -> str:
    gid = overview.get("game_id", "")
    score = overview.get("score", "")
    rate = ev.get("family_match_rate")
    n_closed = int(ev.get("n_closed_vs_actual") or 0)
    ar = int(overview.get("audit_rows") or 0)
    lp = int(overview.get("total_logged_plays") or 0)
    base = (
        f"Session **{gid}** (score **{score}**): **{ar}** engine recommendation(s) on record, "
        f"**{lp}** logged plays across **{overview.get('total_drives', 0)}** drive(s)."
    )
    if rate is not None and n_closed > 0:
        pct = int(round(float(rate) * 100))
        base += f" Family match rate **{pct}%** over **{n_closed}** snaps with linked outcomes."
    elif n_closed == 0:
        base += " Link logged plays to see match rate."
    sess_line = overview.get("session_summary_line")
    prefix = ""
    if sess_line:
        prefix = f"**Operator session:** {sess_line}  \n\n"
    return prefix + base

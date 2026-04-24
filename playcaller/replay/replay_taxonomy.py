"""
Stable, football-readable **taxonomy** for archived-drive replay vs actual plays.

Used only for operator surfaces and analysis structs — not for scoring or dedup.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from playcaller.domain import PASS_FAMILIES, RUN_FAMILIES, ActualPlayResult


def _norm_play_routes(play: Mapping[str, Any]) -> str:
    if not isinstance(play, dict):
        return ""
    routes = play.get("routes") or play.get("route") or []
    if isinstance(routes, str):
        return routes.lower()
    if isinstance(routes, list) and routes:
        first = routes[0]
        if isinstance(first, dict):
            return str(first.get("name") or first.get("route") or "").lower()
        return str(first).lower()
    return ""


def replay_summary_bucket_from_recommend(result: Mapping[str, Any]) -> str:
    """
    Map current-engine output to a conservative display bucket.

    Uses situation ``bucket`` (short_yardage / medium_yardage / long_yardage / …) plus
    ``play_family`` and play metadata — deterministic, no randomness.
    """
    fam = str(result.get("play_family") or "").strip()
    sit = str(result.get("bucket") or "").strip().lower()
    play = result.get("play") if isinstance(result.get("play"), dict) else {}
    routes_txt = _norm_play_routes(play)

    if fam == "two_point":
        return "special teams / two-point"
    if "punt" in sit or fam == "punt":
        return "special teams / punt"
    if "field_goal" in sit or fam == "field_goal":
        return "special teams / field goal"
    if fam == "screen" or "screen" in routes_txt:
        return "screen"
    if fam == "draw":
        return "draw"
    if fam in ("inside_zone", "duo", "power"):
        if fam == "power":
            return "run off tackle / power"
        return "run inside / gap"
    if fam == "outside_zone":
        return "outside run"
    if fam == "qb_scramble" or "scramble" in routes_txt:
        return "QB scramble"

    if fam in PASS_FAMILIES:
        if sit == "long_yardage" and fam in ("dropback_pass", "play_action", "fade_iso"):
            return "deep pass"
        if sit == "medium_yardage" and fam in ("dropback_pass", "play_action"):
            return "medium pass"
        if sit == "short_yardage" or fam == "quick_game":
            return "short pass"
        if fam == "dropback_pass":
            return "dropback pass"
        if fam == "play_action":
            return "play action"
        if fam == "fade_iso":
            return "isolation / fade"
        return "pass"

    if sit:
        return sit.replace("_", " ")
    return "recommended call"


def model_summary_bucket_from_audit_row(row: Mapping[str, Any]) -> str:
    """
    Approximate :func:`replay_summary_bucket_from_recommend` for **stored** Generate-time rows.

    Uses ``selected_family``, situation ``bucket``, and play name only (no full play tree).
    """
    fam = str(row.get("selected_family") or "").strip()
    sit = str(row.get("bucket") or "").strip()
    name = str(row.get("selected_play_name") or "").strip()
    play: dict[str, Any] = {"name": name} if name else {}
    return replay_summary_bucket_from_recommend({"play_family": fam, "bucket": sit, "play": play})


def actual_play_summary_bucket(actual: ActualPlayResult) -> str:
    """Bucket logged truth for side-by-side comparison with :func:`replay_summary_bucket_from_recommend`."""
    rtype = str(actual.result_type or "").strip().lower()
    pr = str(actual.pass_result or "").strip().lower()
    pt = str(actual.play_type or "").strip().lower()
    fam = str(actual.family or "").strip()

    if actual.penalty:
        return "penalty / no-play" if rtype in ("no_play", "no play") else "penalty"
    if rtype == "kickoff":
        return "kickoff"
    if rtype in ("extra_point", "extra_point_miss"):
        return "extra point"
    if rtype == "punt" or fam == "punt":
        return "punt"
    if rtype == "field_goal":
        return "field goal"
    if rtype == "field_goal_miss":
        return "field goal miss"
    if actual.turnover or pr == "intercepted" or (actual.turnover_kind or "").lower() == "interception":
        return "turnover — interception"
    if (actual.turnover_kind or "").lower() == "fumble" or rtype == "fumble":
        return "turnover — fumble"
    if actual.sack or pr == "sack":
        return "sack"
    if actual.scramble or pt in ("qb_scramble", "qb_run"):
        return "QB scramble"
    if fam == "screen" or pt == "screen":
        return "screen"
    if fam == "draw" or pt == "draw":
        return "draw"
    if pt == "run" or fam in RUN_FAMILIES:
        if fam in ("outside_zone",):
            return "outside run"
        if fam in ("inside_zone", "duo", "power"):
            if fam == "power":
                return "run off tackle / power"
            return "run inside / gap"
        return "run"
    if pt == "pass" or fam in PASS_FAMILIES:
        if pr == "incomplete":
            return "pass — incomplete"
        y = int(actual.yards_gained)
        if y >= 20:
            return "deep pass"
        if y >= 10:
            return "medium pass"
        return "short pass"
    if fam == "two_point":
        return "special / two-point"
    if rtype in ("touchdown",) and actual.touchdown:
        return "touchdown"
    return "play"


def coarse_bucket_alignment(
    actual_bucket: str,
    replay_bucket: str,
    *,
    actual_run_pass: Optional[str],
    replay_run_pass: Optional[str],
) -> Optional[bool]:
    """
    Whether coarse scheme labels align — conservative: exact bucket string match, or same run/pass
    when both buckets use the same side (run vs pass family).
    """
    a = (actual_bucket or "").strip().lower()
    r = (replay_bucket or "").strip().lower()
    if a and r:
        if a == r:
            return True
        # Same broad side: both clearly run-ish or pass-ish words
        run_tokens = ("run", "draw", "inside", "outside", "gap", "power", "scramble")
        pass_tokens = ("pass", "screen", "play action", "fade", "dropback")
        a_run = any(t in a for t in run_tokens)
        r_run = any(t in r for t in run_tokens)
        a_pass = any(t in a for t in pass_tokens)
        r_pass = any(t in r for t in pass_tokens)
        if a_run and r_run and actual_run_pass == "Run" and replay_run_pass == "Run":
            return True
        if a_pass and r_pass and actual_run_pass == "Pass" and replay_run_pass == "Pass":
            return True
        return False
    return None